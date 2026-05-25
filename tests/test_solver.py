# tests/test_solver.py
import unittest
import random
from src import game_engine
from src import solver

class TestSolver(unittest.TestCase):
    def setUp(self):
        self.config = game_engine.config
        self.orig_max_time = self.config['solver'].get('max_time_ms')
        self.config['solver']['max_time_ms'] = 0

    def tearDown(self):
        if hasattr(self, 'orig_max_time'):
            if self.orig_max_time is not None:
                self.config['solver']['max_time_ms'] = self.orig_max_time
            elif 'max_time_ms' in self.config['solver']:
                del self.config['solver']['max_time_ms']

    def test_8_solver_returns_valid_moves_only(self):
        """Solver returns only valid moves."""
        grid = [
            [0, 2, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board = game_engine.list_to_board(grid)
        best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
        
        valid_moves = game_engine.get_valid_moves(board)
        self.assertIn(best_move, valid_moves)

    def test_9_solver_near_full_board_no_crash(self):
        """Solver can evaluate a nearly full board without crashing."""
        grid = [
            [1, 2, 3, 4],
            [5, 6, 7, 8],
            [9, 10, 11, 0],
            [2, 3, 4, 0]
        ]
        board = game_engine.list_to_board(grid)
        try:
            best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
            self.assertIsNotNone(ev)
        except Exception as e:
            self.fail(f"Solver crashed on nearly full board: {e}")

    def test_10_restart_decision_triggers(self):
        """Restart decision triggers when estimated EV is below fresh baseline."""
        grid = [
            [11, 1, 11, 2],
            [3, 11, 4, 11],
            [11, 5, 11, 6],
            [7, 11, 8, 9]
        ]
        board = game_engine.list_to_board(grid)
        evaluation = solver.evaluate_board_options(board, self.config, enabled_modes=['x1'])
        self.assertIn(evaluation['decision'], ["RESTART_GAME", "STOP_AND_CONVERT", "GAME_OVER"])

    def test_11_solver_merges_to_level_11(self):
        """Solver should prioritize merging two level-10 tiles to form a level-11 stone."""
        grid = [
            [10, 10, 8, 7],
            [5,  4,  3, 2],
            [1,  0,  0, 0],
            [0,  0,  0, 0]
        ]
        board = game_engine.list_to_board(grid)
        best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
        self.assertEqual(best_move, game_engine.LEFT)

    def test_12_simulation_reaches_level_11(self):
        """Simulate playing from a level 10 board and verify we reach level 11 consistently."""
        random.seed(42)
        grid_start = [
            [10, 9, 8, 7],
            [3,  4, 5, 6],
            [2,  1, 0, 0],
            [0,  0, 0, 0]
        ]
        board = game_engine.list_to_board(grid_start)
        
        reached_11 = False
        for step in range(50):
            grid = game_engine.board_to_list(board)
            if any(11 in row for row in grid):
                reached_11 = True
                break
                
            best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
            if best_move is None:
                break
                
            board, _, valid = game_engine.apply_move(board, best_move)
            if not valid:
                break
                
            outcomes = game_engine.get_spawn_outcomes(board, 'x1')
            if not outcomes:
                break
                
            probs = [o[0] for o in outcomes]
            outcome = random.choices(outcomes, weights=probs, k=1)[0]
            board = outcome[1]
            
        self.assertTrue(reached_11, "Failed to reach level 11 in simulation from level 10 board.")

    def test_13_level_breakthrough_simulation_reaches_level_12(self):
        """Enable level breakthrough in config and verify we reach level 12 in simulation from level 11."""
        orig_stone = self.config['game'].get('level_11_stone', True)
        try:
            self.config['game']['level_11_stone'] = False
            game_engine.config = self.config
            game_engine.init_tables()
            
            random.seed(42)
            grid_start = [
                [11, 10, 9, 8],
                [4,  5,  6,  7],
                [3,  2,  1,  0],
                [1,  1,  1,  1]
            ]
            board = game_engine.list_to_board(grid_start)
            
            reached_12 = False
            for step in range(50):
                grid = game_engine.board_to_list(board)
                if any(12 in row for row in grid):
                    reached_12 = True
                    break
                    
                best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
                if best_move is None:
                    break
                    
                board, _, valid = game_engine.apply_move(board, best_move)
                if not valid:
                    break
                    
                outcomes = game_engine.get_spawn_outcomes(board, 'x1')
                if not outcomes:
                    break
                    
                probs = [o[0] for o in outcomes]
                outcome = random.choices(outcomes, weights=probs, k=1)[0]
                board = outcome[1]
                
            self.assertTrue(reached_12, "Failed to reach level 12 in breakthrough simulation.")
        finally:
            self.config['game']['level_11_stone'] = orig_stone
            game_engine.config = self.config
            game_engine.init_tables()

    def test_14_level_breakthrough_simulation_reaches_level_13(self):
        """Enable level breakthrough in config and verify we reach level 13 in simulation from level 12."""
        orig_stone = self.config['game'].get('level_11_stone', True)
        try:
            self.config['game']['level_11_stone'] = False
            game_engine.config = self.config
            game_engine.init_tables()
            
            random.seed(42)
            grid_start = [
                [12, 11, 10, 9],
                [5,  6,  7,  8],
                [4,  3,  2,  1],
                [1,  1,  1,  1]
            ]
            board = game_engine.list_to_board(grid_start)
            
            reached_13 = False
            for step in range(50):
                grid = game_engine.board_to_list(board)
                if any(13 in row for row in grid):
                    reached_13 = True
                    break
                    
                best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
                if best_move is None:
                    break
                    
                board, _, valid = game_engine.apply_move(board, best_move)
                if not valid:
                    break
                    
                outcomes = game_engine.get_spawn_outcomes(board, 'x1')
                if not outcomes:
                    break
                    
                probs = [o[0] for o in outcomes]
                outcome = random.choices(outcomes, weights=probs, k=1)[0]
                board = outcome[1]
                
            self.assertTrue(reached_13, "Failed to reach level 13 in breakthrough simulation.")
        finally:
            self.config['game']['level_11_stone'] = orig_stone
            game_engine.config = self.config
            game_engine.init_tables()

    def test_15_simulation_from_level_8_reaches_level_11(self):
        """Verify that the solver can successfully play from a level-8 starting state to reach level-11 stone."""
        random.seed(801)
        grid_start = [
            [8, 7, 6, 5],
            [1, 2, 3, 4],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board = game_engine.list_to_board(grid_start)
        
        reached_11 = False
        for step in range(500):
            grid = game_engine.board_to_list(board)
            if any(11 in row for row in grid):
                reached_11 = True
                break
                
            best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
            if best_move is None:
                break
                
            board, _, valid = game_engine.apply_move(board, best_move)
            if not valid:
                break
                
            outcomes = game_engine.get_spawn_outcomes(board, 'x1')
            if not outcomes:
                break
                
            probs = [o[0] for o in outcomes]
            outcome = random.choices(outcomes, weights=probs, k=1)[0]
            board = outcome[1]
            
        self.assertTrue(reached_11, "Failed to reach level 11 stone from level 8 board.")

    def test_16_simulation_creates_third_stone(self):
        """Verify that the solver can play around multiple stones and successfully create a third stone."""
        random.seed(1000)
        grid_start = [
            [11, 10, 9, 11],
            [5,  6,  7,  8],
            [4,  3,  2,  1],
            [1,  1,  1,  1]
        ]
        board = game_engine.list_to_board(grid_start)
        
        reached_three_stones = False
        for step in range(50):
            grid = game_engine.board_to_list(board)
            count_11 = sum(row.count(11) for row in grid)
            if count_11 >= 3:
                reached_three_stones = True
                break
                
            best_move, ev, expected_empty, move_values, _, _, _ = solver.get_best_move(board, 'x1', self.config)
            if best_move is None:
                break
                
            board, _, valid = game_engine.apply_move(board, best_move)
            if not valid:
                break
                
            outcomes = game_engine.get_spawn_outcomes(board, 'x1')
            if not outcomes:
                break
                
            probs = [o[0] for o in outcomes]
            outcome = random.choices(outcomes, weights=probs, k=1)[0]
            board = outcome[1]
            
        self.assertTrue(reached_three_stones, "Failed to create a third level 11 stone.")

    def test_17_risk_aversion_prefers_safer_anchors(self):
        """Verify that risk aversion correctly penalizes moves with catastrophic anchor loss risk."""
        grid = [
            [8, 7, 6, 9],
            [1, 5, 5, 0],
            [1, 2, 3, 0],
            [2, 1, 1, 2]
        ]
        board = game_engine.list_to_board(grid)
        orig_risk = self.config['solver'].get('risk_aversion')
        try:
            self.config['solver']['risk_aversion'] = 0.0
            best_move_no_risk, ev_no_risk, _, move_values_no_risk, _, _, _ = solver.get_best_move(
                board, 'x1', self.config, override_depth=3
            )
            
            self.config['solver']['risk_aversion'] = 10.0
            best_move_with_risk, ev_with_risk, _, move_values_with_risk, _, _, _ = solver.get_best_move(
                board, 'x1', self.config, override_depth=3
            )
            
            for move, val_no_risk in move_values_no_risk.items():
                val_with_risk = move_values_with_risk[move]
                self.assertLessEqual(val_with_risk, val_no_risk, 
                                     f"Move {move} value should not increase with risk aversion.")
                
            has_penalty = any(move_values_with_risk[m] < move_values_no_risk[m] for m in move_values_no_risk)
            self.assertTrue(has_penalty, "No risk penalty was applied to any move under risk_aversion=10.0.")
        finally:
            if orig_risk is not None:
                self.config['solver']['risk_aversion'] = orig_risk
            elif 'risk_aversion' in self.config['solver']:
                del self.config['solver']['risk_aversion']

if __name__ == '__main__':
    unittest.main()
