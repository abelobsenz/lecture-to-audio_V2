# LectureStream iOS

SwiftUI app for streaming interactive lectures from the FastAPI server using OpenAI Realtime over WebRTC.

## Requirements
- Xcode 15+ (iOS 16+)
- Physical iPhone recommended for microphone + Bluetooth

## Open the project
1. Open `ios/LectureStream/LectureStream.xcodeproj` in Xcode.
2. Resolve Swift Package dependencies when prompted (WebRTC).
3. Select a physical device and run.

## Configure SERVER_BASE_URL
- In the app, open **Settings** and set your server base URL.
  - Example: `http://192.168.1.100:8002`
- Ensure your iPhone can reach the server over LAN or a tunnel.

## Streaming flow
1. Tap **Play** on a lecture.
2. The app requests `/realtime-token` and `/realtime-instructions`, then connects to OpenAI Realtime via WebRTC.
3. It fetches `/chunk?index=N`, sends the chunk text into the Realtime session, and plays model audio.
4. Tap **Interrupt** (or use AirPods button) to pause chunk progression and ask a question.
5. The app fetches `/context` and asks the model to answer concisely, then waits for "Ready to continue?".

## Interrupt controls
- **AirPods / headset click**: toggles the Interrupt action while playing.
- **Action Button**:
  1) Open the Shortcuts app.
  2) Add the "Interrupt Lecture" shortcut from the LectureStream app.
  3) Assign it to the Action Button in Settings -> Action Button.

## Notes
- If the Realtime connection drops (token expired / network change), use **Reconnect**.
- Update the transcription model in `RealtimeClient.updateSession` if you prefer a different model.
