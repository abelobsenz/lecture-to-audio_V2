import Foundation

enum APIError: Error, LocalizedError {
    case invalidURL
    case badResponse(Int)
    case decodingFailed

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid server URL."
        case .badResponse(let code):
            return "Server error: \(code)."
        case .decodingFailed:
            return "Failed to decode response."
        }
    }
}

final class APIClient {
    private let settings: SettingsStore
    private let session: URLSession

    init(settings: SettingsStore, session: URLSession = .shared) {
        self.settings = settings
        self.session = session
    }

    func fetchLectures() async throws -> [LectureSummary] {
        try await request(path: "/lectures")
    }

    func fetchLectureDetail(id: String) async throws -> LectureDetail {
        try await request(path: "/lectures/\(id)")
    }

    func fetchChunk(lectureId: String, index: Int) async throws -> LectureChunkResponse {
        try await request(path: "/lectures/\(lectureId)/chunk", query: [URLQueryItem(name: "index", value: "\(index)")])
    }

    func fetchContext(lectureId: String, index: Int, window: Int) async throws -> LectureContextResponse {
        try await request(path: "/lectures/\(lectureId)/context", query: [
            URLQueryItem(name: "index", value: "\(index)"),
            URLQueryItem(name: "window", value: "\(window)")
        ])
    }

    func fetchRealtimeInstructions(lectureId: String) async throws -> RealtimeInstructionResponse {
        try await request(path: "/lectures/\(lectureId)/realtime-instructions")
    }

    func mintRealtimeToken(lectureId: String) async throws -> RealtimeTokenResponse {
        try await request(path: "/lectures/\(lectureId)/realtime-token", method: "POST")
    }

    private func request<T: Decodable>(
        path: String,
        query: [URLQueryItem] = [],
        method: String = "GET",
        body: Data? = nil
    ) async throws -> T {
        guard var components = URLComponents(url: settings.baseURL, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidURL
        }
        components.path = path
        if !query.isEmpty {
            components.queryItems = query
        }
        guard let url = components.url else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.badResponse(-1)
        }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.badResponse(http.statusCode)
        }

        let decoder = JSONDecoder()
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingFailed
        }
    }
}
