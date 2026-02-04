import AVFoundation
import WebRTC

final class AudioSessionManager {
    static let shared = AudioSessionManager()
    private init() {}

    func activateForRealtime() throws {
        try configureSession(
            category: .playAndRecord,
            mode: .default,
            options: [.allowBluetoothHFP, .defaultToSpeaker, .allowAirPlay],
            overrideSpeaker: true
        )
    }

    func activateForPlayback() throws {
        do {
            try configureSession(
                category: .playback,
                mode: .default,
                options: [.allowAirPlay],
                overrideSpeaker: false
            )
        } catch {
            // WebRTC can reject category switches while the audio unit is active.
            // Fallback to a less-attenuated playAndRecord configuration.
            try configureSession(
                category: .playAndRecord,
                mode: .default,
                options: [.allowBluetoothHFP, .defaultToSpeaker],
                overrideSpeaker: true
            )
        }
    }

    func activateForPlaybackAndRecord() throws {
        try configureSession(
            category: .playAndRecord,
            mode: .voiceChat,
            options: [.allowBluetoothHFP, .defaultToSpeaker],
            overrideSpeaker: true
        )
    }

    func deactivate() {
        let rtcSession = RTCAudioSession.sharedInstance()
        rtcSession.lockForConfiguration()
        defer { rtcSession.unlockForConfiguration() }

        let session = rtcSession.session
        try? session.setActive(false, options: .notifyOthersOnDeactivation)
        rtcSession.isAudioEnabled = false
    }

    private func configureSession(
        category: AVAudioSession.Category,
        mode: AVAudioSession.Mode,
        options: AVAudioSession.CategoryOptions,
        overrideSpeaker: Bool
    ) throws {
        let rtcSession = RTCAudioSession.sharedInstance()
        rtcSession.lockForConfiguration()
        defer { rtcSession.unlockForConfiguration() }

        let session = rtcSession.session
        if session.category != category || session.mode != mode || session.categoryOptions != options {
            try rtcSession.setCategory(category, mode: mode, options: options)
        }
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        if overrideSpeaker {
            try? session.overrideOutputAudioPort(.speaker)
        }
        rtcSession.isAudioEnabled = true
    }
}
