import Foundation
import MediaPlayer

@MainActor
final class PlayerViewModel: ObservableObject {
    enum PlayerState: String {
        case idle
        case connecting
        case playing
        case paused
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
    private var pendingFollowup: Bool = false
    private var lastQuestion: String = ""
    private var lastQuestionContext: String = ""
    private var latestAssistantResponse: String = ""
    private var lastAssistantResponse: String = ""
    private var activeChunkIndex: Int? = nil
    private var rollbackChunkIndex: Int? = nil
    private var chunkIndex: Int = 0
    private var recentChunks: [RecentChunk] = []
    private var interruptObserver: NSObjectProtocol?
    private let progressKeyPrefix = "lectureProgress."

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
        realtime.onAssistantTextUpdate = { [weak self] text in
            Task { @MainActor in
                self?.latestAssistantResponse = text
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
                self?.handleInterruptRequest()
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

    func startPlayback(resumeFromSaved: Bool = true) {
        playbackTask?.cancel()
        realtime.disconnect()
        responseContinuation = nil
        responseToken = nil
        responseActive = false
        pendingResume = false
        pendingRetryChunk = false
        interruptedDuringChunk = false
        rollbackChunkIndex = nil
        activeChunkIndex = nil
        pendingQuestionTask?.cancel()
        isMicEnabled = false
        if resumeFromSaved, let saved = loadSavedProgress() {
            chunkIndex = saved
        } else {
            chunkIndex = 0
            clearSavedProgress()
        }
        recentChunks = []
        recentContextText = ""
        currentChunkText = ""
        currentSection = ""
        playbackTask = Task {
            await connectAndPlay()
        }
        updateNowPlayingInfo()
    }

    func restartPlayback() {
        clearSavedProgress()
        startPlayback(resumeFromSaved: false)
    }

    func stop() {
        playbackTask?.cancel()
        saveCurrentProgress()
        resumeAfterResponse()
        realtime.disconnect()
    }

    func pausePlayback() {
        guard state == .playing || state == .waitingToResume || state == .answering else { return }
        saveCurrentProgress()
        if realtime.isResponseActive {
            realtime.cancelResponse()
        }
        playbackTask?.cancel()
        state = .paused
        resumeAfterResponse()
        isMicEnabled = false
        realtime.setRemoteAudioMuted(true)
        realtime.setMicrophoneEnabled(false)
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
        realtime.setRemoteAudioMuted(true)
        realtime.setMicrophoneEnabled(true)
    }

    private func handleInterruptRequest() {
        if state == .playing {
            interruptPlayback()
            return
        }
        if state == .waitingToResume || state == .answering {
            beginFollowupInterrupt()
        }
    }

    private func beginFollowupInterrupt() {
        if realtime.isResponseActive {
            realtime.cancelResponse()
        }
        lastAssistantResponse = latestAssistantResponse
        pendingFollowup = true
        state = .interrupted
        isMicEnabled = true
        realtime.setRemoteAudioMuted(true)
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
        realtime.setRemoteAudioMuted(false)
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
            realtime.setRemoteAudioMuted(false)
            isMicEnabled = false
            state = .playing
            await loadLecture()
            clampProgressIfNeeded()
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
                    saveProgress(chunkIndex)
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
                    clearSavedProgress()
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
            lastAssistantResponse = latestAssistantResponse
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
            lastQuestion = question
            lastQuestionContext = context.contextText
            latestAssistantResponse = ""
            let prompt = "User question: \(question). Recent lecture context: \(context.contextText). Answer concisely, then ask 'Forge ahead?'"
            realtime.sendUserText(prompt)
            realtime.setRemoteAudioMuted(false)
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
        if normalized.contains("forge ahead") {
            resumeIfRequested()
        }
    }

    private func handleUserTranscriptCompleted(_ transcript: String) {
        lastTranscript = transcript
        let normalized = transcript.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if normalized.isEmpty {
            return
        }
        if normalized.contains("forge ahead") {
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
            if self.pendingFollowup {
                self.pendingFollowup = false
                await self.handleFollowupQuestion(transcript)
            } else {
                await self.handleQuestion(transcript)
            }
        }
    }

    private func handleFollowupQuestion(_ question: String) async {
        state = .answering
        do {
            let contextText: String
            if lastQuestionContext.isEmpty {
                let context = try await api.fetchContext(lectureId: lectureId, index: chunkIndex, window: 30)
                contextText = context.contextText
            } else {
                contextText = lastQuestionContext
            }
            latestAssistantResponse = ""
            let prompt = """
            Follow-up question: \(question).
            Previous question: \(lastQuestion).
            Recent lecture context: \(contextText).
            Previous answer (partial): \(lastAssistantResponse).
            Answer concisely, then ask 'Forge ahead?'
            """
            realtime.sendUserText(prompt)
            realtime.setRemoteAudioMuted(false)
            realtime.requestResponse()
            await waitForResponse(maxWaitSeconds: 45)
        } catch {
            errorMessage = error.localizedDescription
            state = .error
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

    private func progressKey() -> String {
        "\(progressKeyPrefix)\(lectureId)"
    }

    private func loadSavedProgress() -> Int? {
        let value = UserDefaults.standard.integer(forKey: progressKey())
        return value > 0 ? value : nil
    }

    private func saveProgress(_ index: Int) {
        guard index >= 0 else { return }
        UserDefaults.standard.set(index, forKey: progressKey())
    }

    private func saveCurrentProgress() {
        let resumeIndex = activeChunkIndex ?? chunkIndex
        saveProgress(resumeIndex)
    }

    private func clearSavedProgress() {
        UserDefaults.standard.removeObject(forKey: progressKey())
    }

    private func clampProgressIfNeeded() {
        guard let detail = lectureDetail else { return }
        if chunkIndex >= detail.numChunks {
            chunkIndex = 0
            clearSavedProgress()
        }
    }

}
