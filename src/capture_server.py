# capture_server.py
from flask import Flask, request, jsonify, send_file
import os
import threading

app = Flask(__name__)

# State variables
capture_requested = False
latest_screenshot_path = None
latest_parsed_board = None

# Callback trigger to notify GUI thread
on_capture_received_callback = None
on_status_changed_callback = None

@app.route('/capture/request', methods=['POST'])
def capture_request():
    """Sets capture_requested to True to signal the Windows agent to capture."""
    global capture_requested
    capture_requested = True
    return jsonify({"status": "success", "capture_requested": True})

@app.route('/capture/poll', methods=['GET'])
def capture_poll():
    """Polled by the Windows agent. Returns true if capture is requested, then resets flag."""
    global capture_requested
    state = capture_requested
    if state:
        capture_requested = False # Reset flag so agent only screenshots once
    return jsonify({"capture_requested": state})

@app.route('/capture/upload', methods=['POST'])
def capture_upload():
    """Handles screenshot uploads, saves the file, parses the board, and notifies the GUI thread."""
    global latest_screenshot_path, latest_parsed_board
    
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Empty filename"}), 400
        
    from src.paths import LATEST_SCREENSHOT_PATH, ensure_logs_dir
    ensure_logs_dir()
    save_path = LATEST_SCREENSHOT_PATH
    
    try:
        # Save screenshot
        file.save(save_path)
        latest_screenshot_path = save_path
        
        # Notify GUI that we have received the image and are starting parsing
        if on_status_changed_callback:
            on_status_changed_callback("Parsing...")
        
        # Parse board image
        import src.image_parser as image_parser
        grid = image_parser.parse_screenshot(save_path)
        if grid:
            from src import game_engine
            latest_parsed_board = game_engine.list_to_board(grid)
        else:
            grid = None
            latest_parsed_board = None
            
        # Trigger PyQt GUI callback to update display thread-safely
        if on_capture_received_callback:
            on_capture_received_callback(save_path, grid)
            
        return jsonify({
            "status": "success",
            "parsed_board": grid
        })
    except Exception as e:
        print(f"Error handling uploaded capture: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/capture/latest', methods=['GET'])
def capture_latest():
    """Retrieves latest screenshot or parsed board state."""
    global latest_screenshot_path, latest_parsed_board
    
    if not latest_screenshot_path or not os.path.exists(latest_screenshot_path):
        return jsonify({"status": "error", "message": "No capture available"}), 404
        
    if request.args.get('image') == 'true':
        return send_file(latest_screenshot_path, mimetype='image/png')
        
    from src import game_engine
    grid = game_engine.board_to_list(latest_parsed_board) if latest_parsed_board is not None else None
    return jsonify({
        "parsed_board": grid,
        "board_hex": hex(latest_parsed_board) if latest_parsed_board is not None else None,
        "screenshot_url": "/capture/latest?image=true"
    })

def start_server(port=5000, callback=None, status_callback=None):
    """Starts the Flask server on a daemon thread to prevent locking the PyQt app."""
    global on_capture_received_callback, on_status_changed_callback
    on_capture_received_callback = callback
    on_status_changed_callback = status_callback
    
    # Mute Flask's standard output logs to keep the terminal clean
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    def run():
        # debug=False and use_reloader=False are mandatory for running in threads
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
        
    server_thread = threading.Thread(target=run, daemon=True)
    server_thread.start()
    return server_thread
