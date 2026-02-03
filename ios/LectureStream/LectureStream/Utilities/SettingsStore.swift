import Foundation

final class SettingsStore: ObservableObject {
    private enum Keys {
        static let serverBaseURL = "serverBaseURL"
    }

    @Published var serverBaseURL: String {
        didSet {
            UserDefaults.standard.set(serverBaseURL, forKey: Keys.serverBaseURL)
        }
    }

    init() {
        if let stored = UserDefaults.standard.string(forKey: Keys.serverBaseURL) {
            serverBaseURL = stored
        } else if let configured = Bundle.main.object(forInfoDictionaryKey: "SERVER_BASE_URL") as? String,
                  !configured.isEmpty,
                  configured != "$(SERVER_BASE_URL)" {
            serverBaseURL = configured
        } else {
            serverBaseURL = "http://localhost:8002"
        }
    }

    var baseURL: URL {
        let trimmed = serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let url = URL(string: trimmed) {
            return url
        }
        return URL(string: "http://localhost:8002")!
    }
}
