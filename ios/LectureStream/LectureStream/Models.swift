import Foundation

enum LectureStatus: String, Codable {
    case queued
    case extracting
    case scripting
    case done
    case failed
}

struct LectureSummary: Identifiable, Codable, Hashable {
    let lectureId: String
    let title: String
    let createdAt: String
    let status: LectureStatus
    let durationEstimate: Int?

    var id: String { lectureId }

    enum CodingKeys: String, CodingKey {
        case lectureId = "lecture_id"
        case title
        case createdAt = "created_at"
        case status
        case durationEstimate = "duration_estimate"
    }
}

struct LectureDetail: Identifiable, Codable {
    let lectureId: String
    let title: String
    let createdAt: String
    let status: LectureStatus
    let sourceFilename: String?
    let durationEstimate: Int?
    let numChunks: Int
    let chunksReady: Bool
    let scriptReady: Bool

    var id: String { lectureId }

    enum CodingKeys: String, CodingKey {
        case lectureId = "lecture_id"
        case title
        case createdAt = "created_at"
        case status
        case sourceFilename = "source_filename"
        case durationEstimate = "duration_estimate"
        case numChunks = "num_chunks"
        case chunksReady = "chunks_ready"
        case scriptReady = "script_ready"
    }
}

struct LectureChunk: Codable {
    let chunkId: Int
    let approxSeconds: Int
    let text: String
    let spokenMath: [String]?
    let sectionName: String?
    let sourceRefs: [String]?

    enum CodingKeys: String, CodingKey {
        case chunkId = "chunk_id"
        case approxSeconds = "approx_seconds"
        case text
        case spokenMath = "spoken_math"
        case sectionName = "section_name"
        case sourceRefs = "source_refs"
    }
}

struct LectureChunkResponse: Codable {
    let lectureId: String
    let chunk: LectureChunk

    enum CodingKeys: String, CodingKey {
        case lectureId = "lecture_id"
        case chunk
    }
}

struct LectureContextResponse: Codable {
    let lectureId: String
    let index: Int
    let window: Int
    let approxSeconds: Int
    let contextText: String

    enum CodingKeys: String, CodingKey {
        case lectureId = "lecture_id"
        case index
        case window
        case approxSeconds = "approx_seconds"
        case contextText = "context_text"
    }
}

struct RealtimeInstructionResponse: Codable {
    let lectureId: String
    let instructions: String

    enum CodingKeys: String, CodingKey {
        case lectureId = "lecture_id"
        case instructions
    }
}

struct ClientSecret: Codable {
    let value: String
    let expiresAt: Int

    enum CodingKeys: String, CodingKey {
        case value
        case expiresAt = "expires_at"
    }
}

struct RealtimeTokenResponse: Codable {
    let clientSecret: ClientSecret
    let realtimeModel: String
    let voice: String
    let lectureId: String
    let serverTime: String

    enum CodingKeys: String, CodingKey {
        case clientSecret = "client_secret"
        case realtimeModel = "realtime_model"
        case voice
        case lectureId = "lecture_id"
        case serverTime = "server_time"
    }
}

struct RecentChunk {
    let text: String
    let approxSeconds: Int
}
