import SwiftUI

struct LectureDetailView: View {
    let lecture: LectureSummary
    private let settings: SettingsStore
    @StateObject private var viewModel: LectureDetailViewModel

    init(lecture: LectureSummary, settings: SettingsStore) {
        self.lecture = lecture
        self.settings = settings
        _viewModel = StateObject(wrappedValue: LectureDetailViewModel(lectureId: lecture.lectureId, settings: settings))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(viewModel.detail?.title ?? lecture.title)
                .font(.title)
                .bold()
            Text(formatDate(viewModel.detail?.createdAt ?? lecture.createdAt))
                .foregroundStyle(.secondary)

            if let detail = viewModel.detail {
                HStack {
                    Text("Status: \(detail.status.rawValue.capitalized)")
                    Spacer()
                    Text(detail.chunksReady ? "Ready" : "Processing")
                        .foregroundStyle(detail.chunksReady ? .green : .orange)
                }
                if let duration = detail.durationEstimate {
                    Text("Estimated duration: \(formatDuration(duration))")
                }
                Text("Chunks: \(detail.numChunks)")
                    .foregroundStyle(.secondary)
            }

            NavigationLink {
                PlayerView(lectureId: lecture.lectureId, settings: settings)
            } label: {
                Text("Play")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.blue)
                    .foregroundStyle(.white)
                    .cornerRadius(12)
            }
            .disabled(viewModel.detail?.chunksReady != true)

            Spacer()
        }
        .padding()
        .navigationTitle("Lecture")
        .task {
            await viewModel.load()
        }
    }

    private func formatDate(_ iso: String) -> String {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: iso) {
            return date.formatted(date: .abbreviated, time: .shortened)
        }
        return iso
    }

    private func formatDuration(_ seconds: Int) -> String {
        let minutes = max(1, seconds / 60)
        return "\(minutes) min"
    }
}
