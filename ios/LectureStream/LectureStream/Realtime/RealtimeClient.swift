import Foundation
import WebRTC

final class RealtimeClient {
    private let webRTC = WebRTCClient()
    private var pendingEvents: [String] = []
    private(set) var isResponseActive: Bool = false

    var onConnectionState: ((String) -> Void)?
    var onResponseStarted: (() -> Void)?
    var onResponseCompleted: (() -> Void)?
    var onTranscript: ((String) -> Void)?
    var onUserTranscriptCompleted: ((String) -> Void)?
    var onError: ((String) -> Void)?
    var onErrorDetailed: ((String?, String) -> Void)?

    init() {
        webRTC.onDataMessage = { [weak self] message in
            self?.handleMessage(message)
        }
        webRTC.onConnectionStateChange = { [weak self] state in
            self?.onConnectionState?(state.description)
        }
        webRTC.onDataChannelStateChange = { [weak self] state in
            if state == .open {
                self?.flushPendingEvents()
            }
        }
    }

    func connect(ephemeralKey: String) async throws {
        try await webRTC.connect(ephemeralKey: ephemeralKey)
    }

    func disconnect() {
        webRTC.disconnect()
    }

    func setMicrophoneEnabled(_ enabled: Bool) {
        webRTC.setMicrophoneEnabled(enabled)
    }

    func updateSession(instructions: String, voice: String) {
        let event: [String: Any] = [
            "type": "session.update",
            "session": [
                "type": "realtime",
                "instructions": instructions,
                "audio": [
                    "output": ["voice": voice],
                    "input": [
                        "transcription": ["model": "gpt-4o-mini-transcribe"],
                        "turn_detection": [
                            "type": "server_vad",
                            "create_response": false,
                            "interrupt_response": true
                        ]
                    ]
                ],
            ]
        ]
        send(event: event)
    }

    func sendUserText(_ text: String) {
        let event: [String: Any] = [
            "type": "conversation.item.create",
            "item": [
                "type": "message",
                "role": "user",
                "content": [
                    ["type": "input_text", "text": text]
                ]
            ]
        ]
        send(event: event)
    }

    func requestResponse() {
        let event: [String: Any] = [
            "type": "response.create"
        ]
        send(event: event)
    }

    func cancelResponse() {
        let event: [String: Any] = [
            "type": "response.cancel"
        ]
        send(event: event)
    }

    func send(event: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: event, options: []) else { return }
        guard let text = String(data: data, encoding: .utf8) else { return }
        if webRTC.isDataChannelOpen {
            print("Realtime OUT:", text)
            webRTC.send(text)
        } else {
            pendingEvents.append(text)
        }
    }

    private func flushPendingEvents() {
        guard webRTC.isDataChannelOpen else { return }
        while !pendingEvents.isEmpty {
            let text = pendingEvents.removeFirst()
            print("Realtime OUT:", text)
            webRTC.send(text)
        }
    }

    private func handleMessage(_ text: String) {
        print("Realtime IN:", text)
        guard let data = text.data(using: .utf8) else { return }
        guard let json = try? JSONSerialization.jsonObject(with: data, options: []) else { return }
        guard let payload = json as? [String: Any] else { return }
        let type = payload["type"] as? String ?? ""

        if type.contains("error") {
            if let errorPayload = payload["error"] as? [String: Any] {
                let message = errorPayload["message"] as? String ?? "Realtime error"
                let code = errorPayload["code"] as? String
                onErrorDetailed?(code, message)
                if code != "response_cancel_not_active" && code != "conversation_already_has_active_response" {
                    onError?(message)
                }
            } else {
                let message = payload["message"] as? String ?? "Realtime error"
                onErrorDetailed?(nil, message)
                onError?(message)
            }
        }

        if type == "response.created" {
            isResponseActive = true
            onResponseStarted?()
        }

        if isResponseCompleted(type: type) {
            isResponseActive = false
            onResponseCompleted?()
        }

        if type == "conversation.item.input_audio_transcription.completed",
           let transcript = extractTranscript(from: payload) {
            onUserTranscriptCompleted?(transcript)
            return
        }

        if isUserTranscriptEvent(type: type, payload: payload) {
            if let transcript = extractTranscript(from: payload) {
                onTranscript?(transcript)
            }
        }
    }

    private func isResponseCompleted(type: String) -> Bool {
        if type == "response.completed" || type == "response.done" {
            return true
        }
        return false
    }

    private func isUserTranscriptEvent(type: String, payload: [String: Any]) -> Bool {
        if type.contains("input_audio_transcription") {
            return true
        }
        if type.hasPrefix("conversation.item"),
           let item = payload["item"] as? [String: Any],
           let role = item["role"] as? String,
           role == "user",
           let content = item["content"] as? [[String: Any]] {
            return content.contains { entry in
                if let transcript = entry["transcript"] as? String, !transcript.isEmpty {
                    return true
                }
                if let entryType = entry["type"] as? String, entryType == "input_audio" {
                    return true
                }
                return false
            }
        }
        return false
    }

    private func extractTranscript(from payload: [String: Any]) -> String? {
        if let transcript = payload["transcript"] as? String {
            return transcript
        }
        if let data = payload["data"] as? [String: Any], let transcript = data["transcript"] as? String {
            return transcript
        }
        if let item = payload["item"] as? [String: Any],
           let content = item["content"] as? [[String: Any]] {
            for entry in content {
                if let transcript = entry["transcript"] as? String {
                    return transcript
                }
                if let text = entry["text"] as? String {
                    return text
                }
            }
        }
        return nil
    }
}

private extension RTCIceConnectionState {
    var description: String {
        switch self {
        case .new: return "new"
        case .checking: return "checking"
        case .connected: return "connected"
        case .completed: return "completed"
        case .failed: return "failed"
        case .disconnected: return "disconnected"
        case .closed: return "closed"
        case .count: return "count"
        @unknown default: return "unknown"
        }
    }
}
