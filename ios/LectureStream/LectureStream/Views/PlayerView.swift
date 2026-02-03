import SwiftUI

struct PlayerView: View {
    private let lectureId: String
    @StateObject private var viewModel: PlayerViewModel

    init(lectureId: String, settings: SettingsStore) {
        self.lectureId = lectureId
        _viewModel = StateObject(wrappedValue: PlayerViewModel(lectureId: lectureId, settings: settings))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                statusSection
                currentChunkSection
                transcriptSection
                controlSection
                interruptSection
            }
            .padding()
        }
        .navigationTitle("Player")
        .onAppear {
            Task { await viewModel.loadLecture() }
        }
        .onDisappear {
            viewModel.toggleMicrophone(false)
            viewModel.stop()
        }
    }

    private var statusSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title = viewModel.lectureDetail?.title {
                Text(title)
                    .font(.title3)
                    .bold()
            }
            Text("State: \(viewModel.state.rawValue.capitalized)")
                .font(.headline)
            if !viewModel.connectionStatus.isEmpty {
                Text("Connection: \(viewModel.connectionStatus)")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if let error = viewModel.errorMessage {
                Text(error)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .background(Color.blue.opacity(0.08))
        .cornerRadius(12)
    }

    private var currentChunkSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Current Section")
                .font(.headline)
            Text(viewModel.currentSection.isEmpty ? "-" : viewModel.currentSection)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Divider()
            Text(viewModel.currentChunkText.isEmpty ? "Waiting for next chunk..." : viewModel.currentChunkText)
                .font(.body)
        }
        .padding()
        .background(Color.orange.opacity(0.08))
        .cornerRadius(12)
    }

    private var transcriptSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Recent Context (~30s)")
                .font(.headline)
            Text(viewModel.transcriptPreview.isEmpty ? "No transcript yet." : viewModel.transcriptPreview)
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color.gray.opacity(0.08))
        .cornerRadius(12)
    }

    private var controlSection: some View {
        HStack(spacing: 12) {
            Button(action: {
                viewModel.startPlayback()
            }) {
                Label("Play", systemImage: "play.fill")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)

            Button(action: {
                viewModel.interruptPlayback()
            }) {
                Label("Interrupt", systemImage: "pause.circle")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)

            Button(action: {
                viewModel.reconnect()
            }) {
                Label("Reconnect", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
        }
    }

    private var interruptSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Interrupt & Ask")
                .font(.headline)

            TextField("Type a question (optional)", text: $viewModel.questionDraft)
                .textFieldStyle(.roundedBorder)

            HStack(spacing: 12) {
                MicControlButton(isActive: $viewModel.isMicEnabled) { enabled in
                    viewModel.toggleMicrophone(enabled)
                }

                Button(action: {
                    viewModel.sendQuestion()
                }) {
                    Label("Send", systemImage: "paperplane.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }

            if viewModel.state == .waitingToResume || viewModel.state == .interrupted {
                Button(action: {
                    viewModel.resumeIfRequested()
                }) {
                    Label("Resume Lecture", systemImage: "forward.end")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding()
        .background(Color.purple.opacity(0.08))
        .cornerRadius(12)
    }
}

struct MicControlButton: View {
    @Binding var isActive: Bool
    var onChange: (Bool) -> Void
    @GestureState private var isPressing = false

    var body: some View {
        let press = DragGesture(minimumDistance: 0)
            .updating($isPressing) { _, state, _ in
                state = true
            }
            .onEnded { _ in
                if isActive {
                    isActive = false
                    onChange(false)
                }
            }

        return Button(action: {
            isActive.toggle()
            onChange(isActive)
        }) {
            Label(isActive ? "Mic On" : "Mic Off", systemImage: isActive ? "mic.fill" : "mic")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .simultaneousGesture(press)
        .onChange(of: isPressing) { newValue in
            if newValue && !isActive {
                isActive = true
                onChange(true)
            }
        }
    }
}
