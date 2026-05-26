# tests/test_engine.py
import unittest
from src import game_engine

class TestEngine(unittest.TestCase):
    def test_1_simple_merge_left(self):
        """Moving left merges [1,1,1,0] into [2,1,0,0], with one level-2 merge score."""
        grid = [
            [1, 1, 1, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board = game_engine.list_to_board(grid)
        new_board, score, valid = game_engine.move_left(board)
        
        self.assertTrue(valid)
        res_grid = game_engine.board_to_list(new_board)
        self.assertEqual(res_grid[0], [2, 1, 0, 0])
        self.assertEqual(score, 1)

    def test_2_double_merge_left(self):
        """Moving left merges [1,1,1,1] into [2,2,0,0], not [3,0,0,0]."""
        grid = [
            [1, 1, 1, 1],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board = game_engine.list_to_board(grid)
        new_board, score, valid = game_engine.move_left(board)
        
        self.assertTrue(valid)
        res_grid = game_engine.board_to_list(new_board)
        self.assertEqual(res_grid[0], [2, 2, 0, 0])
        self.assertEqual(score, 2)

    def test_3_level_11_stone_no_merge(self):
        """Level-11 tiles do not merge."""
        grid = [
            [11, 11, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board = game_engine.list_to_board(grid)
        new_board, score, valid = game_engine.move_left(board)
        
        self.assertFalse(valid)
        self.assertEqual(new_board, board)
        self.assertEqual(score, 0)

    def test_4_invalid_moves_detected(self):
        """Invalid moves are detected and cost no energy (no changes made)."""
        grid = [
            [2, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board = game_engine.list_to_board(grid)
        _, _, valid_left = game_engine.move_left(board)
        _, _, valid_up = game_engine.move_up(board)
        
        self.assertFalse(valid_left)
        self.assertFalse(valid_up)
        
        _, _, valid_down = game_engine.move_down(board)
        _, _, valid_right = game_engine.move_right(board)
        self.assertTrue(valid_down)
        self.assertTrue(valid_right)

    def test_5_x1_spawn_levels(self):
        """x1 spawn events create only levels 1 and 2."""
        board = 0
        outcomes = game_engine.get_spawn_outcomes(board, 'x1')
        self.assertGreater(len(outcomes), 0)
        for prob, nb, score in outcomes:
            grid = game_engine.board_to_list(nb)
            non_zeros = [lvl for row in grid for lvl in row if lvl > 0]
            for lvl in non_zeros:
                self.assertIn(lvl, [1, 2])

    def test_6_x4_spawn_levels(self):
        """x4 spawn events create only levels 3 and 4."""
        board = 0
        outcomes = game_engine.get_spawn_outcomes(board, 'x4')
        self.assertGreater(len(outcomes), 0)
        for prob, nb, score in outcomes:
            grid = game_engine.board_to_list(nb)
            non_zeros = [lvl for row in grid for lvl in row if lvl > 0]
            for lvl in non_zeros:
                self.assertIn(lvl, [3, 4])

    def test_7_spawn_distribution_probabilities(self):
        """Spawn distribution matches configured probabilities."""
        orig_probs = game_engine.config.get('spawn_probabilities', {}).copy()
        try:
            game_engine.config['spawn_probabilities'] = {
                'event_1_low': 0.50,
                'event_2_low': 0.35,
                'event_2_low_1_high': 0.15
            }
            board = 0
            outcomes = game_engine.get_spawn_outcomes(board, 'x1')
            
            sum_prob_1_low = 0.0
            sum_prob_2_low = 0.0
            sum_prob_2_low_1_high = 0.0
            
            for prob, nb, score in outcomes:
                grid = game_engine.board_to_list(nb)
                spawned_levels = [lvl for row in grid for lvl in row if lvl > 0]
                
                if len(spawned_levels) == 1:
                    self.assertEqual(spawned_levels[0], 1)
                    sum_prob_1_low += prob
                elif len(spawned_levels) == 2:
                    self.assertEqual(spawned_levels, [1, 1])
                    sum_prob_2_low += prob
                elif len(spawned_levels) == 3:
                    self.assertEqual(sorted(spawned_levels), [1, 1, 2])
                    sum_prob_2_low_1_high += prob
                    
            self.assertAlmostEqual(sum_prob_1_low, 0.50, places=5)
            self.assertAlmostEqual(sum_prob_2_low, 0.35, places=5)
            self.assertAlmostEqual(sum_prob_2_low_1_high, 0.15, places=5)
        finally:
            game_engine.config['spawn_probabilities'] = orig_probs

if __name__ == '__main__':
    unittest.main()
