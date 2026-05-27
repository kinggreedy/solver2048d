# tests/test_gui_retry.py
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Set up QApplication offscreen for GUI instantiation in tests
from PyQt6.QtWidgets import QApplication
app = QApplication.instance()
if not app:
    app = QApplication(["-platform", "offscreen"])

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src import game_engine

class TestGUIRetry(unittest.TestCase):
    def setUp(self):
        # Patch PyQt status updates and expectimax searches to make instantiation clean and isolated
        self.patch_start_server = patch('src.capture_server.start_server')
        self.patch_run_solver = patch('src.gui.Solver2048dGUI.run_solver')
        self.patch_set_action = patch('src.capture_server.set_action_requested')
        
        self.mock_start_server = self.patch_start_server.start()
        self.mock_run_solver = self.patch_run_solver.start()
        self.mock_set_action = self.patch_set_action.start()
        
        from src.gui import Solver2048dGUI
        self.gui = Solver2048dGUI()

    def tearDown(self):
        self.patch_start_server.stop()
        self.patch_run_solver.stop()
        self.patch_set_action.stop()

    def test_post_swipe_validation_failure_retries(self):
        """If parsed board matches board_before_move in WAITING_FOR_SPAWN and Auto Apply is enabled, it retries."""
        self.gui.gui_state = "WAITING_FOR_SPAWN"
        
        # Define a test board state
        test_grid = [
            [0, 1, 2, 3],
            [4, 5, 6, 7],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        test_board = game_engine.list_to_board(test_grid)
        
        self.gui.board_before_move = test_board
        self.gui.chk_auto_apply.setChecked(True)
        self.gui.last_move_taken = game_engine.UP
        
        # Trigger incoming capture with the identical board (meaning swipe failed to change it)
        self.gui.handle_incoming_capture("temp.png", test_grid)
        
        # Check that a retry action was issued to capture_server
        self.mock_set_action.assert_called_once()
        args, kwargs = self.mock_set_action.call_args
        self.assertEqual(args[0], "UP")  # The direction of self.last_move_taken
        
        # Check that status labels and state are correct
        self.assertEqual(self.gui.lbl_capture_status.text(), "⚡ Retrying UP...")
        self.assertEqual(self.gui.gui_state, "WAITING_FOR_SPAWN")

    def test_post_swipe_validation_failure_no_auto_apply(self):
        """If parsed board matches board_before_move in WAITING_FOR_SPAWN but Auto Apply is disabled, it does not retry."""
        self.gui.gui_state = "WAITING_FOR_SPAWN"
        
        test_grid = [
            [0, 1, 2, 3],
            [4, 5, 6, 7],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        test_board = game_engine.list_to_board(test_grid)
        
        self.gui.board_before_move = test_board
        self.gui.chk_auto_apply.setChecked(False)
        self.gui.last_move_taken = game_engine.UP
        
        # Trigger incoming capture with the identical board
        self.gui.handle_incoming_capture("temp.png", test_grid)
        
        # Check that NO retry action was issued
        self.mock_set_action.assert_not_called()
        
        # Check that status shows swipe failed
        self.assertEqual(self.gui.lbl_capture_status.text(), "🛑 Swipe Failed")
        self.assertEqual(self.gui.gui_state, "WAITING_FOR_SPAWN")

    def test_metrics_retention_during_waiting_for_spawn(self):
        """When in WAITING_FOR_SPAWN, display updates do not overwrite recommended move text with solver recommendations, but keep metrics."""
        self.gui.gui_state = "WAITING_FOR_SPAWN"
        self.gui.enabled_modes = ['x1']
        
        # Set text of labels before update
        self.gui.rec_dir_label.setText("Waiting for spawn input... 🕒")
        self.gui.decision_badge.setText("WAITING FOR SPAWN")
        self.gui.val_ev.setText("10.00 pts")
        self.gui.val_ev_energy.setText("5.00 pts/energy")
        self.gui.val_survival.setValue(50)
        
        # Mock evaluation dict returned by solver
        evaluation = {
            'best_mode': 'x1',
            'best_val_per_energy': 12.5,
            'completed_depth': 4,
            'survival_score': 85.0,
            'decision': 'CONTINUE',
            'results': {
                'x1': {
                    'best_move': game_engine.LEFT,
                    'ev': 25.5,
                    'ev_per_energy': 12.75,
                    'move_values': {},
                    'move_real_values': {}
                }
            }
        }
        
        # Trigger display result (as if background solver finished)
        self.gui._display_solver_result(evaluation, elapsed_ms=100, selected_mode='x1')
        
        # Verify recommendation label and badge stay in spawn-waiting state
        self.assertEqual(self.gui.rec_dir_label.text(), "Waiting for spawn input... 🕒")
        self.assertEqual(self.gui.decision_badge.text(), "WAITING FOR SPAWN")
        
        # Verify metrics (EV, EV Per Energy, Survival score) are updated/retained
        self.assertEqual(self.gui.val_ev.text(), "25.50 pts")
        self.assertEqual(self.gui.val_ev_energy.text(), "12.75 pts/energy")
        self.assertEqual(self.gui.val_survival.value(), 85)
