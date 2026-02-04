import Foundation
import WebRTC

final class WebRTCClient: NSObject {
    private let factory: RTCPeerConnectionFactory
    private var peerConnection: RTCPeerConnection?
    private var dataChannel: RTCDataChannel?
    private var localAudioTrack: RTCAudioTrack?

    var onDataMessage: ((String) -> Void)?
    var onConnectionStateChange: ((RTCIceConnectionState) -> Void)?
    var onError: ((Error) -> Void)?
    var onDataChannelStateChange: ((RTCDataChannelState) -> Void)?

    var isDataChannelOpen: Bool {
        dataChannel?.readyState == .open
    }

    override init() {
        RTCInitializeSSL()
        let encoderFactory = RTCDefaultVideoEncoderFactory()
        let decoderFactory = RTCDefaultVideoDecoderFactory()
        self.factory = RTCPeerConnectionFactory(encoderFactory: encoderFactory, decoderFactory: decoderFactory)
        super.init()
    }

    func connect(ephemeralKey: String) async throws {
        try AudioSessionManager.shared.activateForPlayback()

        let config = RTCConfiguration()
        config.sdpSemantics = .unifiedPlan
        config.continualGatheringPolicy = .gatherContinually

        let constraints = RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: ["DtlsSrtpKeyAgreement": "true"])
        guard let peerConnection = factory.peerConnection(with: config, constraints: constraints, delegate: self) else {
            throw URLError(.cannotConnectToHost)
        }

        let recvInit = RTCRtpTransceiverInit()
        recvInit.direction = .recvOnly
        _ = peerConnection.addTransceiver(of: .audio, init: recvInit)

        let audioSource = factory.audioSource(with: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil))
        let audioTrack = factory.audioTrack(with: audioSource, trackId: "audio0")
        audioTrack.isEnabled = false
        peerConnection.add(audioTrack, streamIds: ["stream0"])
        self.localAudioTrack = audioTrack

        let dataConfig = RTCDataChannelConfiguration()
        dataConfig.isOrdered = true
        let dataChannel = peerConnection.dataChannel(forLabel: "oai-events", configuration: dataConfig)
        dataChannel?.delegate = self
        self.dataChannel = dataChannel

        let offer = try await peerConnection.asyncOffer(constraints: constraints)
        try await peerConnection.asyncSetLocalDescription(offer)

        let answerSdp = try await Self.sendOfferToOpenAI(offer.sdp, ephemeralKey: ephemeralKey)
        let answer = RTCSessionDescription(type: .answer, sdp: answerSdp)
        try await peerConnection.asyncSetRemoteDescription(answer)

        self.peerConnection = peerConnection
    }

    func disconnect() {
        dataChannel?.close()
        peerConnection?.close()
        peerConnection = nil
        dataChannel = nil
        localAudioTrack = nil
        AudioSessionManager.shared.deactivate()
    }

    func send(_ text: String) {
        guard let channel = dataChannel else {
            print("WebRTC: data channel not ready; dropping message")
            return
        }
        if channel.readyState != .open {
            print("WebRTC: data channel state is \(channel.readyState.rawValue); message dropped")
            return
        }
        let buffer = RTCDataBuffer(data: text.data(using: .utf8) ?? Data(), isBinary: false)
        channel.sendData(buffer)
    }

    func setMicrophoneEnabled(_ enabled: Bool) {
        if enabled {
            do {
                try AudioSessionManager.shared.activateForPlaybackAndRecord()
            } catch {
                print("WebRTC: failed to activate playAndRecord: \(error)")
            }
            localAudioTrack?.isEnabled = true
        } else {
            localAudioTrack?.isEnabled = false
            do {
                try AudioSessionManager.shared.activateForPlayback()
            } catch {
                print("WebRTC: failed to activate playback: \(error)")
            }
        }
    }

    private static func sendOfferToOpenAI(_ sdp: String, ephemeralKey: String) async throws -> String {
        guard let url = URL(string: "https://api.openai.com/v1/realtime/calls") else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = sdp.data(using: .utf8)
        request.setValue("application/sdp", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(ephemeralKey)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        guard let answer = String(data: data, encoding: .utf8) else {
            throw URLError(.cannotDecodeContentData)
        }
        return answer
    }
}

extension WebRTCClient: RTCPeerConnectionDelegate {
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}

    func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {
        onConnectionStateChange?(newState)
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {
        dataChannel.delegate = self
        self.dataChannel = dataChannel
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd rtpReceiver: RTCRtpReceiver, streams: [RTCMediaStream]) {
        if let audioTrack = rtpReceiver.track as? RTCAudioTrack {
            audioTrack.isEnabled = true
            print("WebRTC: received remote audio track")
            if localAudioTrack?.isEnabled != true {
                do {
                    try AudioSessionManager.shared.activateForPlayback()
                } catch {
                    print("WebRTC: failed to re-activate playback session: \(error)")
                }
            }
        }
    }
}

extension WebRTCClient: RTCDataChannelDelegate {
    func dataChannelDidChangeState(_ dataChannel: RTCDataChannel) {
        print("WebRTC: data channel state = \(dataChannel.readyState.rawValue)")
        onDataChannelStateChange?(dataChannel.readyState)
    }

    func dataChannel(_ dataChannel: RTCDataChannel, didReceiveMessageWith buffer: RTCDataBuffer) {
        guard let text = String(data: buffer.data, encoding: .utf8) else { return }
        onDataMessage?(text)
    }
}

private extension RTCPeerConnection {
    func asyncOffer(constraints: RTCMediaConstraints) async throws -> RTCSessionDescription {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<RTCSessionDescription, Error>) in
            offer(for: constraints) { sdp, error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else if let sdp = sdp {
                    continuation.resume(returning: sdp)
                } else {
                    continuation.resume(throwing: URLError(.unknown))
                }
            }
        }
    }

    func asyncSetLocalDescription(_ sdp: RTCSessionDescription) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            setLocalDescription(sdp) { error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: ())
                }
            }
        }
    }

    func asyncSetRemoteDescription(_ sdp: RTCSessionDescription) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            setRemoteDescription(sdp) { error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: ())
                }
            }
        }
    }
}
