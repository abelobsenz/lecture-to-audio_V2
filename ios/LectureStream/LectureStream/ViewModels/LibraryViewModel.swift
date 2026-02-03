import Foundation

@MainActor
final class LibraryViewModel: ObservableObject {
    @Published var lectures: [LectureSummary] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String? = nil
    @Published var query: String = ""

    private var api: APIClient?

    func setSettings(_ settings: SettingsStore) {
        if api == nil {
            api = APIClient(settings: settings)
        }
    }

    func loadLectures() async {
        guard let api else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            lectures = try await api.fetchLectures()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var filteredLectures: [LectureSummary] {
        guard !query.isEmpty else { return lectures }
        return lectures.filter { $0.title.lowercased().contains(query.lowercased()) }
    }
}
