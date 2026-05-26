# gui.py
import sys
import os
import traceback
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QProgressBar, QTextEdit, QFrame, QMessageBox,
    QScrollArea, QCheckBox, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QFont, QKeyEvent, QPainter, QPen, QColor, QPixmap

class CaptureSignalEmitter(QObject):
    capture_received = pyqtSignal(str, list) # filepath, parsed_grid
    status_changed = pyqtSignal(str) # new status text

from src import game_engine
from src import solver
from src import stats
from src.paths import CONFIG_PATH, CAPTURE_CONFIG_PATH, LATEST_SCREENSHOT_PATH, LOGS_DIR

class SolverThread(QThread):
    solver_finished = pyqtSignal(int)   # generation
    solver_progress = pyqtSignal(dict, int)   # event (dict), generation
    solver_failed = pyqtSignal(str)
    
    def __init__(self, board, config, selected_mode, override_depth, override_time, use_empirical, enabled_modes, cancel_filepath, generation):
        super().__init__()
        self.board = board
        self.config = config
        self.selected_mode = selected_mode
        self.override_depth = override_depth
        self.override_time = override_time
        self.use_empirical = use_empirical
        self.enabled_modes = enabled_modes
        self.cancel_filepath = cancel_filepath
        self.generation = generation
        self.cancel_token = solver.CancelToken(cancel_filepath)
        
    def cancel(self):
        self.cancel_token.cancel()
        
    def run(self):
        import multiprocessing
        import queue as queue_lib
        try:
            empirical_patterns = None
            if self.use_empirical:
                summary = stats.compute_spawn_statistics(self.config)
                if self.cancel_token.is_cancelled():
                    return
                empirical_patterns = summary.get('empirical_probabilities')
                
            # Create a multiprocessing queue
            queue = multiprocessing.Queue()
            
            # Start worker processes
            processes = {}
            for mode in self.enabled_modes:
                from src.solver import solver_worker_entry
                proc = multiprocessing.Process(
                    target=solver_worker_entry,
                    args=(
                        self.board,
                        mode,
                        self.config,
                        empirical_patterns,
                        self.override_depth,
                        self.override_time,
                        self.cancel_filepath,
                        queue
                    )
                )
                proc.daemon = True
                proc.start()
                processes[mode] = proc
                
            active_modes = set(self.enabled_modes)
            
            while active_modes and not self.cancel_token.is_cancelled():
                try:
                    event = queue.get(timeout=0.05)
                    self.solver_progress.emit(event, self.generation)
                    if event.get("is_final"):
                        mode = event.get("mode")
                        if mode in active_modes:
                            active_modes.remove(mode)
                except queue_lib.Empty:
                    # Check if any process has terminated unexpectedly
                    for mode in list(active_modes):
                        proc = processes[mode]
                        if not proc.is_alive():
                            # Process died or finished without final event
                            fake_event = {
                                "mode": mode,
                                "depth": 1,
                                "best_move": None,
                                "real_ev": 0.0,
                                "ev_per_energy": 0.0,
                                "heuristic_score": 0.0,
                                "nodes": 0,
                                "elapsed_ms": 0.0,
                                "is_final": True
                            }
                            self.solver_progress.emit(fake_event, self.generation)
                            active_modes.remove(mode)
                time.sleep(0.01)
                
            if self.cancel_token.is_cancelled():
                for proc in processes.values():
                    if proc.is_alive():
                        proc.terminate()
                return
                
            for proc in processes.values():
                proc.join(timeout=0.5)
                
            self.solver_finished.emit(self.generation)
        except Exception as e:
            self.solver_failed.emit(traceback.format_exc())
        finally:
            if self.cancel_filepath and os.path.exists(self.cancel_filepath):
                try:
                    os.remove(self.cancel_filepath)
                except Exception:
                    pass


# Map direction constant to string
DIR_STR = {
    game_engine.LEFT: "LEFT (◀)",
    game_engine.RIGHT: "RIGHT (▶)",
    game_engine.UP: "UP (▲)",
    game_engine.DOWN: "DOWN (▼)"
}
DIR_MAP_FROM_STR = {
    "LEFT": game_engine.LEFT,
    "RIGHT": game_engine.RIGHT,
    "UP": game_engine.UP,
    "DOWN": game_engine.DOWN
}
DIR_MAP_TO_STR = {
    game_engine.LEFT: "LEFT",
    game_engine.RIGHT: "RIGHT",
    game_engine.UP: "UP",
    game_engine.DOWN: "DOWN"
}

class TileButton(QPushButton):
    """Custom button that handles left and right clicks independently."""
    clicked_left = pyqtSignal()
    clicked_right = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked_left.emit()
        elif event.button() == Qt.MouseButton.RightButton:
            self.clicked_right.emit()
        else:
            super().mousePressEvent(event)

class Solver2048dGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = game_engine.config
        # Ensure capture config is loaded cleanly from capture_config.yaml
        from src.image_parser import load_capture_config
        self.config['capture'] = load_capture_config()
        
        # State variables
        self.current_board = 0
        self.board_before_move = 0
        self.board_after_move_no_spawn = 0
        self.last_move_taken = None
        self.last_rec_move = None
        self.capture_warning_cells = set()
        
        self.total_score = 0
        self.total_energy = 0
        self.total_moves = 0
        
        # Game loop states: "NORMAL", "WAITING_FOR_SPAWN"
        self.gui_state = "NORMAL"
        
        # Undo history: holds tuples of (board, score, energy, moves, state)
        self.history = []
        self.empty_spawn_confirmed = False
        self.active_threads = []
        self._solver_generation = 0  # Incremented each time run_solver is called; used to discard stale results
        
        self.init_ui()
        self.update_board_display()
        self.refresh_stats()
        self.run_solver()
        
        # Capture Server integration
        self.latest_screenshot_path = None
        self.capture_emitter = CaptureSignalEmitter()
        self.capture_emitter.capture_received.connect(self.handle_incoming_capture)
        self.capture_emitter.status_changed.connect(self.lbl_capture_status.setText)
        
        capture_cfg = self.config.get('capture', {})
        if capture_cfg.get('enabled', True):
            import src.capture_server as capture_server
            port = capture_cfg.get('port', 5000)
            
            def server_cb(filepath, grid):
                self.capture_emitter.capture_received.emit(filepath, grid or [])
                
            def status_cb(status_text):
                # Map plain text status to emoji statuses in the GUI
                if status_text == "Parsing...":
                    status_text = "⚙️ Parsing..."
                self.capture_emitter.status_changed.emit(status_text)
                
            capture_server.start_server(port=port, callback=server_cb, status_callback=status_cb)
            
    def init_ui(self):
        capture_cfg = self.config.get('capture', {})
        self.setWindowTitle("Solver 2048d — KDE Remote Desktop Helper")
        self.resize(1380, 680)
        
        # Main Central Widget and Layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(15)
        
        # Styling Theme: Sleek Dark Mode
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121214;
            }
            QWidget {
                color: #e0e0e0;
                font-family: "Segoe UI", "Inter", "Roboto", "Helvetica Neue", sans-serif;
            }
            QLabel {
                font-size: 14px;
            }
            QFrame {
                background-color: #1e1e24;
                border: 1px solid #2d2d35;
                border-radius: 8px;
            }
            QPushButton {
                background-color: #2a2a35;
                color: #ffffff;
                border: 1px solid #3d3d4b;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #353545;
                border-color: #5d5d75;
            }
            QPushButton:pressed {
                background-color: #1a1a24;
            }
            QPushButton:disabled {
                background-color: #15151b;
                color: #666677;
                border-color: #202025;
            }
            QComboBox {
                background-color: #2a2a35;
                border: 1px solid #3d3d4b;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QProgressBar {
                border: 1px solid #3d3d4b;
                border-radius: 4px;
                text-align: center;
                background-color: #15151b;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
            }
            QTextEdit {
                background-color: #15151b;
                border: 1px solid #2d2d35;
                border-radius: 4px;
                color: #a0a0b0;
                font-family: monospace;
            }
            QCheckBox {
                color: #b0bec5;
                font-size: 13px;
                font-weight: bold;
            }
            QSpinBox {
                background-color: #2a2a35;
                color: #ffffff;
                border: 1px solid #3d3d4b;
                border-radius: 4px;
                padding: 4px;
                padding-right: 20px;
            }
            QSpinBox:hover {
                border-color: #5d5d75;
            }
            QSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 18px;
                border-left: 1px solid #3d3d4b;
                border-bottom: 1px solid #3d3d4b;
                border-top-right-radius: 4px;
                background-color: #2a2a35;
            }
            QSpinBox::up-button:hover {
                background-color: #353545;
            }
            QSpinBox::up-arrow {
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 5px solid #e0e0e0;
                width: 0;
                height: 0;
            }
            QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {
                border-bottom-color: #666677;
            }
            QSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 18px;
                border-left: 1px solid #3d3d4b;
                border-bottom-right-radius: 4px;
                background-color: #2a2a35;
            }
            QSpinBox::down-button:hover {
                background-color: #353545;
            }
            QSpinBox::down-arrow {
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #e0e0e0;
                width: 0;
                height: 0;
            }
            QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {
                border-top-color: #666677;
            }
        """)
        
        # ------------------ LEFT COLUMN (Board Panel) ------------------
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(15, 10, 15, 15)
        left_layout.setSpacing(5)
        
        # Title and Game Stats
        header_label = QLabel("BOARD VIEW")
        header_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #4facfe; margin-bottom: 2px;")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(header_label)
        
        # Stats Display Grid
        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #16161c; border: none;")
        stats_grid = QGridLayout(stats_frame)
        stats_grid.setContentsMargins(5, 5, 5, 5)
        
        self.score_val_label = QLabel("Score: 0")
        self.score_val_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #4caf50;")
        self.energy_val_label = QLabel("Energy: 0")
        self.energy_val_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #ffeb3b;")
        self.moves_val_label = QLabel("Moves: 0")
        self.moves_val_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #e0e0e0;")
        self.efficiency_val_label = QLabel("Pts/Energy: 0.0")
        self.efficiency_val_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #00e676;")
        
        stats_grid.addWidget(self.score_val_label, 0, 0)
        stats_grid.addWidget(self.energy_val_label, 0, 1)
        stats_grid.addWidget(self.moves_val_label, 1, 0)
        stats_grid.addWidget(self.efficiency_val_label, 1, 1)
        
        left_layout.addWidget(stats_frame)
        
        # Spawn Warning / Interactive Status Banner
        self.status_banner = QLabel("STATUS: Edit board manually or apply moves")
        self.status_banner.setStyleSheet("""
            background-color: #2b2b36;
            color: #b0bec5;
            padding: 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)
        self.status_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.status_banner)
        
        # 4x4 Grid of Tile Buttons
        grid_frame = QFrame()
        grid_frame.setStyleSheet("background-color: #25252d; border-radius: 10px; border: 1px solid #33333f;")
        self.grid_layout = QGridLayout(grid_frame)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        
        self.buttons = []
        for r in range(4):
            row_buttons = []
            for c in range(4):
                btn = TileButton()
                btn.clicked_left.connect(lambda row=r, col=c: self.handle_cell_click(row, col, "left"))
                btn.clicked_right.connect(lambda row=r, col=c: self.handle_cell_click(row, col, "right"))
                self.grid_layout.addWidget(btn, r, c)
                row_buttons.append(btn)
            self.buttons.append(row_buttons)
            
        left_layout.addWidget(grid_frame)
        
        # Manual Action Buttons
        action_frame = QFrame()
        action_frame.setStyleSheet("background-color: #1e1e24; border: 1px solid #2d2d35; border-radius: 8px; margin-top: 5px; margin-bottom: 5px;")
        action_layout = QHBoxLayout(action_frame)
        action_layout.setContentsMargins(10, 10, 10, 10)
        
        action_label = QLabel("Apply Action:")
        action_label.setStyleSheet("font-weight: bold; color: #b0bec5;")
        action_layout.addWidget(action_label)
        
        self.btn_move_left = QPushButton("◀ LEFT")
        self.btn_move_left.clicked.connect(lambda: self.execute_move(game_engine.LEFT))
        
        self.btn_move_up = QPushButton("▲ UP")
        self.btn_move_up.clicked.connect(lambda: self.execute_move(game_engine.UP))
        
        self.btn_move_down = QPushButton("▼ DOWN")
        self.btn_move_down.clicked.connect(lambda: self.execute_move(game_engine.DOWN))
        
        self.btn_move_right = QPushButton("RIGHT ▶")
        self.btn_move_right.clicked.connect(lambda: self.execute_move(game_engine.RIGHT))
        
        self.btn_apply_rec = QPushButton("⚡ Apply Recommended")
        self.btn_apply_rec.setStyleSheet("background-color: #00796b; border-color: #00897b; color: white;")
        self.btn_apply_rec.clicked.connect(self.execute_recommended_move)
        
        action_layout.addWidget(self.btn_move_left)
        action_layout.addWidget(self.btn_move_up)
        action_layout.addWidget(self.btn_move_down)
        action_layout.addWidget(self.btn_move_right)
        action_layout.addWidget(self.btn_apply_rec)
        
        left_layout.addWidget(action_frame)
        
        # Board View Control Buttons
        board_controls = QHBoxLayout()
        self.btn_reset = QPushButton("Reset Board")
        self.btn_reset.setStyleSheet("background-color: #552222; border-color: #773333;")
        self.btn_reset.clicked.connect(self.reset_board)
        
        self.btn_new_game = QPushButton("New Game")
        self.btn_new_game.setStyleSheet("background-color: #1b5e20; border-color: #2e7d32;")
        self.btn_new_game.clicked.connect(self.new_game)
        
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.clicked.connect(self.undo)
        
        self.btn_confirm_spawn = QPushButton("Confirm Spawn")
        self.btn_confirm_spawn.setEnabled(False)
        self.btn_confirm_spawn.setStyleSheet("background-color: #0d47a1; border-color: #1565c0;")
        self.btn_confirm_spawn.clicked.connect(self.confirm_spawn)
        
        board_controls.addWidget(self.btn_reset)
        board_controls.addWidget(self.btn_new_game)
        board_controls.addWidget(self.btn_undo)
        board_controls.addWidget(self.btn_confirm_spawn)
        
        left_layout.addLayout(board_controls)
        
        # Keyboard Move Guide
        guide_label = QLabel("💡 Tip: Use Arrow Keys on this window to swipe in-game!")
        guide_label.setStyleSheet("color: #78909c; font-size: 12px; margin-top: 5px;")
        guide_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(guide_label)
        
        main_layout.addWidget(left_panel, 11)
        
        # ------------------ RIGHT COLUMN (Solver & Stats) ------------------
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(15, 10, 15, 15)
        right_layout.setSpacing(5)
        
        # Solver Header
        solver_header = QLabel("SOLVER RECOMMENDATION")
        solver_header.setStyleSheet("font-size: 15px; font-weight: bold; color: #00e676; margin-bottom: 2px;")
        solver_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(solver_header)
        
        # Config options and Solver Budget Settings
        settings_frame = QFrame()
        settings_frame.setStyleSheet("background-color: #1e1e24; border: 1px solid #2d2d35; border-radius: 8px; padding: 10px; margin-bottom: 5px;")
        settings_layout = QGridLayout(settings_frame)
        settings_layout.setSpacing(10)
        
        # Row 0: Mode Selector and Checkboxes
        settings_layout.addWidget(QLabel("Multiplier Mode:"), 0, 0)
        self.mode_selector = QComboBox()
        for mode in sorted(self.config['modes'].keys(), key=lambda x: self.config['modes'][x]['energy_cost']):
            self.mode_selector.addItem(f"{mode.upper()} (Energy: {self.config['modes'][mode]['energy_cost']})", mode)
        self.mode_selector.currentIndexChanged.connect(self.run_solver)
        settings_layout.addWidget(self.mode_selector, 0, 1)
        
        # Combined X8/X16 block
        x_modes_layout = QHBoxLayout()
        x_modes_layout.setContentsMargins(0, 0, 0, 0)
        x_modes_layout.setSpacing(15)
        
        self.chk_x8 = QCheckBox("X8")
        self.chk_x8.setChecked(False)
        self.chk_x8.stateChanged.connect(self.run_solver)
        x_modes_layout.addWidget(self.chk_x8)
        
        self.chk_x16 = QCheckBox("X16")
        self.chk_x16.setChecked(False)
        self.chk_x16.stateChanged.connect(self.run_solver)
        x_modes_layout.addWidget(self.chk_x16)
        
        settings_layout.addLayout(x_modes_layout, 0, 2)
        
        self.chk_empirical_spawn = QCheckBox("Use Empirical Spawns")
        self.chk_empirical_spawn.setChecked(True)
        self.chk_empirical_spawn.stateChanged.connect(self.run_solver)
        settings_layout.addWidget(self.chk_empirical_spawn, 0, 3)
        
        # Row 1: Search Depth and Time Limit
        settings_layout.addWidget(QLabel("Search Depth:"), 1, 0)
        self.depth_selector = QComboBox()
        self.depth_selector.addItem("Dynamic (Balanced)", "dynamic")
        self.depth_selector.addItem("Depth 2 (Fastest)", 2)
        self.depth_selector.addItem("Depth 3 (Fast)", 3)
        self.depth_selector.addItem("Depth 4 (Normal)", 4)
        self.depth_selector.addItem("Depth 5 (Deep)", 5)
        self.depth_selector.addItem("Depth 6 (Thorough)", 6)
        self.depth_selector.addItem("Depth 7 (Ultimate)", 7)
        self.depth_selector.currentIndexChanged.connect(self.run_solver)
        settings_layout.addWidget(self.depth_selector, 1, 1)
        
        settings_layout.addWidget(QLabel("Max Time:"), 1, 2)
        self.time_selector = QComboBox()
        self.time_selector.addItem("500 ms", 500)
        self.time_selector.addItem("1000 ms", 1000)
        self.time_selector.addItem("2000 ms", 2000)
        self.time_selector.addItem("5000 ms", 5000)
        self.time_selector.addItem("10000 ms", 10000)
        self.time_selector.addItem("Unlimited", 0)
        self.time_selector.setCurrentIndex(1) # Default to 1000 ms
        self.time_selector.currentIndexChanged.connect(self.run_solver)
        settings_layout.addWidget(self.time_selector, 1, 3)
        
        # Solve Button
        self.btn_solve = QPushButton("Solve")
        self.btn_solve.setStyleSheet("background-color: #006064; border-color: #00838f;")
        self.btn_solve.clicked.connect(self.run_solver)
        
        # Create a container vertical layout to hold the settings frame and solve button
        settings_container = QVBoxLayout()
        settings_container.addWidget(settings_frame)
        settings_container.addWidget(self.btn_solve)
        right_layout.addLayout(settings_container)
        
        # Recommendation display
        self.rec_card = QFrame()
        self.rec_card.setStyleSheet("background-color: #16161c; padding: 10px;")
        rec_card_layout = QVBoxLayout(self.rec_card)
        
        # Direction
        self.rec_dir_label = QLabel("NO RECOMMENDATION")
        self.rec_dir_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        self.rec_dir_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rec_card_layout.addWidget(self.rec_dir_label)
        
        # Decision Badge
        self.decision_badge = QLabel("WAITING")
        self.decision_badge.setStyleSheet("""
            background-color: #424242;
            color: #ffffff;
            font-size: 14px;
            font-weight: bold;
            padding: 5px 15px;
            border-radius: 12px;
        """)
        self.decision_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rec_card_layout.addWidget(self.decision_badge)
        
        # Detail numbers
        details_layout = QGridLayout()
        details_layout.addWidget(QLabel("Expected Score (EV):"), 0, 0)
        self.val_ev = QLabel("N/A")
        self.val_ev.setStyleSheet("font-weight: bold;")
        details_layout.addWidget(self.val_ev, 0, 1)
        
        details_layout.addWidget(QLabel("EV Per Energy:"), 1, 0)
        self.val_ev_energy = QLabel("N/A")
        self.val_ev_energy.setStyleSheet("font-weight: bold; color: #00e676;")
        details_layout.addWidget(self.val_ev_energy, 1, 1)
        
        details_layout.addWidget(QLabel("Survival Score:"), 2, 0)
        self.val_survival = QProgressBar()
        self.val_survival.setValue(0)
        details_layout.addWidget(self.val_survival, 2, 1)
        
        rec_card_layout.addLayout(details_layout)
        right_layout.addWidget(self.rec_card)
        
        # Reasons textbox
        right_layout.addWidget(QLabel("Why this move?"))
        self.reasons_box = QTextEdit()
        self.reasons_box.setReadOnly(True)
        self.reasons_box.setStyleSheet("background-color: #121216; color: #90a4ae; font-size: 13px;")
        right_layout.addWidget(self.reasons_box)
        
        # Empirical spawn statistics card
        right_layout.addWidget(QLabel("Empirical Spawn Statistics"))
        self.stats_card = QFrame()
        self.stats_card.setStyleSheet("background-color: #16161c; padding: 10px;")
        stats_card_layout = QVBoxLayout(self.stats_card)
        
        self.stats_text = QLabel("Loading stats...")
        self.stats_text.setWordWrap(True)
        self.stats_text.setStyleSheet("font-size: 12px; color: #b0bec5;")
        stats_card_layout.addWidget(self.stats_text)
        
        btn_refresh_stats = QPushButton("Refresh Stats")
        btn_refresh_stats.clicked.connect(self.refresh_stats)
        stats_card_layout.addWidget(btn_refresh_stats)
        
        right_layout.addWidget(self.stats_card)
        
        main_layout.addWidget(right_panel, 9)
        
        # ------------------ RIGHTMOST COLUMN (Android Capture & Calibration) ------------------
        capture_panel = QFrame()
        capture_layout = QVBoxLayout(capture_panel)
        capture_layout.setContentsMargins(15, 10, 15, 15)
        capture_layout.setSpacing(5)
        
        capture_header = QLabel("ANDROID CAPTURE")
        capture_header.setStyleSheet("font-size: 15px; font-weight: bold; color: #4facfe; margin-bottom: 2px;")
        capture_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        capture_layout.addWidget(capture_header)
        
        # Grid settings region (Single row super-compact horizontal layout)
        capture_settings_frame = QFrame()
        capture_settings_frame.setStyleSheet("QFrame { background-color: #1e1e24; border: 1px solid #2d2d35; border-radius: 8px; padding: 6px; }")
        capture_settings_layout = QHBoxLayout(capture_settings_frame)
        capture_settings_layout.setContentsMargins(6, 4, 6, 4)
        capture_settings_layout.setSpacing(8)

        # 1. Action Button
        self.btn_capture_now = QPushButton("📸 Capture")
        self.btn_capture_now.setStyleSheet("background-color: #0d47a1; border-color: #1565c0; font-weight: bold; padding: 6px 10px;")
        self.btn_capture_now.clicked.connect(self.request_android_capture)
        self.btn_capture_now.setMaximumWidth(100)
        capture_settings_layout.addWidget(self.btn_capture_now, 1)
        
        # 2. Capture Mode
        self.cmb_capture_mode = QComboBox()
        self.cmb_capture_mode.addItems(["🔢 Lvl", "✖️ Mult"])
        self.cmb_capture_mode.setStyleSheet("background-color: #2a2a35; padding: 4px; border-radius: 4px; font-size: 12px; font-weight: bold; color: #ffffff;")
        self.cmb_capture_mode.setMaximumWidth(100)
        cap_mode = self.config.get('capture', {}).get('mode', 'level')
        self.cmb_capture_mode.setCurrentIndex(1 if cap_mode == 'x' else 0)
        self.cmb_capture_mode.currentIndexChanged.connect(self.handle_capture_mode_changed)
        capture_settings_layout.addWidget(self.cmb_capture_mode, 1)

        # 3. Status Label
        self.lbl_capture_status = QLabel("💤 Idle")
        self.lbl_capture_status.setStyleSheet("color: #b0bec5; font-weight: bold; font-size: 12px; background-color: #15151b; border-radius: 4px; padding: 6px;")
        self.lbl_capture_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        capture_settings_layout.addWidget(self.lbl_capture_status, 3)

        capture_layout.addWidget(capture_settings_frame)
        
        # Live Preview Label
        self.lbl_screenshot_preview = QLabel("No screenshot uploaded yet.\n\nStart PowerShell agent on Windows,\nthen click Capture Android.")
        self.lbl_screenshot_preview.setStyleSheet("border: 1px dashed #424242; border-radius: 4px; background-color: #15151b; color: #78909c;")
        self.lbl_screenshot_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_screenshot_preview.setMinimumHeight(550)
        capture_layout.addWidget(self.lbl_screenshot_preview)
        
        # Calibration Controls (SpinBoxes) - Single line QHBoxLayout
        calibration_frame = QFrame()
        calibration_frame.setStyleSheet("QFrame { background-color: #1e1e24; border: 1px solid #2d2d35; padding: 4px; }")
        cal_layout = QHBoxLayout(calibration_frame)
        cal_layout.setContentsMargins(6, 4, 6, 4)
        cal_layout.setSpacing(6)
        
        cal_layout.addWidget(QLabel("X:"))
        self.spn_crop_x = QSpinBox()
        self.spn_crop_x.setRange(0, 9999)
        self.spn_crop_x.setValue(self.config.get('capture', {}).get('crop_x', 40))
        self.spn_crop_x.setMaximumWidth(70)
        self.spn_crop_x.setFixedHeight(24)
        self.spn_crop_x.valueChanged.connect(self.handle_calibration_changed)
        cal_layout.addWidget(self.spn_crop_x)
        
        cal_layout.addWidget(QLabel("Y:"))
        self.spn_crop_y = QSpinBox()
        self.spn_crop_y.setRange(0, 9999)
        self.spn_crop_y.setValue(self.config.get('capture', {}).get('crop_y', 900))
        self.spn_crop_y.setMaximumWidth(70)
        self.spn_crop_y.setFixedHeight(24)
        self.spn_crop_y.valueChanged.connect(self.handle_calibration_changed)
        cal_layout.addWidget(self.spn_crop_y)
        
        cal_layout.addWidget(QLabel("W:"))
        self.spn_crop_w = QSpinBox()
        self.spn_crop_w.setRange(10, 9999)
        self.spn_crop_w.setValue(self.config.get('capture', {}).get('crop_w', 950))
        self.spn_crop_w.setMaximumWidth(70)
        self.spn_crop_w.setFixedHeight(24)
        self.spn_crop_w.valueChanged.connect(self.handle_calibration_changed)
        cal_layout.addWidget(self.spn_crop_w)
        
        cal_layout.addWidget(QLabel("H:"))
        self.spn_crop_h = QSpinBox()
        self.spn_crop_h.setRange(10, 9999)
        self.spn_crop_h.setValue(self.config.get('capture', {}).get('crop_h', 880))
        self.spn_crop_h.setMaximumWidth(70)
        self.spn_crop_h.setFixedHeight(24)
        self.spn_crop_h.valueChanged.connect(self.handle_calibration_changed)
        cal_layout.addWidget(self.spn_crop_h)
        
        capture_layout.addWidget(calibration_frame)

        # Action controls for calibration — wrapped in a dark frame with two rows.
        cal_actions_frame = QFrame()
        cal_actions_frame.setStyleSheet(
            "background-color: #1e1e24; border: 1px solid #2d2d35; border-radius: 8px; padding: 6px; margin-top: 2px;"
        )
        cal_actions_layout = QVBoxLayout(cal_actions_frame)
        cal_actions_layout.setContentsMargins(4, 4, 4, 4)
        cal_actions_layout.setSpacing(6)

        # Row 1: Checkboxes and Save Crop
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(8)

        self.chk_show_grid = QCheckBox("Grid Overlay")
        self.chk_show_grid.setChecked(True)
        self.chk_show_grid.stateChanged.connect(self.update_screenshot_display)
        row1_layout.addWidget(self.chk_show_grid)

        self.chk_template_matching = QCheckBox("Template Matching")
        self.chk_template_matching.setChecked(capture_cfg.get('template_matching', False))
        self.chk_template_matching.stateChanged.connect(self.handle_template_matching_changed)
        row1_layout.addWidget(self.chk_template_matching)

        self.chk_auto_apply = QCheckBox("⚡ Auto Apply")
        self.chk_auto_apply.setChecked(capture_cfg.get('auto_apply', False))
        self.chk_auto_apply.stateChanged.connect(self.handle_auto_apply_changed)
        row1_layout.addWidget(self.chk_auto_apply)

        row1_layout.addStretch()

        self.btn_save_cal = QPushButton("💾 Save Crop")
        self.btn_save_cal.setStyleSheet("background-color: #00796b; color: white; padding: 4px 8px;")
        self.btn_save_cal.clicked.connect(self.save_crop_settings)
        row1_layout.addWidget(self.btn_save_cal)

        cal_actions_layout.addLayout(row1_layout)

        # Row 2: Action Buttons (Reparse, Crop Debug, Calibrate, Add Test Case)
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(6)

        self.btn_reparse = QPushButton("🔄 Reparse")
        self.btn_reparse.setStyleSheet("padding: 4px 8px;")
        self.btn_reparse.clicked.connect(self.reparse_current_screenshot)
        row2_layout.addWidget(self.btn_reparse)

        self.btn_debug_crop = QPushButton("📸 Crop Debug")
        self.btn_debug_crop.setStyleSheet("padding: 4px 8px;")
        self.btn_debug_crop.clicked.connect(self.recreate_crop_debug_image)
        row2_layout.addWidget(self.btn_debug_crop)

        self.btn_calibrate_colors = QPushButton("🎨 Calibrate Colors")
        self.btn_calibrate_colors.setStyleSheet("padding: 4px 8px;")
        self.btn_calibrate_colors.setToolTip(
            "Sample dish colors from the current screenshot using the confirmed board as ground truth.\n"
            "Reparse first, correct any wrong tiles manually, then click this to update colors_x in capture_config.yaml."
        )
        self.btn_calibrate_colors.clicked.connect(self.calibrate_colors_from_board)
        row2_layout.addWidget(self.btn_calibrate_colors)

        self.btn_add_test = QPushButton("➕ Add Test Case")
        self.btn_add_test.setStyleSheet("background-color: #3f51b5; color: white; padding: 4px 8px;")
        self.btn_add_test.setToolTip(
            "Save the current cropped screenshot as a new test case sample,\n"
            "using the current manually-confirmed board state as the ground truth."
        )
        self.btn_add_test.clicked.connect(self.add_current_as_test_case)
        row2_layout.addWidget(self.btn_add_test)

        cal_actions_layout.addLayout(row2_layout)

        capture_layout.addWidget(cal_actions_frame)
        
        main_layout.addWidget(capture_panel, 9)
        
        # Window attributes
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()

    def request_android_capture(self):
        """Signals the background Flask server that a capture is requested."""
        import src.capture_server as capture_server
        capture_server.set_capture_requested(True)
        self.lbl_capture_status.setText("⏳ Waiting for Android...")
        self.statusBar().showMessage("Android capture request sent to server.", 2000)

    def handle_incoming_capture(self, filepath, grid):
        """Thread-safe slot triggered when a new screenshot is uploaded and parsed."""
        self.latest_screenshot_path = filepath
        self.update_screenshot_display()
        
        if grid:
            board_int = game_engine.list_to_board(grid)
            self.save_history()
            self.capture_warning_cells = self.find_capture_mismatch_cells(board_int)
            self.current_board = board_int
            
            if self.capture_warning_cells:
                warning_count = len(self.capture_warning_cells)
                self.lbl_capture_status.setText(f"⚠️ Parsed ({warning_count})")
                self.statusBar().showMessage(
                    f"Capture parsed with {warning_count} board mismatch warning(s). Click marked cells to clear.",
                    5000
                )
            else:
                self.lbl_capture_status.setText("✅ Parsed")
                self.statusBar().showMessage("Board updated from Android capture!", 4000)
            
            # If waiting for spawn, auto-confirm and return to normal
            if self.gui_state == "WAITING_FOR_SPAWN":
                self.confirm_spawn()
            else:
                self.update_board_display()
                self.run_solver()
        else:
            self.lbl_capture_status.setText("❌ Parse Failed")
            self.statusBar().showMessage("Capture received, but board parsing failed! Check crop calibration.", 4000)

    def handle_calibration_changed(self):
        """Fires when crop parameters are edited in the calibration panel."""
        if 'capture' not in self.config:
            self.config['capture'] = {}
        self.config['capture']['crop_x'] = self.spn_crop_x.value()
        self.config['capture']['crop_y'] = self.spn_crop_y.value()
        self.config['capture']['crop_w'] = self.spn_crop_w.value()
        self.config['capture']['crop_h'] = self.spn_crop_h.value()
        
        self.update_screenshot_display()

    def handle_capture_mode_changed(self):
        """Fires when the capture parse mode dropdown is modified."""
        if 'capture' not in self.config:
            self.config['capture'] = {}
        
        index = self.cmb_capture_mode.currentIndex()
        if index == 1:
            self.config['capture']['mode'] = 'x'
        else:
            self.config['capture']['mode'] = 'level'
            
        # Re-parse if there is an active screenshot
        if getattr(self, 'latest_screenshot_path', None) and os.path.exists(self.latest_screenshot_path):
            self.reparse_current_screenshot()

    def handle_template_matching_changed(self):
        """Fires when the Template Matching checkbox is toggled."""
        if 'capture' not in self.config:
            self.config['capture'] = {}
        self.config['capture']['template_matching'] = self.chk_template_matching.isChecked()

    def handle_auto_apply_changed(self):
        """Fires when the Auto Apply checkbox is toggled."""
        if 'capture' not in self.config:
            self.config['capture'] = {}
        self.config['capture']['auto_apply'] = self.chk_auto_apply.isChecked()

    def update_screenshot_display(self):
        """Draws the crop box and 4x4 grid overlay on the latest screenshot and scales it to fit."""
        if not getattr(self, 'latest_screenshot_path', None) or not os.path.exists(self.latest_screenshot_path):
            return
            
        try:
            x = self.spn_crop_x.value()
            y = self.spn_crop_y.value()
            w = self.spn_crop_w.value()
            h = self.spn_crop_h.value()
            
            pixmap_copy = QPixmap(self.latest_screenshot_path)
            if pixmap_copy.isNull():
                return
                
            painter = QPainter(pixmap_copy)
            
            # Draw crop box (red, thick)
            pen = QPen(QColor(255, 23, 68), 6)
            painter.setPen(pen)
            painter.drawRect(x, y, w, h)
            
            # Draw 4x4 inner grid lines
            if self.chk_show_grid.isChecked():
                pen_grid = QPen(QColor(255, 255, 255, 200), 2, Qt.PenStyle.DashLine)
                painter.setPen(pen_grid)
                
                # Verticals
                for i in range(1, 4):
                    vx = int(x + i * (w / 4))
                    painter.drawLine(vx, y, vx, y + h)
                    
                # Horizontals
                for i in range(1, 4):
                    vy = int(y + i * (h / 4))
                    painter.drawLine(x, vy, x + w, vy)
                    
            painter.end()
            
            # Scale to fit QLabel
            lbl_w = max(100, self.lbl_screenshot_preview.width())
            lbl_h = max(100, self.lbl_screenshot_preview.height())
            scaled = pixmap_copy.scaled(
                lbl_w,
                lbl_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_screenshot_preview.setPixmap(scaled)
            
            # Automatically save the cropped board region with grid overlay to logs/debug_cropped.png
            try:
                from PIL import Image, ImageDraw
                img = Image.open(self.latest_screenshot_path)
                img_w, img_h = img.size
                
                # Clamp coordinates to avoid PIL errors
                c_x = max(0, min(x, img_w - 1))
                c_y = max(0, min(y, img_h - 1))
                c_w = min(w, img_w - c_x)
                c_h = min(h, img_h - c_y)
                
                if c_w > 0 and c_h > 0:
                    board_img = img.crop((c_x, c_y, c_x + c_w, c_y + c_h))
                    debug_img = board_img.copy()
                    draw = ImageDraw.Draw(debug_img)
                    
                    # Draw grid lines on the crop
                    cell_w = c_w / 4
                    cell_h = c_h / 4
                    for i in range(1, 4):
                        vx = int(i * cell_w)
                        draw.line([(vx, 0), (vx, c_h)], fill=(255, 0, 0), width=3)
                        vy = int(i * cell_h)
                        draw.line([(0, vy), (c_w, vy)], fill=(255, 0, 0), width=3)
                    draw.rectangle([(0, 0), (c_w - 1, c_h - 1)], outline=(255, 0, 0), width=4)
                    
                    debug_path = os.path.join(LOGS_DIR, "debug_cropped.png")
                    debug_img.save(debug_path)
            except Exception as e:
                print(f"Error saving debug_cropped.png from GUI: {e}")
        except Exception as e:
            print(f"Error drawing screenshot overlay: {e}")

    def reparse_current_screenshot(self):
        """Forces board re-parsing of the current screenshot using active crop parameters."""
        if not getattr(self, 'latest_screenshot_path', None) or not os.path.exists(self.latest_screenshot_path):
            self.statusBar().showMessage("No screenshot available to reparse!", 2000)
            return
            
        self.lbl_capture_status.setText("⚙️ Parsing...")
        
        import src.image_parser as image_parser
        grid = image_parser.parse_screenshot(self.latest_screenshot_path)
        if grid:
            board_int = game_engine.list_to_board(grid)
            self.save_history()
            self.capture_warning_cells = self.find_capture_mismatch_cells(board_int)
            self.current_board = board_int
            
            if self.gui_state == "WAITING_FOR_SPAWN":
                self.gui_state = "NORMAL"
                self.reset_confirm_spawn_button()
                self.update_gui_state_display()
                
            self.update_board_display()
            if self.capture_warning_cells:
                warning_count = len(self.capture_warning_cells)
                self.lbl_capture_status.setText(f"⚠️ Parsed ({warning_count})")
                self.statusBar().showMessage(
                    f"Board reparsed with {warning_count} mismatch warning(s). Click marked cells to clear.",
                    5000
                )
            else:
                self.lbl_capture_status.setText("✅ Parsed")
                self.statusBar().showMessage("Board reparsed and updated successfully!", 3000)
            self.run_solver()
        else:
            self.lbl_capture_status.setText("❌ Parse Failed")
            self.statusBar().showMessage("Reparsing failed! Adjust calibration and retry.", 3000)

    def save_crop_settings(self):
        """Saves current crop parameters to capture_config.yaml."""
        try:
            import yaml
            path = CAPTURE_CONFIG_PATH
            with open(path, "r") as f:
                yaml_data = yaml.safe_load(f) or {}
                
            if 'capture' not in yaml_data:
                yaml_data['capture'] = {}
                
            yaml_data['capture']['crop_x'] = self.spn_crop_x.value()
            yaml_data['capture']['crop_y'] = self.spn_crop_y.value()
            yaml_data['capture']['crop_w'] = self.spn_crop_w.value()
            yaml_data['capture']['crop_h'] = self.spn_crop_h.value()
            
            # Save the active parsing mode
            index = self.cmb_capture_mode.currentIndex()
            yaml_data['capture']['mode'] = 'x' if index == 1 else 'level'
            
            # Save the template matching setting
            yaml_data['capture']['template_matching'] = self.chk_template_matching.isChecked()
            
            # Save the auto apply setting
            yaml_data['capture']['auto_apply'] = self.chk_auto_apply.isChecked()
            
            with open(path, "w") as f:
                yaml.safe_dump(yaml_data, f, default_flow_style=False)
                
            self.statusBar().showMessage("Crop settings saved to capture_config.yaml successfully!", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"Failed to save crop settings: {e}", 3000)
            
    def recreate_crop_debug_image(self):
        """Forces manual regeneration of logs/debug_cropped.png and shows feedback."""
        if not getattr(self, 'latest_screenshot_path', None) or not os.path.exists(self.latest_screenshot_path):
            self.statusBar().showMessage("No screenshot available to crop!", 2000)
            return

        self.update_screenshot_display()
        self.statusBar().showMessage("Recreated logs/debug_cropped.png successfully!", 3000)

    def calibrate_colors_from_board(self):
        """Auto-calibrates colors_x in config.yaml by sampling dish colors at Y=70% of each
        non-empty cell, using the currently confirmed board (self.current_board) as ground truth.

        Workflow:
          1. Reparse the screenshot (Reparse button) so the board looks roughly right.
          2. Correct any wrong tile values by clicking the tile buttons on the board display.
          3. Click 'Calibrate Colors' — this reads the confirmed board and samples the dish colour
             at the bottom of each cell (Y=70%, X=35/50/65%) to derive the per-level reference colours.
          4. Click 'Save Crop' to persist the updated config.yaml.
        """
        if not getattr(self, 'latest_screenshot_path', None) or not os.path.exists(self.latest_screenshot_path):
            self.statusBar().showMessage("No screenshot available — capture a frame first!", 3000)
            return

        try:
            from PIL import Image
            import yaml
            from src import game_engine as ge
            from src import image_parser

            cfg = self.config.get('capture', {})
            mode = cfg.get('mode', 'level')
            if mode != 'x':
                self.statusBar().showMessage("Calibrate Colors is only supported in 'x' mode.", 3000)
                return

            crop_x = cfg.get('crop_x', 65)
            crop_y = cfg.get('crop_y', 940)
            crop_w = cfg.get('crop_w', 893)
            crop_h = cfg.get('crop_h', 770)

            img = Image.open(self.latest_screenshot_path).convert("RGB")
            board_img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
            img_w, img_h = board_img.size
            cell_w = crop_w / 4
            cell_h = crop_h / 4

            # Collect dish-color samples per level from the confirmed board
            samples_per_level = {}
            for idx in range(16):
                r, c = divmod(idx, 4)
                lvl = ge.get_cell(self.current_board, r, c)
                if lvl == 0:
                    continue  # skip empty cells

                cl = int(c * cell_w)
                ct = int(r * cell_h)
                cw_i = int((c + 1) * cell_w) - cl
                ch_i = int((r + 1) * cell_h) - ct

                # Sample three points at Y=70% (dish background below fish body)
                pts = []
                for fx in [0.35, 0.50, 0.65]:
                    px = max(0, min(int(cl + fx * cw_i), img_w - 1))
                    py = max(0, min(int(ct + 0.70 * ch_i), img_h - 1))
                    pts.append(board_img.getpixel((px, py)))

                avg = tuple(sum(p[k] for p in pts) // len(pts) for k in range(3))
                samples_per_level.setdefault(lvl, []).append(avg)

            if not samples_per_level:
                self.statusBar().showMessage("Board appears empty — nothing to calibrate!", 3000)
                return

            # Average each level's samples
            new_colors = {}
            for lvl, samps in samples_per_level.items():
                new_colors[lvl] = tuple(sum(s[k] for s in samps) // len(samps) for k in range(3))

            # Load existing capture config, merge in new per-level colours, write back
            path = CAPTURE_CONFIG_PATH
            with open(path, "r") as f:
                yaml_data = yaml.safe_load(f) or {}

            existing_colors = {}
            raw = yaml_data.get('capture', {}).get('colors_x', {})
            for k, v in raw.items():
                try:
                    existing_colors[int(k)] = tuple(v)
                except (ValueError, TypeError):
                    pass

            # Merge: new samples override existing; unknown levels keep their old value
            merged = dict(existing_colors)
            merged.update(new_colors)

            # Serialise back as list-of-ints (YAML-friendly)
            merged_yaml = {str(k): list(merged[k]) for k in sorted(merged)}

            if 'capture' not in yaml_data:
                yaml_data['capture'] = {}
            yaml_data['capture']['colors_x'] = merged_yaml

            with open(path, "w") as f:
                yaml.safe_dump(yaml_data, f, default_flow_style=False)

            # Also update runtime config so next parse uses new colours immediately
            self.config.setdefault('capture', {})['colors_x'] = {int(k): list(v) for k, v in merged.items()}

            template_samples_saved = 0
            if cfg.get('template_matching', False):
                template_samples_saved = image_parser.collect_x_template_samples(
                    self.latest_screenshot_path,
                    ge.board_to_list(self.current_board),
                    cfg,
                )

            # Build summary message
            lv_names = {0:'0',1:'x2',2:'x4',3:'x8',4:'x16',5:'x32',6:'x64',7:'x128',
                        8:'x256',9:'x512',10:'x1024',11:'stone'}
            lines = [f"Calibrated {len(new_colors)} tile level(s):"]
            for lvl in sorted(new_colors):
                r, g, b = new_colors[lvl]
                n_samps = len(samples_per_level[lvl])
                lines.append(f"  {lv_names.get(lvl, f'lvl{lvl}'):6s}: RGB=({r},{g},{b})  [{n_samps} sample(s)]")
            if template_samples_saved:
                lines.append(f"Collected {template_samples_saved} template sample(s) from the confirmed board.")
            summary = "\n".join(lines)
            print(summary)
            QMessageBox.information(self, "Color Calibration Done", summary)
            self.statusBar().showMessage(
                f"Colors calibrated for {len(new_colors)} level(s) and saved to capture_config.yaml!", 4000
            )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.statusBar().showMessage(f"Calibration failed: {e}", 4000)
            print(f"Calibration error:\n{tb}")

    def add_current_as_test_case(self):
        """Crops the current screenshot to the active crop boundaries and saves it as a new
        test case under tests/sample_auto_N.png, recording the manually-corrected board state
        as ground truth in tests/dynamic_samples.json.
        """
        if not getattr(self, 'latest_screenshot_path', None) or not os.path.exists(self.latest_screenshot_path):
            self.statusBar().showMessage("No screenshot available — capture a frame first!", 3000)
            return

        try:
            from PIL import Image
            import json
            from src import game_engine as ge

            # Get current crop settings directly from the spinboxes
            crop_x = self.spn_crop_x.value()
            crop_y = self.spn_crop_y.value()
            crop_w = self.spn_crop_w.value()
            crop_h = self.spn_crop_h.value()
            
            cfg = self.config.get('capture', {})
            mode = cfg.get('mode', 'level')

            # Load screenshot and crop
            img = Image.open(self.latest_screenshot_path)
            img_w, img_h = img.size

            # Clamp coordinates to safely crop
            crop_x = max(0, min(crop_x, img_w - 1))
            crop_y = max(0, min(crop_y, img_h - 1))
            crop_w = max(10, min(crop_w, img_w - crop_x))
            crop_h = max(10, min(crop_h, img_h - crop_y))

            board_img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))

            # Determine a unique filename in tests/
            tests_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests")
            os.makedirs(tests_dir, exist_ok=True)

            idx = 1
            while os.path.exists(os.path.join(tests_dir, f"sample_auto_{idx}.png")):
                idx += 1

            new_filename = f"sample_auto_{idx}.png"
            new_filepath = os.path.join(tests_dir, new_filename)

            # Save the cropped image
            board_img.save(new_filepath)

            # Retrieve current board state levels as ground truth
            ground_truth = ge.board_to_list(self.current_board)

            # Load and update dynamic_samples.json
            dynamic_path = os.path.join(tests_dir, "dynamic_samples.json")
            dynamic_data = []
            if os.path.exists(dynamic_path):
                try:
                    with open(dynamic_path, "r") as f:
                        dynamic_data = json.load(f)
                except Exception as e:
                    print(f"Error loading existing dynamic samples: {e}")

            new_sample = {
                "name": new_filename,
                "mode": mode,
                "ground_truth": ground_truth
            }
            dynamic_data.append(new_sample)

            with open(dynamic_path, "w") as f:
                json.dump(dynamic_data, f, indent=4)

            msg = (
                f"Successfully added test case!\n\n"
                f"Saved crop: tests/{new_filename}\n"
                f"Mode: {mode}\n"
                f"Ground Truth:\n" + "\n".join(f"  {row}" for row in ground_truth)
            )
            print(msg)
            QMessageBox.information(self, "Test Case Added", msg)
            self.statusBar().showMessage(f"Test case tests/{new_filename} added successfully!", 4000)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.statusBar().showMessage(f"Failed to add test case: {e}", 4000)
            print(f"Add test case error:\n{tb}")

        
    def keyPressEvent(self, event: QKeyEvent):
        """Allows playing standard swipes using Arrow Keys."""
        if self.gui_state == "WAITING_FOR_SPAWN":
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.confirm_spawn()
            else:
                super().keyPressEvent(event)
            return
            
        direction = None
        if event.key() == Qt.Key.Key_Left:
            direction = game_engine.LEFT
        elif event.key() == Qt.Key.Key_Right:
            direction = game_engine.RIGHT
        elif event.key() == Qt.Key.Key_Up:
            direction = game_engine.UP
        elif event.key() == Qt.Key.Key_Down:
            direction = game_engine.DOWN
            
        if direction is not None:
            self.execute_move(direction)
        else:
            super().keyPressEvent(event)
            
    def get_tile_style(self, level, capture_warning=False):
        colors = {
            0: ("#2e2e38", "#ffffff"), # empty
            1: ("#4facfe", "#ffffff"), # x1 spawn low
            2: ("#00f2fe", "#121214"), # x1 spawn high
            3: ("#4caf50", "#ffffff"), # x4 spawn low
            4: ("#00e676", "#121214"), # x4 spawn high
            5: ("#ffeb3b", "#121214"),
            6: ("#ff9800", "#ffffff"),
            7: ("#ff5722", "#ffffff"),
            8: ("#f44336", "#ffffff"),
            9: ("#d500f9", "#ffffff"),
            10: ("#651fff", "#ffffff"),
            11: ("#37474f", "#ffffff"), # stone
        }
        bg, fg = colors.get(level, ("#121214", "#ffffff"))
        border = "2px solid #ffffff" if level == 11 else "1px solid #424242"
        border_radius = "8px"
        font_size = "16px"
        font_weight = "bold"
        
        # If waiting for spawn, highlight empty cells with a dash border
        if self.gui_state == "WAITING_FOR_SPAWN" and level == 0:
            border = "2px dashed #0d47a1"
            bg = "#1b1b22"

        if capture_warning:
            border = "3px solid #ffeb3b"
            
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: {border};
                border-radius: {border_radius};
                font-size: {font_size};
                font-weight: {font_weight};
                min-width: 65px;
                min-height: 65px;
            }}
            QPushButton:hover {{
                background-color: {bg}cc;
                border: 2px solid #00f2fe;
            }}
        """
        
    def save_history(self):
        """Saves current state to undo history."""
        self.history.append((
            self.current_board,
            self.total_score,
            self.total_energy,
            self.total_moves,
            self.gui_state,
            self.board_before_move,
            self.board_after_move_no_spawn,
            self.last_move_taken
        ))
        # Cap undo size
        if len(self.history) > 50:
            self.history.pop(0)
            
    def undo(self):
        if not self.history:
            QMessageBox.information(self, "Undo", "Nothing to undo!")
            return
        (
            self.current_board,
            self.total_score,
            self.total_energy,
            self.total_moves,
            self.gui_state,
            self.board_before_move,
            self.board_after_move_no_spawn,
            self.last_move_taken
        ) = self.history.pop()
        self.capture_warning_cells.clear()
        
        self.update_board_display()
        self.update_stats_display()
        self.update_gui_state_display()
        self.reset_confirm_spawn_button()
        self.run_solver()
        self.setFocus()
        
    def reset_board(self):
        self.save_history()
        self.current_board = 0
        self.capture_warning_cells.clear()
        self.gui_state = "NORMAL"
        self.update_board_display()
        self.update_gui_state_display()
        self.reset_confirm_spawn_button()
        self.run_solver()
        self.setFocus()
        
    def new_game(self):
        # Log summary of previous game if played
        if self.total_moves > 0:
            # Detect max level and stones
            grid = game_engine.board_to_list(self.current_board)
            max_lvl = max(max(row) for row in grid)
            stone_count = sum(row.count(11) for row in grid)
            stats.log_game_summary(
                self.total_moves,
                self.total_energy,
                self.total_score,
                self.current_board,
                max_lvl,
                stone_count,
                "User initiated new game"
            )
            
        self.save_history()
        self.current_board = 0
        self.total_score = 0
        self.total_energy = 0
        self.total_moves = 0
        self.gui_state = "NORMAL"
        self.capture_warning_cells.clear()
        
        self.update_board_display()
        self.update_stats_display()
        self.update_gui_state_display()
        self.reset_confirm_spawn_button()
        self.run_solver()
        self.setFocus()
        
    def set_board_cell(self, r, c, val):
        self.save_history()
        self.capture_warning_cells.discard((r, c))
        self.current_board = game_engine.set_cell(self.current_board, r, c, val)
        self.update_board_display()
        
        if getattr(self, 'empty_spawn_confirmed', False):
            self.reset_confirm_spawn_button()
            
        if self.gui_state == "NORMAL":
            self.run_solver()
            
    def handle_cell_click(self, r, c, button_type):
        curr_lvl = game_engine.get_cell(self.current_board, r, c)
        
        mode = self.mode_selector.currentData()
        mode_cfg = self.config['modes'][mode]
        low_spawn = mode_cfg['low_spawn']
        high_spawn = mode_cfg['high_spawn']
        
        if button_type == "left":
            if curr_lvl == 0:
                new_lvl = low_spawn
            elif curr_lvl == low_spawn:
                new_lvl = high_spawn
            else:
                new_lvl = curr_lvl + 1
                if new_lvl > self.config['game']['max_level']:
                    new_lvl = 0
        else:
            new_lvl = 0
            
        self.set_board_cell(r, c, new_lvl)
        self.setFocus()
        
    def execute_move(self, direction):
        """Applies move direction, deducts energy, computes merge scores, triggers spawn state."""
        new_board, merge_score, valid = game_engine.apply_move(self.current_board, direction)
        if not valid:
            self.statusBar().showMessage("Invalid Move! Board does not change.", 2000)
            return
            
        self.save_history()
        self.capture_warning_cells.clear()
        
        mode = self.mode_selector.currentData()
        energy_cost = self.config['modes'][mode]['energy_cost']
        
        # Save game state snapshot
        self.board_before_move = self.current_board
        self.board_after_move_no_spawn = new_board
        self.last_move_taken = direction
        
        # Update board and stats
        self.current_board = new_board
        self.total_score += merge_score
        self.total_energy += energy_cost
        self.total_moves += 1
        
        # Transition to spawn confirmation state
        self.gui_state = "WAITING_FOR_SPAWN"
        
        self.update_board_display()
        self.update_stats_display()
        self.update_gui_state_display()
        self.setFocus()
        
    def execute_recommended_move(self):
        """Applies the recommended move currently calculated by the solver and signals the agent to swipe."""
        if self.gui_state == "WAITING_FOR_SPAWN":
            return
        if getattr(self, 'last_rec_move', None) is not None:
            move_const = self.last_rec_move
            self.execute_move(move_const)
            
            # Send action to capture server so the Android device executes it
            import src.capture_server as capture_server
            dir_str = {
                game_engine.LEFT: "LEFT",
                game_engine.UP: "UP",
                game_engine.RIGHT: "RIGHT",
                game_engine.DOWN: "DOWN"
            }.get(move_const)
            
            if dir_str:
                # Calculate dynamic swipe coordinates based on formulas
                crop_x = self.spn_crop_x.value()
                crop_y = self.spn_crop_y.value()
                crop_w = self.spn_crop_w.value()
                crop_h = self.spn_crop_h.value()
                
                cx = int(crop_x + crop_w / 2)
                cy = int(crop_y + crop_h / 2)
                x_offset = int(crop_w * 0.3)
                y_offset = int(crop_h * 0.3)
                
                coords_map = {
                    game_engine.LEFT:  [cx + x_offset, cy, cx - x_offset, cy, 120],
                    game_engine.RIGHT: [cx - x_offset, cy, cx + x_offset, cy, 120],
                    game_engine.UP:    [cx, cy + y_offset, cx, cy - y_offset, 120],
                    game_engine.DOWN:  [cx, cy - y_offset, cx, cy + y_offset, 120]
                }
                swipe_coords = coords_map.get(move_const)
                
                capture_server.set_action_requested(dir_str, swipe_coords)
                self.lbl_capture_status.setText(f"⚡ Swiping {dir_str}...")
        else:
            self.statusBar().showMessage("No recommended move to apply!", 2000)
        
    def confirm_spawn(self):
        """Calculates difference, logs spawn observations and move result, returns to normal state."""
        # Find which cells changed from board_after_move_no_spawn to current_board
        before_grid = game_engine.board_to_list(self.board_after_move_no_spawn)
        after_grid = game_engine.board_to_list(self.current_board)
        
        spawned_cells = []
        for r in range(4):
            for c in range(4):
                bef = before_grid[r][c]
                aft = after_grid[r][c]
                
                if bef != aft:
                    if bef == 0:
                        spawned_cells.append((r * 4 + c, aft))
                        
        if not spawned_cells:
            if not getattr(self, 'empty_spawn_confirmed', False):
                self.empty_spawn_confirmed = True
                self.btn_confirm_spawn.setText("Sure?")
                self.btn_confirm_spawn.setStyleSheet("background-color: #b71c1c; border: 2px solid #ff1744; color: white; font-weight: bold;")
                self.statusBar().showMessage("Empty spawn detected. Click Confirm again to force empty spawn.", 3000)
                return
                
        # Reset double confirmation state
        self.empty_spawn_confirmed = False
        self.btn_confirm_spawn.setText("Confirm Spawn")
        self.btn_confirm_spawn.setStyleSheet("background-color: #0d47a1; border-color: #1565c0; font-weight: bold; color: white;")
        
        mode = self.mode_selector.currentData()
        
        # Calculate appear points score of spawns
        appear_points_total = 0
        appear_tbl = self.config['appear_points']
        for cell_idx, lvl in spawned_cells:
            appear_points_total += appear_tbl.get(lvl, 0)
            
        self.total_score += appear_points_total
        
        # Calculate empty cells before spawn
        empty_count_before = sum(row.count(0) for row in before_grid)
        
        # Log to files
        # 1. Spawn observation
        stats.log_spawn_observation(
            mode,
            len(spawned_cells),
            [lvl for _, lvl in spawned_cells],
            empty_count_before,
            self.board_after_move_no_spawn,
            self.current_board
        )
        
        # 2. Move result
        # Calculate merge score
        # merge_score = total score delta - appear points
        merge_score = game_engine.apply_move(self.board_before_move, self.last_move_taken)[1]
        stats.log_move_result(
            self.board_before_move,
            DIR_STR[self.last_move_taken],
            mode,
            True,
            merge_score,
            spawned_cells,
            self.current_board
        )
        
        self.gui_state = "NORMAL"
        self.update_stats_display()
        self.update_gui_state_display()
        self.update_board_display()
        self.refresh_stats()
        self.run_solver()
        self.setFocus()
        
    def reset_confirm_spawn_button(self):
        """Resets the Confirm Spawn button to its normal state."""
        self.empty_spawn_confirmed = False
        if hasattr(self, 'btn_confirm_spawn'):
            self.btn_confirm_spawn.setText("Confirm Spawn")
            if self.gui_state == "WAITING_FOR_SPAWN":
                self.btn_confirm_spawn.setStyleSheet("background-color: #0d47a1; border-color: #1565c0; font-weight: bold; color: white;")
            else:
                self.btn_confirm_spawn.setStyleSheet("")
                
    def reset_action_button_styles(self):
        """Resets the manual directional swipe action buttons to standard styles."""
        style = "background-color: #2a2a35; border: 1px solid #3d3d4b; border-radius: 4px; padding: 6px 12px; font-weight: bold; color: #ffffff;"
        if hasattr(self, 'btn_move_left'):
            self.btn_move_left.setStyleSheet(style)
            self.btn_move_up.setStyleSheet(style)
            self.btn_move_down.setStyleSheet(style)
            self.btn_move_right.setStyleSheet(style)
            self.btn_apply_rec.setStyleSheet("background-color: #00796b; border-color: #00897b; color: white;")

    def find_capture_mismatch_cells(self, parsed_board):
        """Returns cells where a capture disagrees with the expected post-move board."""
        if self.gui_state != "WAITING_FOR_SPAWN":
            return set()

        expected_grid = game_engine.board_to_list(self.board_after_move_no_spawn)
        parsed_grid = game_engine.board_to_list(parsed_board)
        warning_cells = set()

        for r in range(4):
            for c in range(4):
                expected = expected_grid[r][c]
                parsed = parsed_grid[r][c]
                if expected == 0:
                    continue  # new spawned tiles are allowed to emerge from empty cells
                if parsed != expected:
                    warning_cells.add((r, c))

        return warning_cells
        
    def update_board_display(self):
        grid = game_engine.board_to_list(self.current_board)
        mode = self.config.get('capture', {}).get('mode', 'level')
        
        for r in range(4):
            for c in range(4):
                level = grid[r][c]
                btn = self.buttons[r][c]
                has_capture_warning = (r, c) in self.capture_warning_cells
                
                # Set text based on level and capture mode
                if level == 0:
                    display_text = ""
                elif level == 11:
                    display_text = "🪨"
                else:
                    if mode == 'x':
                        # In X mode, display the actual tile value (2, 4, 8...)
                        display_text = str(2 ** level)
                    else:
                        # In Level mode, display the raw level (1, 2, 3...)
                        display_text = str(level)

                if has_capture_warning:
                    display_text = f"{display_text} ⚠️" if display_text else "⚠️"

                btn.setText(display_text)
                    
                # Set stylesheet
                btn.setStyleSheet(self.get_tile_style(level, has_capture_warning))
                
    def update_stats_display(self):
        self.score_val_label.setText(f"Score: {self.total_score}")
        self.energy_val_label.setText(f"Energy: {self.total_energy}")
        self.moves_val_label.setText(f"Moves: {self.total_moves}")
        efficiency = (self.total_score / self.total_energy) if self.total_energy > 0 else 0.0
        self.efficiency_val_label.setText(f"Pts/Energy: {efficiency:.2f}")
        
    def update_gui_state_display(self):
        is_normal = (self.gui_state == "NORMAL")
        
        # Toggle enabled state of action buttons
        if hasattr(self, 'btn_move_left'):
            self.btn_move_left.setEnabled(is_normal)
            self.btn_move_up.setEnabled(is_normal)
            self.btn_move_down.setEnabled(is_normal)
            self.btn_move_right.setEnabled(is_normal)
            self.btn_apply_rec.setEnabled(is_normal and getattr(self, 'last_rec_move', None) is not None)
            
        if self.gui_state == "WAITING_FOR_SPAWN":
            self.status_banner.setText("⚠️ WAITING FOR SPAWN: Click spawned tiles, then ENTER or Confirm Spawn")
            self.status_banner.setStyleSheet("""
                background-color: #0d47a1;
                color: #ffffff;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self.btn_confirm_spawn.setEnabled(True)
            
            # Clear previous recommendation display to show we are waiting for spawn input
            if hasattr(self, 'rec_dir_label'):
                self.rec_dir_label.setText("Waiting for spawn input... 🕒")
            if hasattr(self, 'val_ev'):
                self.val_ev.setText("-")
            if hasattr(self, 'val_ev_energy'):
                self.val_ev_energy.setText("-")
            if hasattr(self, 'val_survival'):
                self.val_survival.setValue(0)
            if hasattr(self, 'decision_badge'):
                self.decision_badge.setText("WAITING FOR SPAWN")
                self.decision_badge.setStyleSheet("background-color: #0d47a1; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold;")
        else:
            self.status_banner.setText("STATUS: Active Game / Edit Mode")
            self.status_banner.setStyleSheet("""
                background-color: #2b2b36;
                color: #b0bec5;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self.btn_confirm_spawn.setEnabled(False)
            
    def refresh_stats(self):
        """Recalculates empirical statistics and displays them."""
        summary = stats.compute_spawn_statistics(self.config)
        txt = []
        txt.append(f"Total Observed Spawns: {summary['total_observations']}")
        if summary['total_observations'] > 0 and summary.get('relative_probabilities'):
            sorted_pats = sorted(summary['relative_probabilities'].items(), key=lambda x: x[1], reverse=True)
            pat_strs = []
            for rel_pat, prob in sorted_pats:
                lbl_list = ['L' if idx == 1 else 'H' for idx in rel_pat]
                pat_str = f"[{', '.join(lbl_list)}]: {prob*100:.1f}%"
                pat_strs.append(pat_str)
            txt.append("Pooled Spawn Distribution:")
            txt.append("  " + " | ".join(pat_strs))
        if summary['confidence_warning']:
            txt.append(f"⚠️ {summary['confidence_warning']}")
            
        self.stats_text.setText("\n".join(txt))
        
    def run_solver(self):
        """Runs expectimax evaluation on a background thread and updates GUI recommendations panel."""
        if self.gui_state == "WAITING_FOR_SPAWN":
            return # Don't solve when waiting for spawn input
            
        # Cancel all active running threads before starting a new one.
        # Disconnect signals first so stale results don't leak in.
        # We do NOT block-wait here — instead we use a generation counter to discard stale results.
        if hasattr(self, 'active_threads'):
            for t in list(self.active_threads):
                if t.isRunning():
                    t.cancel()
                    try:
                        t.solver_finished.disconnect()
                        t.solver_failed.disconnect()
                    except TypeError:
                        pass
                    
        # Reset highlighted button styles at start of computation
        self.reset_action_button_styles()
        self.statusBar().showMessage("Solving... 🧠")
        
        # Clear recommendation panel immediately so we never show stale data
        if hasattr(self, 'rec_dir_label'):
            self.rec_dir_label.setText("Solving... 🧠")
        if hasattr(self, 'val_ev'):
            self.val_ev.setText("-")
        if hasattr(self, 'val_ev_energy'):
            self.val_ev_energy.setText("-")
        if hasattr(self, 'val_survival'):
            self.val_survival.setValue(0)
        if hasattr(self, 'decision_badge'):
            self.decision_badge.setText("COMPUTING")
            self.decision_badge.setStyleSheet("background-color: #37474f; color: #b0bec5; padding: 5px 15px; border-radius: 12px; font-weight: bold;")
        self.last_rec_move = None
        if hasattr(self, 'btn_apply_rec'):
            self.btn_apply_rec.setEnabled(False)
        
        # Read parameters on the main thread
        selected_mode = self.mode_selector.currentData()
        override_depth = self.depth_selector.currentData() if hasattr(self, 'depth_selector') else None
        override_time = self.time_selector.currentData() if hasattr(self, 'time_selector') else None
        use_empirical = hasattr(self, 'chk_empirical_spawn') and self.chk_empirical_spawn.isChecked()
        
        # Build dynamic enabled modes list based on user selections
        enabled_modes = ['x1', 'x4']
        if hasattr(self, 'chk_x8') and self.chk_x8.isChecked():
            enabled_modes.append('x8')
        if hasattr(self, 'chk_x16') and self.chk_x16.isChecked():
            enabled_modes.append('x16')
        if selected_mode not in enabled_modes:
            enabled_modes.append(selected_mode)
            
        self.selected_mode = selected_mode
        self.enabled_modes = enabled_modes
        self.current_search_results = {}
        self.completed_modes = set()
        self.solver_start_time = time.time()
            
        # Increment generation counter — any result from an older generation is discarded
        self._solver_generation += 1
        current_generation = self._solver_generation
        
        if hasattr(self, 'btn_solve'):
            self.btn_solve.setEnabled(False)
            self.btn_solve.setText("⏳ Solving...")
            
        # Create a unique cancel filepath
        import uuid
        logs_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        cancel_filepath = os.path.join(logs_dir, f"cancel_{uuid.uuid4().hex}.tmp")
            
        # Instantiate and start the thread
        thread = SolverThread(
            board=self.current_board,
            config=self.config,
            selected_mode=selected_mode,
            override_depth=override_depth,
            override_time=override_time,
            use_empirical=use_empirical,
            enabled_modes=enabled_modes,
            cancel_filepath=cancel_filepath,
            generation=current_generation
        )
        self.active_threads.append(thread)
        thread.finished.connect(lambda t=thread: self.cleanup_thread(t))
        thread.solver_finished.connect(self.on_solver_finished)
        thread.solver_progress.connect(self.on_solver_progress)
        thread.solver_failed.connect(self.on_solver_failed)
        thread.start()

    def cleanup_thread(self, thread):
        """Called when a SolverThread emits finished(). Safe to call from any state."""
        if hasattr(self, 'active_threads') and thread in self.active_threads:
            self.active_threads.remove(thread)
        # Schedule deletion on next event loop tick so Qt can clean up safely
        thread.deleteLater()

    def on_solver_progress(self, event, generation):
        """Handles an IPC progress event from one of the worker processes."""
        if generation != self._solver_generation:
            return
            
        # Update aggregated results
        mode = event["mode"]
        depth = event["depth"]
        is_final = event["is_final"]
        
        self.current_search_results.setdefault(mode, {})[depth] = event
        if is_final:
            self.completed_modes.add(mode)
            
        # Build aggregated evaluation dict and display it
        evaluation = self.aggregate_and_build_eval()
        if evaluation is None:
            # Not enough data yet (waiting for all modes to complete depth 2)
            self.update_loading_reasons_box()
            return
            
        elapsed_ms = (time.time() - self.solver_start_time) * 1000
        self._display_solver_result(evaluation, elapsed_ms, self.selected_mode, is_partial=True)

    def on_solver_finished(self, generation):
        """Handles the final completion of the solver thread (all workers exited)."""
        if generation != self._solver_generation:
            return
        if hasattr(self, 'btn_solve'):
            self.btn_solve.setEnabled(True)
            self.btn_solve.setText("Solve")
        self.statusBar().showMessage("Ready", 3000)
        
        # Build final evaluation dict and display
        evaluation = self.aggregate_and_build_eval()
        if evaluation is None:
            return
            
        elapsed_ms = (time.time() - self.solver_start_time) * 1000
        self._display_solver_result(evaluation, elapsed_ms, self.selected_mode, is_partial=False)

        # Auto Apply Recommended Move if checked, no mismatches, and recommended move exists
        if getattr(self, 'chk_auto_apply', None) and self.chk_auto_apply.isChecked():
            if self.capture_warning_cells:
                self.statusBar().showMessage("⚠️ Auto Apply stopped: parser mismatch warning detected.", 5000)
                return
            if getattr(self, 'last_rec_move', None) is not None:
                self.execute_recommended_move()

    def aggregate_and_build_eval(self):
        """
        Aggregates per-mode progress events. 
        Returns an evaluation dict evaluated at the highest common completed depth (fair_depth),
        while ensuring the selected mode's results in the evaluation dict are at that fair_depth.
        """
        # Determine completed depths for each enabled mode
        max_completed_depths = {}
        for m in self.enabled_modes:
            depths = self.current_search_results.get(m, {}).keys()
            max_completed_depths[m] = max(depths) if depths else 0
            
        # Highest common completed depth among all enabled modes
        fair_depth = min(max_completed_depths.values()) if max_completed_depths else 0
        
        # We need at least depth 2 for a valid comparison
        if fair_depth < 2:
            return None
            
        # Get each mode's result at fair_depth
        results_at_fair_depth = {}
        for m in self.enabled_modes:
            res_event = self.current_search_results[m].get(fair_depth)
            if res_event:
                best_move_str = res_event.get("best_move")
                best_move_int = DIR_MAP_FROM_STR.get(best_move_str) if best_move_str else None
                m_vals = {DIR_MAP_FROM_STR[k]: v for k, v in res_event.get("move_values", {}).items() if k in DIR_MAP_FROM_STR}
                m_real_vals = {DIR_MAP_FROM_STR[k]: v for k, v in res_event.get("move_real_values", {}).items() if k in DIR_MAP_FROM_STR}
                
                results_at_fair_depth[m] = {
                    'best_move': best_move_int,
                    'ev': res_event['real_ev'],
                    'ev_per_energy': res_event['ev_per_energy'],
                    'expected_empty': res_event.get('expected_empty', 0.0),
                    'move_values': m_vals,
                    'move_real_values': m_real_vals,
                    'completed_depth': fair_depth,
                    'node_count': res_event['nodes']
                }
            else:
                results_at_fair_depth[m] = None
                
        # Find best mode at fair_depth
        best_overall_mode = None
        best_overall_move = None
        best_overall_val_per_energy = -float('inf')
        survival_score = 0.0
        
        for mode, res in results_at_fair_depth.items():
            if res is None:
                continue
            ev_per_energy = res['ev_per_energy']
            if ev_per_energy > best_overall_val_per_energy:
                best_overall_val_per_energy = ev_per_energy
                best_overall_mode = mode
                best_overall_move = res['best_move']
                survival_score = (res['expected_empty'] / 16.0) * 100.0
                
        # Calculate decision based on the best overall mode at fair_depth
        direct_conv = self.config['decision']['direct_conversion_value_per_energy']
        fresh_baseline = self.config['decision']['fresh_game_baseline_value_per_energy']
        has_any_move = any(res is not None for res in results_at_fair_depth.values())
        
        if not has_any_move:
            decision = "GAME_OVER"
        elif best_overall_val_per_energy < direct_conv:
            decision = "STOP_AND_CONVERT"
        elif best_overall_val_per_energy < fresh_baseline:
            decision = "RESTART_GAME"
        else:
            decision = "CONTINUE"
            
        # Headline recommendation must stay at fair-depth.
        # This means the selected mode's results in the evaluation dict are at fair_depth!
        selected_mode_results = results_at_fair_depth.get(self.selected_mode)
        
        # Calculate total nodes searched across all modes at their latest completed depths
        total_nodes = 0
        for m in self.enabled_modes:
            m_max = max_completed_depths.get(m, 0)
            if m_max >= 2:
                total_nodes += self.current_search_results[m][m_max].get("nodes", 0)
                
        return {
            'best_mode': best_overall_mode,
            'best_move': best_overall_move,
            'best_val_per_energy': best_overall_val_per_energy,
            'survival_score': survival_score,
            'decision': decision,
            'results': {
                self.selected_mode: selected_mode_results
            },
            'completed_depth': fair_depth,
            'node_count': total_nodes,
        }

    def update_loading_reasons_box(self):
        """Displays initialization/progress in the reasons box before all modes complete depth 2."""
        report = []
        report.append("Per-Mode Progress:")
        
        max_completed_depths = {}
        for m in self.enabled_modes:
            depths = self.current_search_results.get(m, {}).keys()
            max_completed_depths[m] = max(depths) if depths else 0
            
        for m in self.enabled_modes:
            m_max_d = max_completed_depths.get(m, 0)
            is_finished = m in self.completed_modes
            status = "finished" if is_finished else "searching..."
            if m_max_d >= 2:
                m_event = self.current_search_results[m][m_max_d]
                m_best_move = m_event.get("best_move")
                m_nodes = m_event.get("nodes", 0)
                m_time = m_event.get("elapsed_ms", 0.0)
                report.append(f"  ● {m.upper()}: best {m_best_move} at d{m_max_d} (Nodes: {m_nodes:,} | {m_time:.1f}ms) [{status}]")
            else:
                report.append(f"  ● {m.upper()}: initializing... [{status}]")
        report.append("")
        report.append("Global Fair Recommendation:")
        report.append("  ⌛ Waiting for all modes to complete depth 2...\n")
        report.append("=" * 45 + "\n")
        
        self.reasons_box.setPlainText("\n".join(report))
        self.rec_dir_label.setText("⌛ Thinking...")
        self.decision_badge.setText("⌛ THINKING")
        self.decision_badge.setStyleSheet(
            "background-color: #e65100; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold;"
        )
        self.val_ev.setText("⌛")
        self.val_ev_energy.setText("⌛")
        self.val_survival.setValue(0)


    def _display_solver_result(self, evaluation, elapsed_ms, selected_mode, is_partial=False):
        """Shared display logic for both partial (streaming) and final solver results."""
        try:
            mode_results = evaluation['results'].get(selected_mode)
            
            if mode_results is None or mode_results['best_move'] is None:
                if not is_partial:
                    # Only clear recommendation on final game-over result
                    self.last_rec_move = None
                    if hasattr(self, 'btn_apply_rec'):
                        self.btn_apply_rec.setEnabled(False)
                    self.rec_dir_label.setText("GAME OVER 💀")
                    self.decision_badge.setText("GAME OVER")
                    self.decision_badge.setStyleSheet("background-color: #552222; color: white; padding: 5px; border-radius: 12px;")
                    self.val_ev.setText("N/A")
                    self.val_ev_energy.setText("N/A")
                    self.val_survival.setValue(0)
                    self.reasons_box.setPlainText("No valid moves exist on the board.")
                return
                
            best_move = mode_results['best_move']
            self.last_rec_move = best_move  # Allow apply-rec even on partial
            
            # Highlight the recommended direction button and the Apply button
            highlight_style = "background-color: #311b92; border: 2px solid #d500f9; border-radius: 4px; padding: 5px 11px; font-weight: bold; color: #ffffff;"
            self.reset_action_button_styles()
            if best_move == game_engine.LEFT:
                self.btn_move_left.setStyleSheet(highlight_style)
            elif best_move == game_engine.UP:
                self.btn_move_up.setStyleSheet(highlight_style)
            elif best_move == game_engine.DOWN:
                self.btn_move_down.setStyleSheet(highlight_style)
            elif best_move == game_engine.RIGHT:
                self.btn_move_right.setStyleSheet(highlight_style)
                
            if hasattr(self, 'btn_apply_rec'):
                self.btn_apply_rec.setEnabled(self.gui_state == "NORMAL")
                self.btn_apply_rec.setStyleSheet("background-color: #00796b; border: 2px solid #00e676; border-radius: 4px; padding: 5px 11px; font-weight: bold; color: #ffffff;")
                
            ev = mode_results['ev']
            ev_per_energy = mode_results['ev_per_energy']
            move_values = mode_results['move_values']           # heuristic ranking scores
            move_real_values = mode_results.get('move_real_values', {})  # real expected pts
            
            # Decide label prefix and badge style based on partial vs final
            completed_depth = evaluation.get('completed_depth', 0)
            best_overall_mode = evaluation['best_mode']
            mode_rec_str = ""
            
            if is_partial:
                prefix = f"🔍 CURRENT BEST (d{completed_depth}):"
                badge_prefix = "⌛ "
            else:
                prefix = "✅ RECOMMEND:"
                badge_prefix = ""
            
            rec_text = f"{prefix} {DIR_STR[best_move]}"
            if best_overall_mode and best_overall_mode != selected_mode:
                mode_rec_str = f"👉 Switch to {best_overall_mode.upper()} mode! (Higher EV/Energy: {evaluation['best_val_per_energy']:.2f})\n\n"
                rec_text += f"  (👉 Switch to {best_overall_mode.upper()}!)"

            # Update direction label
            self.rec_dir_label.setText(rec_text)
            self.val_ev.setText(f"{ev:.2f} pts")
            self.val_ev_energy.setText(f"{ev_per_energy:.2f} pts/energy")
            
            # Survival Score
            survival = evaluation['survival_score']
            self.val_survival.setValue(int(survival))
            
            # Decision Badge
            decision = evaluation['decision']
            badge_text = badge_prefix + decision.replace("_", " ")
            if "RESTART" in decision or "CONVERT" in decision:
                badge_text += " (EXPERIMENTAL)"
            self.decision_badge.setText(badge_text)
            
            if is_partial:
                # Amber pulsing style for in-progress
                self.decision_badge.setStyleSheet(
                    "background-color: #e65100; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold;"
                )
            elif decision == "CONTINUE":
                self.decision_badge.setStyleSheet("background-color: #2e7d32; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold;")
            elif decision == "RESTART_GAME":
                self.decision_badge.setStyleSheet("background-color: #ef6c00; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold;")
            elif decision == "STOP_AND_CONVERT":
                self.decision_badge.setStyleSheet("background-color: #c62828; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold;")
            else:
                self.decision_badge.setStyleSheet("background-color: #424242; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold;")
                
            # Explain move reasons
            reasons = solver.explain_move(self.current_board, best_move, self.config)
            
            # Calculate max completed depth for each enabled mode
            max_completed_depths = {}
            for m in self.enabled_modes:
                depths = self.current_search_results.get(m, {}).keys()
                max_completed_depths[m] = max(depths) if depths else 0
                
            # Build report
            report = []
            
            # 1. Per-mode progress section
            report.append("Per-Mode Progress:")
            for m in self.enabled_modes:
                m_max_d = max_completed_depths.get(m, 0)
                is_finished = m in self.completed_modes
                status = "finished" if is_finished else "searching..."
                if m_max_d >= 2:
                    m_event = self.current_search_results[m][m_max_d]
                    m_best_move = m_event.get("best_move")
                    m_nodes = m_event.get("nodes", 0)
                    m_time = m_event.get("elapsed_ms", 0.0)
                    report.append(f"  ● {m.upper()}: best {m_best_move} at d{m_max_d} (Nodes: {m_nodes:,} | {m_time:.1f}ms) [{status}]")
                else:
                    report.append(f"  ● {m.upper()}: initializing... [{status}]")
            report.append("")
            
            # 2. Global fair recommendation section
            fair_depth = completed_depth  # In evaluation dict, completed_depth is fair_depth
            report.append(f"Global Fair Recommendation (at depth {fair_depth}):")
            for m in self.enabled_modes:
                res_event = self.current_search_results[m].get(fair_depth)
                if res_event:
                    report.append(f"  ● {m.upper()}: EV/Energy = {res_event['ev_per_energy']:.2f} (best {res_event['best_move']})")
                else:
                    report.append(f"  ● {m.upper()}: N/A")
            
            if best_overall_mode:
                report.append(f"  🏆 Winner: {best_overall_mode.upper()} mode")
            report.append("")
            
            if mode_rec_str:
                report.append(mode_rec_str)
            if is_partial:
                report.append(f"🔄 Searching deeper... (headline recommendation pinned at depth {fair_depth})")
                
            # Prepend search stats
            node_count = evaluation.get('node_count', 0)
            status_line = f"Search Stats: Depth {fair_depth} | Nodes {node_count} | Time {elapsed_ms:.1f}ms"
            if is_partial:
                status_line += "  ⏳"
            report.append(status_line)
            report.append("=" * 45 + "\n")
                
            report.append("Heuristic Rationale:")
            for r in reasons:
                report.append(f" • {r}")
                
            report.append("\nMove Comparison (ranked by heuristic search score):")
            energy_cost = self.config['modes'][selected_mode]['energy_cost']
            sorted_moves = sorted(move_values.items(), key=lambda x: x[1], reverse=True)
            for m, heuristic_val in sorted_moves:
                pref = "★ " if m == best_move else "  "
                real_val = move_real_values.get(m)
                if real_val is not None:
                    real_per_energy = real_val / energy_cost
                    report.append(
                        f"{pref}{DIR_STR[m]:<10}: "
                        f"RealEV={real_val:<9.2f}  EV/Energy={real_per_energy:.2f}  "
                        f"[HeuristicScore={heuristic_val:.0f}]"
                    )
                else:
                    report.append(f"{pref}{DIR_STR[m]:<10}: HeuristicScore={heuristic_val:.0f}")
            
            report.append(f"\n[RealEV = accumulated real merge+spawn pts across search tree]")
            report.append(f"[HeuristicScore = search ranking value; used for move ordering only]")
            self.reasons_box.setPlainText("\n".join(report))
            
            # Only log to disk on the final (non-partial) result
            if not is_partial:
                features = {
                    'empty_cells': sum(row.count(0) for row in game_engine.board_to_list(self.current_board)),
                    'heuristic_value': solver.get_heuristic_score(self.current_board, self.config)
                }
                stats.log_board_evaluation(
                    self.current_board,
                    list(self.config['modes'].keys()),
                    selected_mode,
                    DIR_STR[best_move],
                    move_values,
                    ev_per_energy,
                    decision,
                    features,
                    completed_depth
                )
            
        except Exception as e:
            traceback.print_exc()
            self.statusBar().showMessage(f"Solver Error: {str(e)}", 3000)

    def on_solver_failed(self, error_msg):
        if hasattr(self, 'btn_solve'):
            self.btn_solve.setEnabled(True)
            self.btn_solve.setText("Solve")
        self.statusBar().showMessage("Solver Failed ❌", 3000)
        print(f"Solver thread failed:\n{error_msg}")

    def closeEvent(self, event):
        """Gracefully cancel all in-flight solver threads and shut down process pool."""
        if hasattr(self, 'active_threads'):
            # Signal cancellation on all threads simultaneously
            for t in list(self.active_threads):
                try:
                    t.solver_finished.disconnect()
                    t.solver_failed.disconnect()
                except TypeError:
                    pass
                t.cancel()
            # Now wait for all of them to finish
            for t in list(self.active_threads):
                t.wait(5000)  # up to 5 s per thread
        solver.shutdown_executor()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = Solver2048dGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
