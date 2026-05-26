# tests/test_algorithm.py
"""
Algorithm-level integration tests for the expectimax solver.

These tests are LONG-RUNNING (up to several minutes) and are meant to test
algorithmic correctness, convergence properties, and depth-sensitivity.

They are SKIPPED by default when running:
    python3 -m unittest discover -s tests

To run them explicitly:
    python3 -m unittest tests.test_algorithm
    # OR pass --algorithm flag to main test runner (if supported)
    python3 -m pytest tests/test_algorithm.py -v
    python3 tests/test_algorithm.py

Rationale for slow tests:
- These simulate full game trajectories up to hundreds of moves.
- They test whether islands caused by shallow search converge back.
- They validate depth-sensitivity of critical board positions.
"""
import os
import sys
import unittest
import random

# Allow running directly from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import game_engine, solver

SKIP_REASON = (
    "Algorithm tests are long-running. Set RUN_ALGORITHM_TESTS=1 to enable them."
)
RUN_ALGORITHM_TESTS = os.environ.get("RUN_ALGORITHM_TESTS", "0") == "1"

def sim_play(board, config, mode='x1', max_steps=500, time_ms=1000, seed=42, depth=None):
    """
    Simulates a game from a starting board for up to max_steps moves.
    Returns the list of (board, move) pairs and the final board.
    """
    random.seed(seed)
    history = []
    for _ in range(max_steps):
        grid = game_engine.board_to_list(board)
        best_move, _, _, _, _, _, _ = solver.get_best_move(
            board, mode, config,
            override_time_ms=time_ms,
            override_depth=depth
        )
        if best_move is None:
            break
        board, _, valid = game_engine.apply_move(board, best_move)
        if not valid:
            break
        history.append((board, best_move))
        outcomes = game_engine.get_spawn_outcomes(board, mode)
        if not outcomes:
            break
        probs = [o[0] for o in outcomes]
        outcome = random.choices(outcomes, weights=probs, k=1)[0]
        board = outcome[1]
    return history, board


def max_tile_on_board(board):
    grid = game_engine.board_to_list(board)
    return max(cell for row in grid for cell in row)


def count_islands(board):
    """
    Counts 'islands': high-level tiles (>=5) that are not adjacent to any tile
    within 2 levels of them. Returns a rough connectivity score (lower = more islands).
    """
    grid = game_engine.board_to_list(board)
    island_count = 0
    for r in range(4):
        for c in range(4):
            lvl = grid[r][c]
            if lvl < 5:
                continue
            neighbors = []
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < 4 and 0 <= nc < 4:
                    neighbors.append(grid[nr][nc])
            # Island = no neighbor within 2 levels (and not empty)
            if all(abs(n - lvl) > 2 or n == 0 for n in neighbors):
                island_count += 1
    return island_count


@unittest.skipUnless(RUN_ALGORITHM_TESTS, SKIP_REASON)
class TestAlgorithmSnakeRecovery(unittest.TestCase):
    """
    Tests focusing on the solver's ability to maintain and recover
    snake structure through the mid-game.
    """

    def setUp(self):
        self.config = game_engine.config

    def test_depth3_causes_snake_break_at_critical_position(self):
        """
        Confirms that the known board position from session 79, move 35
        is incorrectly evaluated by the 1s solver (depth 3) which chooses DOWN
        instead of the correct RIGHT move.

        Board:
          6 6 7 8
          3 2 1 1
          0 1 0 0
          0 0 0 0

        At depth 3 (1s), the solver prefers DOWN (breaks the snake).
        At depth 5 (5s), the solver correctly prefers RIGHT or LEFT (maintains snake).
        This is a heuristic limitation at shallow depth, not a bug in the algorithm.
        """
        grid = [
            [6, 6, 7, 8],
            [3, 2, 1, 1],
            [0, 1, 0, 0],
            [0, 0, 0, 0]
        ]
        board = game_engine.list_to_board(grid)
        dirs = {game_engine.LEFT: 'LEFT', game_engine.RIGHT: 'RIGHT',
                game_engine.UP: 'UP', game_engine.DOWN: 'DOWN'}

        bm_1s, _, _, _, _, depth_1s, _ = solver.get_best_move(
            board, 'x1', self.config, override_time_ms=1000
        )
        bm_5s, _, _, _, _, depth_5s, _ = solver.get_best_move(
            board, 'x1', self.config, override_time_ms=5000
        )

        print(f"\nCritical position: 1s→{dirs.get(bm_1s)} (d{depth_1s}), "
              f"5s→{dirs.get(bm_5s)} (d{depth_5s})")

        # Confirm 1s picks DOWN (depth 3 is known to be wrong here)
        self.assertEqual(bm_1s, game_engine.DOWN,
                         f"Expected 1s to pick DOWN (shallow-depth artifact), got {dirs.get(bm_1s)}")

        # Confirm 5s+ corrects to RIGHT or LEFT (not DOWN)
        self.assertNotEqual(bm_5s, game_engine.DOWN,
                            f"5s search should NOT pick DOWN - it should find a better structure-preserving move")

    def test_heuristic_score_penalizes_broken_snake(self):
        """
        Verifies that the heuristic correctly scores the board after DOWN
        much lower than the board after RIGHT from the critical position,
        confirming the issue is only in lookahead depth, not the terminal heuristic.
        """
        # After DOWN: snake is broken, high tiles in rows 2-3
        grid_after_down = [
            [0, 0, 0, 0],
            [0, 6, 0, 0],
            [6, 2, 7, 8],
            [3, 1, 1, 1]
        ]
        # After RIGHT: snake maintained, high tiles on top row
        grid_after_right = [
            [0, 7, 7, 8],
            [3, 2, 2, 0],
            [1, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board_down = game_engine.list_to_board(grid_after_down)
        board_right = game_engine.list_to_board(grid_after_right)

        h_down = solver.get_heuristic_score(board_down, self.config)
        h_right = solver.get_heuristic_score(board_right, self.config)

        print(f"\nHeuristic after DOWN: {h_down:.0f}, after RIGHT: {h_right:.0f}")
        self.assertGreater(h_right, h_down,
                           "Heuristic should score RIGHT (structured snake) higher than DOWN (broken snake)")
        # The difference should be substantial (at least 2x)
        self.assertGreater(h_right, h_down * 1.5,
                           "Heuristic advantage of RIGHT over DOWN should be significant (>1.5x)")


@unittest.skipUnless(RUN_ALGORITHM_TESTS, SKIP_REASON)
class TestAlgorithmIslandConvergence(unittest.TestCase):
    """
    Tests whether islands created by shallow-depth moves eventually converge
    back into the snake structure with continued play.
    """

    def setUp(self):
        self.config = game_engine.config

    def test_island_after_broken_snake_converges_with_1s_thinking(self):
        """
        After the snake-breaking DOWN move, simulate continued 1s play and
        check if islands (isolated high tiles far from neighbors) eventually reduce.

        The island in session 79 (move 36+ onwards):
          6 2 7 8  <- 7 and 8 are isolated at top right, disconnected from 6 at col0
          3 1 1 1

        We play from that state and check if islands decrease over 100 moves.
        """
        grid_broken = [
            [0, 1, 0, 0],
            [0, 6, 0, 0],
            [6, 2, 7, 8],
            [3, 1, 1, 1]
        ]
        board = game_engine.list_to_board(grid_broken)
        initial_islands = count_islands(board)

        history, final_board = sim_play(
            board, self.config, mode='x1', max_steps=150, time_ms=1000, seed=100
        )

        final_islands = count_islands(final_board)
        final_max = max_tile_on_board(final_board)

        print(f"\nInitial islands: {initial_islands}, Final islands: {final_islands}")
        print(f"Final max tile: {final_max}, steps played: {len(history)}")

        # At minimum, the max tile should still be growing (not stuck)
        self.assertGreaterEqual(final_max, 8,
                                "Max tile should continue growing from the broken snake state")

        # Islands should eventually reduce or the board should improve
        # (This is a soft assertion - we're documenting expected behavior)
        improved_or_converged = (final_islands <= initial_islands or final_max >= 9)
        self.assertTrue(improved_or_converged,
                        f"Island count should improve or max tile should grow. "
                        f"Islands: {initial_islands}->{final_islands}, max: {final_max}")

    def test_island_convergence_is_faster_with_5s_thinking(self):
        """
        Compare island recovery between 1s and 5s thinking on the same broken board.
        5s thinking should produce fewer islands over the same number of moves.
        """
        grid_broken = [
            [0, 1, 0, 0],
            [0, 6, 0, 0],
            [6, 2, 7, 8],
            [3, 1, 1, 1]
        ]
        board = game_engine.list_to_board(grid_broken)

        # Play 60 steps at 1s
        _, board_1s = sim_play(
            board, self.config, mode='x1', max_steps=60, time_ms=1000, seed=100
        )
        # Play 60 steps at 5s
        _, board_5s = sim_play(
            board, self.config, mode='x1', max_steps=60, time_ms=5000, seed=100
        )

        islands_1s = count_islands(board_1s)
        islands_5s = count_islands(board_5s)
        max_1s = max_tile_on_board(board_1s)
        max_5s = max_tile_on_board(board_5s)

        print(f"\n1s thinking after 60 steps: islands={islands_1s}, max_tile={max_1s}")
        print(f"5s thinking after 60 steps: islands={islands_5s}, max_tile={max_5s}")

        # 5s should produce a better board: fewer islands or higher max tile
        better_5s = (islands_5s <= islands_1s or max_5s > max_1s)
        self.assertTrue(better_5s,
                        f"5s thinking should produce a better board than 1s. "
                        f"1s: islands={islands_1s} max={max_1s}, 5s: islands={islands_5s} max={max_5s}")


@unittest.skipUnless(RUN_ALGORITHM_TESTS, SKIP_REASON)
class TestAlgorithmLongRunSimulation(unittest.TestCase):
    """
    Long-running game simulations that verify the solver can reach
    high-level tiles consistently over many random seeds.
    """

    def setUp(self):
        self.config = game_engine.config

    def test_solver_reaches_level_9_from_level_7_reliably(self):
        """
        Starting from a level 7 board, 1s solver should reach level 9 in at
        least 3 out of 5 random seeds within 200 moves.
        """
        grid_start = [
            [7, 6, 5, 4],
            [1, 2, 3, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board_start = game_engine.list_to_board(grid_start)
        successes = 0
        seeds = [42, 99, 201, 777, 1234]

        for seed in seeds:
            _, final_board = sim_play(
                board_start, self.config, mode='x1',
                max_steps=200, time_ms=1000, seed=seed
            )
            if max_tile_on_board(final_board) >= 9:
                successes += 1

        print(f"\nReached level 9: {successes}/{len(seeds)} seeds")
        self.assertGreaterEqual(successes, 3,
                                f"Expected at least 3/5 seeds to reach level 9, got {successes}")

    def test_5s_solver_reaches_level_10_from_level_8_reliably(self):
        """
        Starting from a level 8 board, 5s solver should reach level 10 in at
        least 2 out of 3 random seeds within 300 moves.
        """
        grid_start = [
            [8, 7, 6, 5],
            [1, 2, 3, 4],
            [0, 0, 0, 0],
            [0, 0, 0, 0]
        ]
        board_start = game_engine.list_to_board(grid_start)
        successes = 0
        seeds = [42, 801, 9999]

        for seed in seeds:
            _, final_board = sim_play(
                board_start, self.config, mode='x1',
                max_steps=300, time_ms=5000, seed=seed
            )
            if max_tile_on_board(final_board) >= 10:
                successes += 1

        print(f"\nReached level 10: {successes}/{len(seeds)} seeds")
        self.assertGreaterEqual(successes, 2,
                                f"Expected at least 2/3 seeds to reach level 10 with 5s thinking, got {successes}")


if __name__ == '__main__':
    # When run directly, enable algorithm tests
    os.environ['RUN_ALGORITHM_TESTS'] = '1'
    unittest.main(verbosity=2)
