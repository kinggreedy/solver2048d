# Windows Capture Agent Guide - Solver 2048d

The client-side sync is run via a lightweight PowerShell agent on Windows. It captures the Android device screen using ADB and uploads the PNG screenshots to the Ubuntu solver app server.

---

## Prerequisites

1. **ADB Command Line**:
   - Install the Android SDK Platform Tools on Windows.
   - Ensure `adb.exe` is added to your Windows environment `PATH`.
2. **Android Debugging**:
   - Enable USB Debugging in developer settings on your phone.
   - Connect the phone via USB. Run `adb devices` to verify the phone is detected.
3. **Screen Mirroring (Optional)**:
   - Run `scrcpy` to view your phone screen in real time.

---

## Agent Configuration

The script is located under `client/capture_agent.ps1`. Before running, open it in an editor and check these variables at the top:

```powershell
$server = "http://localhost:5000"   # The IP of your Ubuntu server
$pollIntervalMs = 500              # How often (ms) the agent asks if a screenshot is needed
$errorRateLimitSeconds = 15        # Limits connection errors print rate
```

---

## How it Works

1. **Polling Loop**: Every 500ms, the script sends an HTTP GET to `$server/capture/poll`.
2. **Rate-Limited connection logging**: If the Ubuntu solver is not currently running, the agent will catch connection errors and output a `WARNING: Server is unavailable...` message at most once every 15 seconds to avoid spamming your terminal.
3. **Screenshot Execution**:
   - Once the server responds that a capture is requested (`capture_requested = true`), the agent runs:
     ```powershell
     adb exec-out screencap -p > latest.png
     ```
   - It then uploads the PNG using `curl.exe` to the server's `/capture/upload` endpoint.
