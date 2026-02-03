import Foundation

@MainActor
final class LectureDetailViewModel: ObservableObject {
    @Published var detail: LectureDetail? = nil
    @Published var isLoading: Bool = false
    @Published var errorMessage: String? = nil

    private let lectureId: String
    private let api: APIClient

    init(lectureId: String, settings: SettingsStore) {
        self.lectureId = lectureId
        self.api = APIClient(settings: settings)
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            detail = try await api.fetchLectureDetail(id: lectureId)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
