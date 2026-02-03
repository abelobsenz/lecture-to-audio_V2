import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: SettingsStore
    @Environment(\.dismiss) private var dismiss
    @State private var draft: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Section(header: Text("Server")) {
                    TextField("Server Base URL", text: $draft)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Example: http://192.168.1.100:8002")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        settings.serverBaseURL = draft
                        dismiss()
                    }
                }
            }
            .onAppear {
                draft = settings.serverBaseURL
            }
        }
    }
}
