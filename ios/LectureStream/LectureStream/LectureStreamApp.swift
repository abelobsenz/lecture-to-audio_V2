import SwiftUI

@main
struct LectureStreamApp: App {
    @StateObject private var settings = SettingsStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(settings)
        }
    }
}

struct RootView: View {
    var body: some View {
        LibraryView()
    }
}
