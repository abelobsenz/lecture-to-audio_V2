import SwiftUI

struct LibraryView: View {
    @EnvironmentObject private var settings: SettingsStore
    @StateObject private var viewModel = LibraryViewModel()
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            List {
                ForEach(viewModel.filteredLectures) { lecture in
                    NavigationLink(value: lecture) {
                        LectureCardView(lecture: lecture)
                    }
                }
            }
            .navigationTitle("Lecture Library")
            .searchable(text: $viewModel.query, prompt: "Search lectures")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Settings") { showSettings = true }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
                    .environmentObject(settings)
            }
            .navigationDestination(for: LectureSummary.self) { lecture in
                LectureDetailView(lecture: lecture, settings: settings)
            }
            .refreshable {
                await viewModel.loadLectures()
            }
            .onAppear {
                viewModel.setSettings(settings)
                Task { await viewModel.loadLectures() }
            }
        }
    }
}

struct LectureCardView: View {
    let lecture: LectureSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(lecture.title)
                .font(.headline)
            HStack {
                Text(formatDate(lecture.createdAt))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(lecture.status.rawValue.capitalized)
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(statusColor.opacity(0.15))
                    .foregroundStyle(statusColor)
                    .cornerRadius(8)
            }
            if let duration = lecture.durationEstimate {
                Text("~\(formatDuration(duration))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private var statusColor: Color {
        switch lecture.status {
        case .done:
            return .green
        case .failed:
            return .red
        case .extracting, .scripting, .queued:
            return .orange
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
