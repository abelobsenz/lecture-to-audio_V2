import AVFoundation
import WebRTC

final class AudioSessionManager {
    static let shared = AudioSessionManager()
    private init() {}

    func activateForPlayback() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default, options: [.allowAirPlay])
        try session.setActive(true, options: .notifyOthersOnDeactivation)

        let rtcSession = RTCAudioSession.sharedInstance()
        rtcSession.isAudioEnabled = true
    }

    func activateForPlaybackAndRecord() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetoothHFP, .defaultToSpeaker])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        try? session.overrideOutputAudioPort(.speaker)

        let rtcSession = RTCAudioSession.sharedInstance()
        rtcSession.isAudioEnabled = true
    }

    func deactivate() {
        let session = AVAudioSession.sharedInstance()
        try? session.setActive(false, options: .notifyOthersOnDeactivation)

        let rtcSession = RTCAudioSession.sharedInstance()
        rtcSession.isAudioEnabled = false
    }
}
