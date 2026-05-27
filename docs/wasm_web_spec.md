# WebAssembly-Powered Backendless Web App Specification

This document details the architecture and implementation specification for porting the PyQt6 2048 Solver interface to a web application running the Python engine and Expectimax solver directly in the browser via **WebAssembly (Pyodide)**.

---

## SECTION 1: Pure Client-Side App (Core WebAssembly App)

This section covers features that run 100% in the browser sandbox. The server only acts as a static file host.

```mermaid
graph TD
    subgraph Browser Sandbox (HTML5 / CSS3 / ES6)
        UI[Glassmorphic HTML5 UI] <--> JS[JS App Controller / app.js]
        JS <--> Storage[(HTML5 LocalStorage)]
        
        subgraph WebAssembly Runtime (Pyodide)
            Py[Python CPython Interpreter] <--> MEMFS[(Virtual MEMFS)]
            Py <--> Engine[game_engine.py]
            Py <--> Solver[solver.py]
        end
        
        JS -- Run Solver --> Py
    end

    User([User]) -- Manual Interactions --> UI
    Storage -- Cache Configuration --> JS
```

### 1. Pure Client-Side Features
* **Interactive Grid Simulator**: A beautiful web board where you can click/swipe to play, edit tile values manually (0-15), and simulate games client-side.
* **Expectimax Solver**: Runs `solver.py` directly inside the browser using Pyodide. Calculates directional EV metrics (UP, DOWN, LEFT, RIGHT) and displays the recommended move.
* **HTML LocalStorage Persistence**: Caches solver settings (Depth, Max Time, Stone Level 11) and game simulation undo/redo histories.

---

## SECTION 2: Android Capture & ADB Automation (DO NOT IMPLEMENT YET)

> [!IMPORTANT]
> **DO NOT IMPLEMENT YET**
> These features require external system connectivity, image parsing, or local file access. They are currently planned and will be kept as visual placeholders/disabled controls in the UI.

```mermaid
graph TD
    subgraph Browser Sandbox
        UI[UI Placeholder Settings] <--> JS[JS App]
        JS <--> Canvas[Canvas Image Cropper]
        
        subgraph WebAssembly Runtime (Pyodide)
            Py[Python CPython Interpreter] \--> Parser[image_parser.py]
        end
        
        JS -- Run Parser --> Py
    end
    
    subgraph Local Machine
        JS -- Local CORS API Requests --> Agent[Windows Powershell Bridge Server / capture_agent.ps1]
        Agent <--> ADB[ADB Connection]
        ADB <--> Phone[Android Device / Emulator]
    end
```

### 1. Placeholder Features (DO NOT IMPLEMENT YET)
* **Pasting / Drag-and-Drop Screenshots**: Placeholder input for loading screenshot files into the app.
* **Canvas Crop & Calibration**: Visual tool allowing coordinate selection for cropping the 2048 game grid.
* **Dynamic Test Case Generator**: 
  * Will compile current image crop and target grid layout into a JSON object.
  * Will show a popup with **"📋 Copy JSON"** and **"📥 Download JSON"** buttons (since the browser cannot directly write to `/tests/dynamic_samples.json`).
* **Image Recognition Pipeline**: 
  * Running `image_parser.py` within Pyodide to recognize cell numbers/levels from screenshots.

### 2. PowerShell HTTP Bridge Server (Option 1)
To enable automated ADB play without requiring a local Python Flask server, we will utilize a **PowerShell HTTP Bridge** architecture:

1. **PowerShell Bridge Server (`capture_agent.ps1` or similar)**:
   * The user runs the PowerShell script on their local Windows computer.
   * Using Windows' built-in `System.Net.HttpListener`, it acts as a lightweight web server running locally (e.g., at `http://localhost:8080`).
   * It handles two main endpoints:
     * `GET /screenshot`: Captures the screen via ADB (`adb exec-out screencap`) and returns the raw PNG bytes.
     * `POST /swipe`: Takes directional coordinates in the payload and runs `adb shell input swipe`.

2. **Web Browser Client (`app.js`)**:
   * Runs the UI and solver in the browser.
   * Feeds the solver results to the local PowerShell server:
     * Polls `GET http://localhost:8080/screenshot` to get a screenshot, which is parsed by Pyodide in-browser.
     * Sends `POST http://localhost:8080/swipe` with the best move coordinates computed by the local WebAssembly solver.

---

## SECTION 3: Serverless Peer-to-Peer Browser Sync (DO NOT IMPLEMENT YET)

> [!IMPORTANT]
> **DO NOT IMPLEMENT YET**
> This section outlines how to link two browser instances (e.g., phone and PC) to synchronize states and stream displays with zero servers.

```mermaid
graph TD
    subgraph Phone Browser
        PhoneUI[Phone Game View] <--> PhoneJS[Phone JS Controller]
    end

    subgraph PC / Tablet Browser
        PCUI[PC Solver Dashboard] <--> PCJS[PC JS Controller]
        PCJS <--> PyWASM[Pyodide WebAssembly Solver]
    end

    PhoneJS -- P2P WebRTC Connection -- UI Sync / Video Stream --> PCJS
```

### 1. The P2P WebRTC Connection Concept
WebRTC allows direct socket communication (DataChannels) and media streaming (MediaStreams) directly between two browsers. To run entirely backendless (no custom signaling server), it uses a **visual QR-code handshake**:

* **SDP Handshake Process**:
  1. The **PC Browser** creates a WebRTC connection object and generates a local connection profile (SDP Offer). It renders this text block as a **QR Code** on the screen.
  2. The **Phone Browser** scans the PC's QR code using its camera. This loads the PC's connection profile.
  3. The Phone generates its response profile (SDP Answer) and displays it on its screen as a QR code.
  4. The PC scans the Phone's QR code using a webcam, establishing the connection.
* **NAT Traversal (STUN)**:
  * If both devices are on the same local Wi-Fi, they find each other locally.
  * If they are on different networks, the browsers ping a public STUN server (such as Google's free public STUN: `stun:stun.l.google.com:19302`) to discover their public-facing IP addresses and establish the UDP tunnel.

### 2. Dual-Device Sync Capabilities
Once connected P2P, we support two cross-device modes:

* **Mode A: Phone Casting (Screen Share)**:
  * The user plays on the phone. The phone browser shares its screen via native WebRTC screen casting (`navigator.mediaDevices.getDisplayMedia`).
  * The PC browser receives the video track, extracts frames in real-time, runs the Pyodide image parser, runs the solver, and displays EV recommendations on the PC screen.
* **Mode B: Interactive Grid Sync (Low Latency DataChannel)**:
  * The user plays the game in the phone browser.
  * Every swipe or game state change sends the 4x4 matrix (16-byte payload) over the WebRTC DataChannel (sub-millisecond latency).
  * The PC browser automatically syncs its grid representation, runs the WebAssembly Expectimax solver, and displays live metrics.
