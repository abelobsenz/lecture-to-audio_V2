import Foundation

final class InterruptCoordinator {
    static let shared = InterruptCoordinator()
    static let notification = Notification.Name("LectureStreamInterruptRequested")

    private init() {}

    func trigger() {
        NotificationCenter.default.post(name: Self.notification, object: nil)
    }
}
