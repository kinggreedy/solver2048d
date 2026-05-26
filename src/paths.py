# paths.py
import os

# Root directory of the solver2048d project
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)

# Configuration file path
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")
CAPTURE_CONFIG_PATH = os.path.join(ROOT_DIR, "capture_config.yaml")

# Directory for gameplay logs
LOGS_DIR = os.path.join(ROOT_DIR, "logs")

# Location of the latest captured screen image
LATEST_SCREENSHOT_PATH = os.path.join(LOGS_DIR, "latest_screenshot.png")

def ensure_logs_dir():
    """Ensures that the logs directory exists on disk."""
    os.makedirs(LOGS_DIR, exist_ok=True)
