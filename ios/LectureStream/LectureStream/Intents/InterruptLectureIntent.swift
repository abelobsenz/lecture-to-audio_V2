import AppIntents

struct InterruptLectureIntent: AppIntent {
    static var title: LocalizedStringResource = "Interrupt Lecture"
    static var description = IntentDescription("Interrupt the current lecture playback.")
    static var openAppWhenRun: Bool = true

    func perform() async throws -> some IntentResult {
        InterruptCoordinator.shared.trigger()
        return .result()
    }
}

// AppShortcutsProvider API varies by SDK version; keep the intent only for now.
