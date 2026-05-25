# Capture Sync & Image Classification - Solver 2048d

This document describes the client-server screenshots sync and image classification logic inside the `solver2048d` capture pipeline.

---

## 1. Communication API Endpoints

The Flask server (`src/capture_server.py`) runs in a background thread and exposes the following REST endpoints:

- **`POST /capture/request`**:
  Sets `capture_requested = True` to request a screenshot.
- **`GET /capture/poll`**:
  Polled by the Windows PowerShell agent. Returns `{"capture_requested": true}` if a capture was requested, and resets the request flag back to `false` to prevent duplicate screenshots.
- **`POST /capture/upload`**:
  Receives multipart/form-data containing the screenshot file. Saves the file to `logs/latest_screenshot.png`, parses the board grid, and thread-safely emits a Qt signal to update the main GUI thread.
- **`GET /capture/latest`**:
  Returns the parsed board state JSON, or serves the latest PNG screenshot when requested with `?image=true`.

---

## 2. Image Parsing & Classification Pipeline

The parser (`src/image_parser.py`) converts raw PNG screen captures into a 4x4 integer level board using Pillow:

### Step A: Cropping
Using the `crop_x`, `crop_y`, `crop_w`, and `crop_h` coordinates defined in `config.yaml`, the full-sized screenshot is cropped down to the exact 4x4 game grid boundaries.

### Step B: Inner/Center Color Sampling
To divide the cropped board into 16 individual tile cells:
1. Cell width is calculated as `crop_w / 4`, and height as `crop_h / 4`.
2. For each cell `(r, c)`, the parser samples the RGB color of **4 inner/center patches** located at 25% and 75% offsets from the cell borders (e.g. coordinates `(0.25, 0.25)`, `(0.75, 0.25)`, `(0.25, 0.75)`, and `(0.75, 0.75)`).
3. Sampling the corners at a 25% offset completely avoids tile borders, shadows, rounded corner artifacts, and any numbers/emojis drawn in the exact center of the tile.
4. The RGB values of the 4 sampled points are averaged to get the clean background color of the cell.

### Step C: Euclidean Color Matching
The averaged RGB is matched against the configured tile colors of levels 0 to 11 in `config.yaml`. The level with the smallest Euclidean distance is selected:

$$\text{Distance} = \sqrt{(R_{\text{sample}} - R_{\text{config}})^2 + (G_{\text{sample}} - G_{\text{config}})^2 + (B_{\text{sample}} - B_{\text{config}})^2}$$

---

## 3. Interactive Crop Calibration

Tuning the crop coordinates for a specific device is made simple with the **Calibration GUI**:
- The spinboxes in the GUI update the crop parameters in memory.
- When the **Grid Overlay** is active, a custom PyQt `QPainter` draws a red crop box and white dashed lines showing the 16 cells directly over the uploaded screenshot preview.
- Tweak the spinbox values until the white dashed lines align perfectly with the boundaries of the cells. Click **Save Crop** to write these values back to `config.yaml` permanently.
- Click **Reparse** to test the new boundaries immediately.
