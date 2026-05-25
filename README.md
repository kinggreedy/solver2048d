# Solver 2048d - GUI Solver & Android Capture Helper

`solver2048d` is a helper utility and expectimax-based solver for a custom 2048 variant featuring energy costs, multiplier modes, configurable spawn behavior, and level-11 stone tiles.

The project includes:

* a PyQt6 desktop GUI,
* board evaluation and move recommendation tools,
* gameplay history inspection utilities,
* and an optional Android screenshot capture pipeline using ADB and a lightweight PowerShell sync agent.

---

## Features

- **Iterative expectimax search**
  - Evaluates legal moves against probabilistic spawn outcomes.
  - Uses depth-limited search with time budgeting and partial-depth progress updates.
  - Applies risk-aware scoring for unstable high-tile/corner positions.

- **Multi-mode parallel evaluation**
  - Compares enabled modes such as `x1`, `x4`, `x8`, and `x16`.
  - Runs mode evaluations in parallel when time-limited.
  - Reports expected value per energy for mode selection.

- **Hybrid evaluation model**
  - Combines searched expected value, heuristic board quality, survivability estimates, and restart/continue thresholds.
  - Includes a Monte Carlo rollout evaluator for experimentation and validation, though the normal recommendation path is expectimax-based.

- **Desktop control interface**
  - PyQt6 GUI for board entry, solving, mode comparison, screenshot capture, and crop calibration.

- **Android capture workflow**
  - Windows PowerShell agent captures Android screenshots via ADB and uploads them to the local solver server for parsing.

- **Logging and replay**
  - JSONL logs for evaluations, move results, and spawn observations.
  - Terminal history viewer for inspecting previous games.

---

## Installation & Setup

1. **Clone the repository**

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *(Ensure you have `PyQt6`, `PyYAML`, `Flask`, and `Pillow` installed).*

---

## Operating Instructions

### 1. Launch PyQt6 GUI Helper
Start the solver app:
```bash
python3 main.py
```
- Select your multiplier mode (`x1`, `x4`, etc.) from the dropdown.
- Tweak search depth and time limits, then click **Solve**.
- Manual edits: Left-click tiles to increment levels, right-click to clear.
- Arrow keys: Navigate / apply swipes.

### 2. Run Android Capture Sync
To sync directly from your phone:
1. Make sure your Android device has **USB Debugging** enabled and is connected to your Windows computer.
2. Run the PowerShell agent on your Windows computer:
   ```powershell
   cd client
   .\capture_agent.ps1
   ```
3. In the PyQt6 GUI on Ubuntu, click **📸 Capture Android**. The screen will automatically upload and sync!
4. Adjust crop coordinates in the **Android Capture** column until the overlays match the board cells, then click **Save Crop**.

### 3. Launch TUI History Player
To inspect logs from previous games:
```bash
python3 main.py --history
```
- **W / S or Arrow Keys (Up/Down)**: Select gameplay session.
- **A / D or Arrow Keys (Left/Right)**: Step moves.
- **Space**: Toggle sequential Autoplay.
- **G**: Jump to a specific move index.

---

## Documentation Links

For deeper reading, check out our docs:
- [Developer Architecture Guide](docs/ARCHITECTURE.md): Expectimax, bitboards, and heuristics details.
- [Capture Agent Configuration](docs/AGENTS.md): ADB configuration and PowerShell loops.
- [Capture System Design](docs/CAPTURE_SYSTEM.md): Flask API endpoints and Pillow color classification.
