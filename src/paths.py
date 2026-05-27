# paths.py
import os
import tempfile

# Root directory of the solver2048d project
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)

# Configuration file path
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")
CAPTURE_CONFIG_PATH = os.path.join(ROOT_DIR, "capture_config.yaml")

# Directory for gameplay logs
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
TMP_DIR = os.path.join(LOGS_DIR, "tmp")

# Location of the latest captured screen image
LATEST_SCREENSHOT_PATH = os.path.join(LOGS_DIR, "latest_screenshot.png")

def ensure_logs_dir():
    """Ensures that the logs and temporary directories exist on disk."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

# Run ensure_logs_dir to guarantee the directory is created immediately
ensure_logs_dir()

# Point Python's tempfile and TMPDIR environment variable to the workspace data partition
# to avoid OSError [Errno 122] Disk quota exceeded on the tmpfs /tmp partition.
tempfile.tempdir = TMP_DIR
os.environ["TMPDIR"] = TMP_DIR
os.environ["TEMP"] = TMP_DIR
os.environ["TMP"] = TMP_DIR
