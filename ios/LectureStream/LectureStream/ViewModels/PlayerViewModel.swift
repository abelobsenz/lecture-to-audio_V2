import Foundation
import MediaPlayer

@MainActor
final class PlayerViewModel: ObservableObject {
    enum PlayerState: String {
        case idle
        case connecting
        case playing
        case interrupted
        case answering
        case waitingToResume
        case finished
        case error
    }

    @Published var state: PlayerState = .idle
    @Published var connectionStatus: String = ""
    @Published var currentChunkText: String = ""
    @Published var currentSection: String = ""
    @Published var recentContextText: String = ""
    @Published var transcriptPreview: String = ""
    @Published var lastTranscript: String = ""
    @Published var errorMessage: String? = nil
    @Published var questionDraft: String = ""
    @Published var isMicEnabled: Bool = false
    @Published var lectureDetail: LectureDetail? = nil

    private let lectureId: String
    private let api: APIClient
    private let realtime = RealtimeClient()
    private var playbackTask: Task<Void, Never>? = nil
    private var responseContinuation: CheckedContinuation<Void, Never>? = nil
    private var responseToken: UUID? = nil
    private var interruptedDuringChunk: Bool = false
    private var pendingRetryChunk: Bool = false
    private var pendingResume: Bool = false
    private var responseActive: Bool = false
    private var errorRecoveryAttempts: Int = 0
    private var lastErrorAt: Date? = nil
    private var pendingQuestionTask: Task<Void, Never>? = nil
    private var activeChunkIndex: Int? = nil
    private var rollbackChunkIndex: Int? = nil
    private var chunkIndex: Int = 0
    private var recentChunks: [RecentChunk] = []
    private var interruptObserver: NSObjectProtocol?

    init(lectureId: String, settings: SettingsStore) {
        self.lectureId = lectureId
        self.api = APIClient(settings: settings)

        realtime.onConnectionState = { [weak self] status in
            Task { @MainActor in
                self?.connectionStatus = status
                if status == "failed" || status == "disconnected" {
                    self?.errorMessage = "Realtime connection lost."
                    self?.state = .error
                }
            }
        }
        realtime.onResponseCompleted = { [weak self] in
            Task { @MainActor in
                self?.resumeAfterResponse()
            }
        }
        realtime.onResponseStarted = { [weak self] in
            Task { @MainActor in
                self?.responseActive = true
            }
        }
        realtime.onTranscript = { [weak self] transcript in
            Task { @MainActor in
                self?.lastTranscript = transcript
                self?.detectResumeCommand(in: transcript)
            }
        }
        realtime.onUserTranscriptCompleted = { [weak self] transcript in
            Task { @MainActor in
                self?.handleUserTranscriptCompleted(transcript)
            }
        }
        realtime.onError = { [weak self] message in
            Task { @MainActor in
                guard let self else { return }
                self.errorMessage = message
            }
        }
        realtime.onErrorDetailed = { [weak self] code, message in
            Task { @MainActor in
                self?.handleRealtimeError(code: code, message: message)
            }
        }

        interruptObserver = NotificationCenter.default.addObserver(
            forName: InterruptCoordinator.notification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.interruptPlayback()
            }
        }

        configureRemoteCommands()
    }

    deinit {
        if let observer = interruptObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    func loadLecture() async {
        do {
            lectureDetail = try await api.fetchLectureDetail(id: lectureId)
        } catch {
            errorMessage = error.localizedDescription
            state = .error
        }
    }

    func startPlayback() {
        playbackTask?.cancel()
        chunkIndex = 0
        recentChunks = []
        recentContextText = ""
        currentChunkText = ""
        currentSection = ""
        playbackTask = Task {
            await connectAndPlay()
        }
        updateNowPlayingInfo()
    }

    func reconnect() {
        realtime.disconnect()
        startPlayback()
    }

    func stop() {
        playbackTask?.cancel()
        resumeAfterResponse()
        realtime.disconnect()
    }

    func interruptPlayback() {
        guard state == .playing else { return }
        state = .interrupted
        interruptedDuringChunk = true
        pendingRetryChunk = true
        if let active = activeChunkIndex {
            rollbackChunkIndex = active
        } else {
            rollbackChunkIndex = chunkIndex
        }
        if realtime.isResponseActive {
            realtime.cancelResponse()
        }
        isMicEnabled = true
        realtime.setMicrophoneEnabled(true)
    }

    func sendQuestion() {
        let question = questionDraft.isEmpty ? lastTranscript : questionDraft
        guard !question.isEmpty else { return }
        questionDraft = ""
        Task {
            await handleQuestion(question)
        }
    }

    func resumeIfRequested() {
        guard state == .waitingToResume || state == .interrupted else { return }
        if responseActive {
            pendingResume = true
            state = .waitingToResume
            return
        }
        state = .playing
        pendingResume = false
        isMicEnabled = false
        realtime.setMicrophoneEnabled(false)
        playbackTask?.cancel()
        playbackTask = Task {
            await playLoop()
        }
    }

    func toggleMicrophone(_ enabled: Bool) {
        isMicEnabled = enabled
        realtime.setMicrophoneEnabled(enabled)
    }

    private func connectAndPlay() async {
        state = .connecting
        do {
            let token = try await api.mintRealtimeToken(lectureId: lectureId)
            let instructions = try await api.fetchRealtimeInstructions(lectureId: lectureId)
            try await realtime.connect(ephemeralKey: token.clientSecret.value)
            realtime.updateSession(instructions: instructions.instructions, voice: token.voice)
            realtime.setMicrophoneEnabled(false)
            isMicEnabled = false
            state = .playing
            await loadLecture()
            updateNowPlayingInfo()
            await playLoop()
        } catch {
            errorMessage = error.localizedDescription
            state = .error
        }
    }

    private func playLoop() async {
        while state == .playing {
            if Task.isCancelled { break }
            do {
                if let rollback = rollbackChunkIndex {
                    chunkIndex = rollback
                    rollbackChunkIndex = nil
                }
                let response = try await api.fetchChunk(lectureId: lectureId, index: chunkIndex)
                let chunk = response.chunk
                activeChunkIndex = chunkIndex
                currentChunkText = chunk.text
                currentSection = chunk.sectionName ?? ""

                while responseActive && state == .playing {
                    try? await Task.sleep(nanoseconds: 200_000_000)
                }

                let startedAt = Date()
                realtime.sendUserText("Lecture chunk \(chunk.chunkId): \(chunk.text)")
                realtime.requestResponse()

                let timeout = max(30, (chunk.approxSeconds * 2) + 10)
                await waitForResponse(maxWaitSeconds: timeout)

                if state == .playing && !interruptedDuringChunk {
                    let elapsed = Date().timeIntervalSince(startedAt)
                    let remaining = TimeInterval(chunk.approxSeconds) - elapsed
                    if remaining > 0 {
                        try? await Task.sleep(nanoseconds: UInt64(remaining * 1_000_000_000))
                    }
                    updateRecentContext(with: chunk)
                    chunkIndex += 1
                    activeChunkIndex = nil
                } else if state == .playing && pendingRetryChunk {
                    // Replay the same chunk after an interruption to avoid skipping content.
                    pendingRetryChunk = false
                }
                interruptedDuringChunk = false
                if state != .playing {
                    break
                }
                if let detail = lectureDetail, chunkIndex >= detail.numChunks {
                    state = .finished
                    break
                }
            } catch {
                if let apiError = error as? APIError, case .badResponse(let code) = apiError, code == 404 {
                    state = .finished
                    break
                } else {
                    errorMessage = error.localizedDescription
                    state = .error
                    break
                }
            }
        }
    }

    private func waitForResponse(maxWaitSeconds: Int) async {
        await withCheckedContinuation { continuation in
            responseContinuation = continuation
            let token = UUID()
            responseToken = token
            Task { @MainActor [weak self] in
                // Safety timeout to avoid leaked continuation if no response event arrives.
                let nanos = UInt64(maxWaitSeconds) * 1_000_000_000
                try? await Task.sleep(nanoseconds: nanos)
                guard let self else { return }
                if self.responseToken == token {
                    self.resumeAfterResponse()
                }
            }
        }
    }

    private func resumeAfterResponse() {
        responseContinuation?.resume()
        responseContinuation = nil
        responseToken = nil
        responseActive = false
        if state == .answering {
            state = .waitingToResume
            isMicEnabled = true
            realtime.setMicrophoneEnabled(true)
            return
        } else if state == .playing && pendingRetryChunk {
            // Ensure we keep the current chunk if we were interrupted mid-way.
            pendingRetryChunk = false
        } else if pendingResume {
            resumeIfRequested()
        }
    }

    private func handleQuestion(_ question: String) async {
        state = .answering
        do {
            let context = try await api.fetchContext(lectureId: lectureId, index: chunkIndex, window: 30)
            let prompt = "User question: \(question). Recent lecture context: \(context.contextText). Answer concisely, then ask 'Ready to continue?'"
            realtime.sendUserText(prompt)
            realtime.requestResponse()
            await waitForResponse(maxWaitSeconds: 45)
        } catch {
            errorMessage = error.localizedDescription
            state = .error
        }
    }

    private func handleRealtimeError(code: String?, message: String) {
        // Benign errors we can safely ignore.
        if code == "response_cancel_not_active" || code == "conversation_already_has_active_response" {
            errorMessage = message
            return
        }

        // Recovery path: restart from the most recent chunk.
        let now = Date()
        if let last = lastErrorAt, now.timeIntervalSince(last) < 15 {
            errorRecoveryAttempts += 1
        } else {
            errorRecoveryAttempts = 1
        }
        lastErrorAt = now

        if errorRecoveryAttempts >= 3 {
            errorMessage = message
            state = .error
            return
        }

        errorMessage = "Recovered from error: \(message)"
        pendingRetryChunk = true
        state = .playing
        playbackTask?.cancel()
        playbackTask = Task {
            await playLoop()
        }
    }

    private func updateRecentContext(with chunk: LectureChunk) {
        recentChunks.append(RecentChunk(text: chunk.text, approxSeconds: chunk.approxSeconds))
        var total = recentChunks.reduce(0) { $0 + $1.approxSeconds }
        while total > 30, !recentChunks.isEmpty {
            let removed = recentChunks.removeFirst()
            total -= removed.approxSeconds
        }
        recentContextText = recentChunks.map { $0.text }.joined(separator: "\n")
        transcriptPreview = recentContextText
    }

    private func detectResumeCommand(in transcript: String) {
        let normalized = transcript.lowercased()
        if normalized.contains("ok") || normalized.contains("okay") || normalized.contains("continue") {
            resumeIfRequested()
        }
    }

    private func handleUserTranscriptCompleted(_ transcript: String) {
        lastTranscript = transcript
        let normalized = transcript.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if normalized.isEmpty {
            return
        }
        if normalized.contains("ok") || normalized.contains("okay") || normalized.contains("continue") || normalized.contains("resume") {
            resumeIfRequested()
            return
        }
        guard state == .interrupted || state == .answering else { return }
        // Avoid firing multiple times if the user keeps speaking; debounce to the last completed transcript.
        pendingQuestionTask?.cancel()
        pendingQuestionTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard let self else { return }
            self.isMicEnabled = false
            self.realtime.setMicrophoneEnabled(false)
            self.questionDraft = ""
            await self.handleQuestion(transcript)
        }
    }

    private func configureRemoteCommands() {
        let commandCenter = MPRemoteCommandCenter.shared()
        commandCenter.togglePlayPauseCommand.isEnabled = true
        commandCenter.togglePlayPauseCommand.addTarget { [weak self] _ in
            guard let self else { return .commandFailed }
            if self.state == .playing {
                self.interruptPlayback()
                return .success
            }
            return .commandFailed
        }
    }

    private func updateNowPlayingInfo() {
        let title = lectureDetail?.title ?? "Lecture"
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: "LectureStream"
        ]
    }
}
