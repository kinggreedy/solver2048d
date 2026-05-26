# solver.py
import time
import random
import os
import concurrent.futures
from src.game_engine import (
    board_to_list,
    get_valid_moves,
    apply_move,
    get_spawn_outcomes,
    LEFT, RIGHT, UP, DOWN
)

# Generate 8 symmetric snake templates for board evaluation
BASE_SNAKE = [
    [10000, 5000, 2500, 1250],
    [80, 160, 320, 640],
    [40, 20, 10, 5],
    [0, 1, 2, 3]
]

def rotate_matrix(m):
    return [list(x) for x in zip(*m[::-1])]

def reflect_matrix(m):
    return [row[::-1] for row in m]

def generate_snake_templates():
    templates = []
    curr = [row[:] for row in BASE_SNAKE]
    for _ in range(4):
        templates.append(curr)
        templates.append(reflect_matrix(curr))
        curr = rotate_matrix(curr)
    # Remove duplicates
    unique = []
    for t in templates:
        if t not in unique:
            unique.append(t)
    return unique

SNAKE_TEMPLATES = generate_snake_templates()
HEURISTIC_CACHE = {}

def clear_caches():
    HEURISTIC_CACHE.clear()

def compute_tile_intrinsic_values(config):
    """
    Computes total merge points required to build each tile level.
    V(L) = 2 * V(L-1) + merge_points[L]
    """
    merge_points = config.get('merge_points', {})
    v = [0] * 16
    for L in range(2, 16):
        v[L] = 2 * v[L-1] + merge_points.get(L, 0)
    return v

def get_board_intrinsic_score(board, tile_values):
    """
    Returns the sum of intrinsic values of all tiles currently on the board.
    """
    score = 0.0
    for i in range(16):
        level = (board >> (i * 4)) & 0xF
        score += tile_values[level]
    return score

def evaluate_unreachable(grid, config=None):
    """
    Counts unreachable (no same-level cell in same row/col/neighbors)
    and isolated (no adjacent same-level neighbor) tiles.
    """
    stone_level = 11 if (config is not None and config.get('game', {}).get('level_11_stone', True)) else None
    unreachable_count = 0
    isolated_count = 0
    
    for r in range(4):
        for c in range(4):
            level = grid[r][c]
            if level == 0 or (stone_level is not None and level == stone_level):
                continue
            
            # Check adjacent neighbors
            has_neighbor = False
            for dr, dc in [(-1,0), (1,0), (0,-1), (0,1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < 4 and 0 <= nc < 4:
                    if grid[nr][nc] == level:
                        has_neighbor = True
                        break
            
            # Check same row or column
            has_row_col = False
            for i in range(4):
                if i != c and grid[r][i] == level:
                    has_row_col = True
                if i != r and grid[i][c] == level:
                    has_row_col = True
                    
            if not has_neighbor and not has_row_col:
                unreachable_count += 1
                
            if not has_neighbor:
                isolated_count += 1
                
    return unreachable_count, isolated_count

def evaluate_board(board, config):
    """Core heuristic evaluator for board state using exponential scaling and corner anchoring."""
    grid = board_to_list(board)
    weights = config['heuristics']
    
    # 1. Empty cells
    empty_cells = sum(row.count(0) for row in grid)
    
    # 2. Smoothness using exponential scaling (penalizes adjacent high-value mismatches severely)
    smoothness = 0
    for r in range(4):
        for c in range(4):
            level = grid[r][c]
            if level > 0:
                val = 2 ** level
                if c + 1 < 4 and grid[r][c+1] > 0:
                    smoothness -= abs(val - (2 ** grid[r][c+1]))
                if r + 1 < 4 and grid[r+1][c] > 0:
                    smoothness -= abs(val - (2 ** grid[r+1][c]))
                    
    # 3. Snake score with corner anchoring based on highest tile positions
    max_lvl = 0
    max_positions = []
    for r in range(4):
        for c in range(4):
            if grid[r][c] > max_lvl:
                max_lvl = grid[r][c]
                max_positions = [(r, c)]
            elif grid[r][c] == max_lvl and max_lvl > 0:
                max_positions.append((r, c))
                
    anchored_templates = SNAKE_TEMPLATES
    if max_lvl > 0:
        corners = [(0, 0), (0, 3), (3, 0), (3, 3)]
        max_corners = [pos for pos in max_positions if pos in corners]
        if max_corners:
            # Filter templates where the corner of the max tile has the absolute maximum weight (10000)
            anchored_templates = []
            for t in SNAKE_TEMPLATES:
                for cr, cc in max_corners:
                    if t[cr][cc] == 10000:
                        anchored_templates.append(t)
                        break
            if not anchored_templates:
                anchored_templates = SNAKE_TEMPLATES
                
    snake_score = max(
        sum((2 ** grid[r][c] if grid[r][c] > 0 else 0) * template[r][c] for r in range(4) for c in range(4))
        for template in anchored_templates
    )
    
    # 4. Stone penalty (Level 11 is a stone)
    stone_penalty = 0
    if config.get('game', {}).get('level_11_stone', True):
        for r in range(4):
            for c in range(4):
                if grid[r][c] == 11:
                    # Prefer corners
                    if (r == 0 or r == 3) and (c == 0 or c == 3):
                        pass
                    elif r == 0 or r == 3 or c == 0 or c == 3:
                        stone_penalty -= 50
                    else:
                        stone_penalty -= 200
                    
    # 5. Unreachable and isolated tiles
    unreachable_count, isolated_count = evaluate_unreachable(grid, config)
    
    # 6. High level tile far from max tile corner
    high_tile_penalty = 0
    if max_lvl >= 6:
        for r in range(4):
            for c in range(4):
                lvl = grid[r][c]
                if lvl >= 5 and lvl < max_lvl:
                    min_dist = min(abs(r - mr) + abs(c - mc) for mr, mc in max_positions)
                    if min_dist > 1:
                        high_tile_penalty -= (lvl * 15) * min_dist
                        
    # Combine scores using config weights
    total_score = (
        empty_cells * weights.get('weight_empty', 100.0) +
        smoothness * weights.get('weight_smoothness', 20.0) +
        snake_score * weights.get('weight_monotonicity', 50.0) +
        stone_penalty * (abs(weights.get('weight_stone_penalty', -150.0)) / 150.0) +
        unreachable_count * weights.get('weight_unreachable_penalty', -80.0) +
        high_tile_penalty
    )
    return total_score


def get_heuristic_score(board, config):
    if board in HEURISTIC_CACHE:
        return HEURISTIC_CACHE[board]
    score = evaluate_board(board, config)
    HEURISTIC_CACHE[board] = score
    return score

class CancelToken:
    def __init__(self, cancel_filepath=None):
        self._cancelled = False
        self.cancel_filepath = cancel_filepath
        
    def cancel(self):
        self._cancelled = True
        if self.cancel_filepath:
            try:
                with open(self.cancel_filepath, 'w') as f:
                    pass
            except Exception:
                pass
                
    def is_cancelled(self):
        if self._cancelled:
            return True
        if self.cancel_filepath and os.path.exists(self.cancel_filepath):
            self._cancelled = True
            return True
        return False

# Global process pool executor
_executor = None

def get_executor():
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ProcessPoolExecutor(max_workers=4)
    return _executor

def shutdown_executor():
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None

# Expectimax search implementation
def expectimax_search(board, depth, is_player_turn, mode_name, memo, start_time, max_time_ms, config, spawn_patterns=None, stats=None, time_check_enabled=True, cancel_token=None):
    if stats is not None:
        stats['nodes'] += 1
        
    # Time limit check (enforced with 50% grace period)
    if time_check_enabled and max_time_ms and (time.time() - start_time) * 1000 >= 1.5 * max_time_ms:
        raise TimeoutError()
        
    # Check cancellation token
    if cancel_token and cancel_token.is_cancelled():
        raise TimeoutError()
        
    # Memoization lookup
    memo_key = (board, depth, is_player_turn)
    if memo_key in memo:
        return memo[memo_key]
        
    # Terminal or depth cut-off
    if depth == 0:
        empty_count = 0
        for i in range(16):
            if ((board >> (i * 4)) & 0xF) == 0:
                empty_count += 1
        tile_values = stats.get('tile_values') if stats else None
        if not tile_values:
            tile_values = compute_tile_intrinsic_values(config)
        real_val = get_board_intrinsic_score(board, tile_values)
        return get_heuristic_score(board, config), real_val, empty_count
        
    if is_player_turn:
        valid_moves = get_valid_moves(board)
        if not valid_moves:
            tile_values = stats.get('tile_values') if stats else None
            if not tile_values:
                tile_values = compute_tile_intrinsic_values(config)
            # Game Over state
            return -999999.0, get_board_intrinsic_score(board, tile_values), 0.0
            
        best_score = -float('inf')
        best_real = 0.0
        best_empty = 0.0
        for move in valid_moves:
            next_board, move_score, _ = apply_move(board, move)
            score, real_score, empty = expectimax_search(next_board, depth - 1, False, mode_name, memo, start_time, max_time_ms, config, spawn_patterns, stats, time_check_enabled, cancel_token)
            val = move_score + score
            if val > best_score:
                best_score = val
                best_real = move_score + real_score
                best_empty = empty
        memo[memo_key] = (best_score, best_real, best_empty)
        return best_score, best_real, best_empty
    else:
        # Chance node (spawn events)
        outcomes = get_spawn_outcomes(board, mode_name, spawn_patterns)
        if not outcomes:
            tile_values = stats.get('tile_values') if stats else None
            if not tile_values:
                tile_values = compute_tile_intrinsic_values(config)
            return get_heuristic_score(board, config), get_board_intrinsic_score(board, tile_values), 0.0
            
        expected_score = 0.0
        expected_real = 0.0
        expected_empty = 0.0
        for prob, spawned_board, spawn_score in outcomes:
            score, real_score, empty = expectimax_search(spawned_board, depth - 1, True, mode_name, memo, start_time, max_time_ms, config, spawn_patterns, stats, time_check_enabled, cancel_token)
            expected_score += prob * (spawn_score + score)
            expected_real += prob * (spawn_score + real_score)
            expected_empty += prob * empty
        memo[memo_key] = (expected_score, expected_real, expected_empty)
        return expected_score, expected_real, expected_empty

def get_recoverability(max_level, empty_cells):
    """
    Returns recoverability score between 0.0 (unrecoverable) and 1.0 (perfectly recoverable).
    Low levels (<= 5) have perfect recoverability (1.0).
    High levels (>= 9) have very low recoverability (0.1).
    Intermediate levels scale linearly.
    Board crowding scales recoverability down to 0.0 if empty_cells <= 2.
    """
    if max_level <= 5:
        return 1.0
        
    # Crowding factor
    if empty_cells <= 2:
        empty_factor = 0.0
    elif empty_cells >= 6:
        empty_factor = 1.0
    else:
        empty_factor = (empty_cells - 2) / 4.0
        
    # Level factor
    if max_level >= 9:
        level_factor = 0.1
    else:
        # max_level is 6, 7, or 8
        level_factor = 0.9 - (max_level - 5) * 0.2
        
    return level_factor * empty_factor

def calculate_risk_penalty(board, next_board, mode_name, depth, memo, config, spawn_patterns=None):
    """
    Calculates the probability-weighted risk penalty for a candidate move.
    """
    grid = board_to_list(board)
    max_level = max(max(row) for row in grid)
    if max_level < 6:
        return 0.0
        
    corners = [(0, 0), (0, 3), (3, 0), (3, 3)]
    original_max_corners = [(r, c) for r, c in corners if grid[r][c] == max_level]
    if not original_max_corners:
        return 0.0
        
    outcomes = get_spawn_outcomes(next_board, mode_name, spawn_patterns)
    if not outcomes:
        return 0.0
        
    total_penalty = 0.0
    risk_aversion = config.get('solver', {}).get('risk_aversion', 2.0)
    
    # corner_value is based on max_level tile value and heuristic weights
    weight_mono = config.get('heuristics', {}).get('weight_monotonicity', 50.0)
    corner_value = (2 ** max_level) * 10000.0 * weight_mono
    
    for prob_o, spawned_board, spawn_score in outcomes:
        valid_moves = get_valid_moves(spawned_board)
        if not valid_moves:
            best_resp_board = spawned_board
        else:
            best_resp_board = None
            best_val = -float('inf')
            for move in valid_moves:
                resp_next_board, move_score, _ = apply_move(spawned_board, move)
                memo_key = (resp_next_board, depth - 3, False)
                memo_val = memo.get(memo_key)
                if memo_val is not None:
                    val = move_score + memo_val[0]
                else:
                    val = move_score + get_heuristic_score(resp_next_board, config)
                if val > best_val:
                    best_val = val
                    best_resp_board = resp_next_board
                    
        if best_resp_board is None:
            best_resp_board = spawned_board
            
        resp_grid = board_to_list(best_resp_board)
        empty_cells = sum(row.count(0) for row in resp_grid)
        
        max_level_resp = max(max(row) for row in resp_grid)
        if max_level_resp > max_level:
            anchor_lost = False
        else:
            anchor_lost = any(resp_grid[r][c] < max_level for r, c in original_max_corners)
            
        if anchor_lost:
            recoverability = get_recoverability(max_level, empty_cells)
            penalty = prob_o * corner_value * (1.0 - recoverability) * risk_aversion
            total_penalty += penalty
            
    return total_penalty

def get_dynamic_depth(board):
    """Adjusts search depth based on number of empty cells for speed/accuracy trade-off."""
    empty_count = 0
    for i in range(16):
        if ((board >> (i * 4)) & 0xF) == 0:
            empty_count += 1
            
    if empty_count >= 8:
        return 2  # Very empty, fast check
    elif empty_count >= 4:
        return 3  # Normal depth
    else:
        return 4  # Full board, deeper analysis needed

def get_best_move(board, mode_name, config, spawn_patterns=None, override_depth=None, override_time_ms=None, cancel_token=None, on_depth_complete=None):
    """Finds best move using iterative deepening expectimax search.
    
    on_depth_complete: optional callable(best_move, best_real, best_empty, move_values, move_real_values, depth, nodes)
                       called after each successfully completed depth >= min_depth.
    """
    valid_moves = get_valid_moves(board)
    if not valid_moves:
        return None, 0.0, 0.0, {}, {}, 0, 0  # 7 values: move, real, empty, heuristic_vals, real_vals, depth, nodes
        
    max_depth = override_depth if override_depth is not None else config['solver'].get('expectimax_depth', 3)
    max_time = override_time_ms if override_time_ms is not None else config['solver'].get('max_time_ms', 1000)
    
    target_limit = 8  # Hard ceiling on iterative deepening depth
    
    if max_depth == "dynamic":
        if max_time:
            # Time-constrained: use dynamic depth as a soft guide (time will cut us off anyway)
            max_depth = get_dynamic_depth(board)
        else:
            # Unlimited time: run to target_limit — partial results keep the UI updated
            max_depth = target_limit
    else:
        max_depth = int(max_depth)
    
    start_time = time.time()
    memo = {}
    
    tile_values = compute_tile_intrinsic_values(config)
    stats = {
        'nodes': 0,
        'tile_values': tile_values
    }
    
    best_move = None
    best_score = -float('inf')
    best_real = 0.0
    best_empty = 0.0
    move_values = {}       # heuristic ranking scores (used for move ordering only)
    move_real_values = {}  # real expected scores (merge + spawn points, used for display)
    completed_depth = 0
    
    # min_depth from config or default 2
    min_depth = config.get('solver', {}).get('min_depth', 2)
    
    for d in range(1, target_limit + 1):
        if cancel_token and cancel_token.is_cancelled():
            break
            
        elapsed = (time.time() - start_time) * 1000
        # If we have a time limit, check if we exceeded it BEFORE starting this iteration.
        # Only check this if we have completed the min_depth search.
        if d > min_depth and max_time and elapsed >= max_time:
            break
            
        try:
            current_best_move = None
            current_best_score = -float('inf')
            current_best_real = 0.0
            current_best_empty = 0.0
            current_move_values = {}       # heuristic ranking scores
            current_move_real_values = {}  # real EV scores
            
            # Enforce time check always to strictly respect the time limit + 50% buffer cap
            time_check_enabled = True
            
            for move in valid_moves:
                next_board, move_score, _ = apply_move(board, move)
                # Recursively search
                score, real, empty = expectimax_search(
                    next_board, d - 1, False, mode_name, memo, 
                    start_time, max_time, config, spawn_patterns, stats, time_check_enabled, cancel_token
                )
                val = move_score + score
                real_val = move_score + real
                
                if d >= 3:
                    penalty = calculate_risk_penalty(board, next_board, mode_name, d, memo, config, spawn_patterns)
                    val -= penalty
                    
                current_move_values[move] = val
                current_move_real_values[move] = real_val
                if val > current_best_score:
                    current_best_score = val
                    current_best_real = real_val
                    current_best_empty = empty
                    current_best_move = move
            
            # Completed depth d successfully!
            best_move = current_best_move
            best_score = current_best_score
            best_real = current_best_real
            best_empty = current_best_empty
            move_values = current_move_values
            move_real_values = current_move_real_values
            completed_depth = d
            
            # Fire progress callback so callers can show live results.
            # We emit from depth 2 onward — depth 1 is too shallow to be meaningful.
            if on_depth_complete and d >= 2 and best_move is not None:
                try:
                    on_depth_complete(
                        best_move, best_real, best_empty,
                        move_values, move_real_values, d, stats['nodes']
                    )
                except Exception:
                    pass  # Never let callback errors break the solver
            
            # If we are in unlimited time mode, respect the depth limit.
            # Otherwise, let the time budget drive iterative deepening.
            if not max_time and d >= max_depth:
                break
                
        except TimeoutError:
            # Timeout during iteration d, discard incomplete depth d results and break
            break
            
    # Fallback if even depth 1 wasn't completed (should be impossible, but as a safety)
    if completed_depth == 0:
        if cancel_token and cancel_token.is_cancelled():
            return None, 0.0, 0.0, {}, {}, 0, stats['nodes']
            
        completed_depth = 1
        for move in valid_moves:
            next_board, move_score, _ = apply_move(board, move)
            try:
                score, real, empty = expectimax_search(
                    next_board, 0, False, mode_name, memo, 
                    start_time, None, config, spawn_patterns, stats, False, cancel_token
                )
                val = move_score + score
                real_val = move_score + real
                move_values[move] = val
                move_real_values[move] = real_val
                if val > best_score:
                    best_score = val
                    best_real = real_val
                    best_empty = empty
                    best_move = move
            except TimeoutError:
                break
                
    return best_move, best_real, best_empty, move_values, move_real_values, completed_depth, stats['nodes']

# Monte Carlo Rollout Fallback
def select_rollout_move(board, config):
    """Rollout policy: pick move that maximizes immediate heuristic score."""
    valid_moves = get_valid_moves(board)
    if not valid_moves:
        return None
    best_move = None
    best_score = -float('inf')
    for m in valid_moves:
        nb, score, _ = apply_move(board, m)
        h_score = score + get_heuristic_score(nb, config)
        if h_score > best_score:
            best_score = h_score
            best_move = m
    return best_move

def run_mc_rollout(board, mode_name, depth_limit, config):
    """Runs a single rollout simulation from a given board state."""
    curr_board = board
    accumulated_score = 0.0
    for d in range(depth_limit):
        move = select_rollout_move(curr_board, config)
        if move is None:
            break
        curr_board, move_score, _ = apply_move(curr_board, move)
        accumulated_score += move_score
        
        # Spawn randomly
        outcomes = get_spawn_outcomes(curr_board, mode_name)
        if not outcomes:
            break
        # Sample one outcome
        probs = [x[0] for x in outcomes]
        outcome = random.choices(outcomes, weights=probs, k=1)[0]
        curr_board = outcome[1]
        accumulated_score += outcome[2]
        
    return accumulated_score + get_heuristic_score(curr_board, config)

def get_best_move_mc(board, mode_name, config):
    """Monte Carlo rollout evaluator for tie-breaking/verification."""
    valid_moves = get_valid_moves(board)
    if not valid_moves:
        return None, 0.0, {}
        
    rollouts_count = config['solver'].get('mc_rollouts', 100)
    rollout_depth = config['solver'].get('mc_depth', 8)
    
    move_scores = {}
    for move in valid_moves:
        next_board, move_score, _ = apply_move(board, move)
        total_score = 0.0
        
        for _ in range(rollouts_count):
            total_score += run_mc_rollout(next_board, mode_name, rollout_depth, config)
            
        move_scores[move] = move_score + (total_score / rollouts_count)
        
    best_move = max(move_scores, key=move_scores.get)
    return best_move, move_scores[best_move], move_scores

def _build_eval_dict(results, config):
    """
    Builds an evaluation dict from a results mapping {mode: result_or_None}.
    Used for both partial (streaming) and final results to keep logic in one place.
    """
    best_overall_mode = None
    best_overall_move = None
    best_overall_val_per_energy = -float('inf')
    survival_score = 0.0
    
    for mode, res in results.items():
        if res is None:
            continue
        ev_per_energy = res['ev_per_energy']
        if ev_per_energy > best_overall_val_per_energy:
            best_overall_val_per_energy = ev_per_energy
            best_overall_mode = mode
            best_overall_move = res['best_move']
            survival_score = (res['expected_empty'] / 16.0) * 100.0

    direct_conv = config['decision']['direct_conversion_value_per_energy']
    fresh_baseline = config['decision']['fresh_game_baseline_value_per_energy']
    has_any_move = any(res is not None for res in results.values())

    if not has_any_move:
        decision = "GAME_OVER"
    elif best_overall_val_per_energy < direct_conv:
        decision = "STOP_AND_CONVERT"
    elif best_overall_val_per_energy < fresh_baseline:
        decision = "RESTART_GAME"
    else:
        decision = "CONTINUE"

    rec_results = results.get(best_overall_mode) if best_overall_mode else None
    completed_depth = rec_results['completed_depth'] if rec_results else 0
    node_count = rec_results['node_count'] if rec_results else 0

    return {
        'best_mode': best_overall_mode,
        'best_move': best_overall_move,
        'best_val_per_energy': best_overall_val_per_energy,
        'survival_score': survival_score,
        'decision': decision,
        'results': results,
        'completed_depth': completed_depth,
        'node_count': node_count,
    }

def evaluate_board_options(board, config, enabled_modes=['x1', 'x4'], empirical_patterns=None, override_depth=None, override_time_ms=None, cancel_token=None, on_progress=None):
    """
    Evaluates current board for all enabled modes.
    Returns recommendations and metrics.
    
    on_progress: optional callable(evaluation_dict, elapsed_ms) — fired whenever a better
                 partial result is available (after each depth in single-mode, or after each
                 mode completes in multi-mode parallel execution).
    """
    clear_caches()
    results = {}
    start_time = time.time()
    
    # Static fallback for survival score if no moves exist
    empty_cells = 0
    for i in range(16):
        if ((board >> (i * 4)) & 0xF) == 0:
            empty_cells += 1

    # Determine effective time limit so we can decide parallel vs sequential
    effective_time_ms = override_time_ms if override_time_ms is not None else config['solver'].get('max_time_ms', 1000)

    # Strategy:
    #  - Sequential: single mode, OR unlimited time
    #    Reason: per-depth callbacks work; no process overhead; unlimited mode benefits
    #    from streaming partial results more than from parallel throughput.
    #  - Parallel (ProcessPoolExecutor): multiple modes AND time-constrained
    #    Reason: running modes in parallel maximises search within the time budget.
    use_parallel = len(enabled_modes) > 1 and bool(effective_time_ms)

    if not use_parallel:
        # Sequential path — iterate over modes one by one, streaming per-depth updates.
        for mode in enabled_modes:
            if cancel_token and cancel_token.is_cancelled():
                break
            energy_cost = config['modes'][mode]['energy_cost']
            mode_patterns = empirical_patterns.get(mode) if empirical_patterns else None
            if mode_patterns:
                mode_patterns = {pat: prob for pat, prob in mode_patterns.items() if pat != '_sample_size'}

            def _on_depth_complete(bm, br, be, mv, mrv, depth, nc, _mode=mode, _ec=energy_cost):
                """Fires on_progress merging already-finished modes + this mode's partial."""
                if on_progress is None or bm is None:
                    return
                ep = br / _ec
                # Include all fully-completed modes already in results
                current_partial = {m: r for m, r in results.items()}
                current_partial[_mode] = {
                    'best_move': bm, 'ev': br, 'ev_per_energy': ep,
                    'expected_empty': be, 'move_values': mv, 'move_real_values': mrv,
                    'completed_depth': depth, 'node_count': nc,
                }
                partial_eval = _build_eval_dict(current_partial, config)
                partial_eval['is_partial'] = True
                elapsed = (time.time() - start_time) * 1000
                try:
                    on_progress(partial_eval, elapsed)
                except Exception:
                    pass

            best_move, ev, expected_empty, move_values, move_real_values, completed_depth, node_count = get_best_move(
                board, mode, config, mode_patterns, override_depth, override_time_ms, cancel_token,
                on_depth_complete=_on_depth_complete if on_progress else None
            )

            if best_move is not None:
                ev_per_energy = ev / energy_cost
                results[mode] = {
                    'best_move': best_move,
                    'ev': ev,
                    'ev_per_energy': ev_per_energy,
                    'expected_empty': expected_empty,
                    'move_values': move_values,
                    'move_real_values': move_real_values,
                    'completed_depth': completed_depth,
                    'node_count': node_count,
                }
            else:
                results[mode] = None
    else:
        # Run in parallel using the global ProcessPoolExecutor.
        # Emit a partial result each time a mode's future completes.
        executor = get_executor()
        futures = {}
        
        for mode in enabled_modes:
            mode_patterns = empirical_patterns.get(mode) if empirical_patterns else None
            if mode_patterns:
                mode_patterns = {pat: prob for pat, prob in mode_patterns.items() if pat != '_sample_size'}
                
            future = executor.submit(
                get_best_move,
                board, mode, config, mode_patterns, override_depth, override_time_ms, cancel_token
                # Note: on_depth_complete cannot cross process boundaries;
                # we emit per-mode partial results below instead.
            )
            futures[future] = mode
            
        completed_results = {}
        for future in concurrent.futures.as_completed(futures):
            mode = futures[future]
            try:
                completed_results[mode] = future.result()
            except Exception:
                # Fallback if task fails/aborts
                completed_results[mode] = (None, 0.0, 0.0, {}, {}, 0, 0)

            # Build partial result from all modes completed so far and emit progress
            if on_progress is not None:
                partial_results = {}
                for m, res_tuple in completed_results.items():
                    ec = config['modes'][m]['energy_cost']
                    bm, br, be, mv, mrv, d, nc = res_tuple
                    if bm is not None:
                        partial_results[m] = {
                            'best_move': bm, 'ev': br, 'ev_per_energy': br / ec,
                            'expected_empty': be, 'move_values': mv, 'move_real_values': mrv,
                            'completed_depth': d, 'node_count': nc,
                        }
                    else:
                        partial_results[m] = None
                # Only emit if there's at least one valid result
                if any(v is not None for v in partial_results.values()):
                    partial_eval = _build_eval_dict(partial_results, config)
                    partial_eval['is_partial'] = True
                    elapsed = (time.time() - start_time) * 1000
                    try:
                        on_progress(partial_eval, elapsed)
                    except Exception:
                        pass
                
        for mode in enabled_modes:
            energy_cost = config['modes'][mode]['energy_cost']
            best_move, ev, expected_empty, move_values, move_real_values, completed_depth, node_count = completed_results.get(
                mode, (None, 0.0, 0.0, {}, {}, 0, 0)
            )
            
            if best_move is not None:
                ev_per_energy = ev / energy_cost
                results[mode] = {
                    'best_move': best_move,
                    'ev': ev,
                    'ev_per_energy': ev_per_energy,
                    'expected_empty': expected_empty,
                    'move_values': move_values,           # heuristic ranking scores
                    'move_real_values': move_real_values,  # real expected points per move
                    'completed_depth': completed_depth,
                    'node_count': node_count
                }
            else:
                results[mode] = None
        
    # Build and return the final (non-partial) evaluation dict
    final_eval = _build_eval_dict(results, config)
    return final_eval

def explain_move(board, move, config):
    """Generates user-friendly explanations for a recommended move."""
    reasons = []
    grid = board_to_list(board)
    next_board, score, _ = apply_move(board, move)
    next_grid = board_to_list(next_board)
    
    # 1. Merge detection
    if score > 0:
        reasons.append(f"Merges adjacent identical tiles for +{score} points.")
        
    # 2. Space creation
    curr_empty = sum(row.count(0) for row in grid)
    next_empty = sum(row.count(0) for row in next_grid)
    if next_empty > curr_empty:
        reasons.append(f"Frees up {next_empty - curr_empty} cell(s) for a more open board.")
        
    # 3. Corner / snake chain stability
    max_lvl = 0
    max_positions = []
    for r in range(4):
        for c in range(4):
            if grid[r][c] > max_lvl:
                max_lvl = grid[r][c]
                max_positions = [(r, c)]
            elif grid[r][c] == max_lvl and max_lvl > 0:
                max_positions.append((r, c))
                
    if max_lvl > 0:
        # Check if max tile is in a corner
        is_in_corner = any((mr in [0, 3] and mc in [0, 3]) for mr, mc in max_positions)
        if is_in_corner:
            next_max_lvl = 0
            next_max_pos = []
            for r in range(4):
                for c in range(4):
                    if next_grid[r][c] > next_max_lvl:
                        next_max_lvl = next_grid[r][c]
                        next_max_pos = [(r, c)]
                    elif next_grid[r][c] == next_max_lvl and next_max_lvl > 0:
                        next_max_pos.append((r, c))
            next_in_corner = any((mr in [0, 3] and mc in [0, 3]) for mr, mc in next_max_pos)
            if next_in_corner:
                reasons.append("Maintains structural stability by keeping highest tiles in corners.")
            else:
                reasons.append("WARNING: Shifting high tiles away from corners!")
                
    # 4. Stone control
    curr_stones = sum(row.count(11) for row in grid)
    next_stones = sum(row.count(11) for row in next_grid)
    if next_stones > curr_stones:
        reasons.append("Creates a new level-11 stone tile (+200 points).")
    
    # 5. Check if stones are isolated or interior
    for r in range(4):
        for c in range(4):
            if next_grid[r][c] == 11 and not ((r == 0 or r == 3) and (c == 0 or c == 3)):
                if not (r == 0 or r == 3 or c == 0 or c == 3):
                    reasons.append("CAUTION: Moves level-11 stone to the interior grid.")
                    
    if not reasons:
        reasons.append("Calculates highest expected score per energy across searched paths.")
        
    return reasons


def solver_worker_entry(board, mode, config, spawn_patterns, override_depth, override_time_ms, cancel_filepath, queue):
    """
    Entry point for a solver process running expectimax for a single mode.
    Communicates progress events back to the parent process via queue.
    """
    import time
    
    # Map direction constants to standard string names for IPC compatibility
    DIR_MAP_TO_STR = {
        0: "LEFT",
        1: "RIGHT",
        2: "UP",
        3: "DOWN"
    }
    
    cancel_token = CancelToken(cancel_filepath)
    start_time = time.time()
    
    # Extract mode-specific spawn patterns
    mode_patterns = spawn_patterns.get(mode) if spawn_patterns else None
    if mode_patterns:
        mode_patterns = {pat: prob for pat, prob in mode_patterns.items() if pat != '_sample_size'}
        
    energy_cost = config['modes'][mode]['energy_cost']
    
    def _on_depth_complete(best_move, best_real, best_empty, move_values, move_real_values, depth, nodes):
        if cancel_token.is_cancelled():
            return
            
        elapsed_ms = (time.time() - start_time) * 1000
        best_move_str = DIR_MAP_TO_STR.get(best_move) if best_move is not None else None
        heuristic_score = move_values.get(best_move, 0.0) if best_move is not None else 0.0
        
        event = {
            "mode": mode,
            "depth": depth,
            "best_move": best_move_str,
            "real_ev": best_real,
            "ev_per_energy": best_real / energy_cost,
            "heuristic_score": heuristic_score,
            "nodes": nodes,
            "elapsed_ms": elapsed_ms,
            "is_final": False,
            # Extra fields for GUI
            "expected_empty": best_empty,
            "move_values": {DIR_MAP_TO_STR[m]: v for m, v in move_values.items()},
            "move_real_values": {DIR_MAP_TO_STR[m]: v for m, v in move_real_values.items()}
        }
        queue.put(event)
        
    try:
        best_move, ev, expected_empty, move_values, move_real_values, completed_depth, node_count = get_best_move(
            board, mode, config, mode_patterns, override_depth, override_time_ms, cancel_token,
            on_depth_complete=_on_depth_complete
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        best_move_str = DIR_MAP_TO_STR.get(best_move) if best_move is not None else None
        heuristic_score = move_values.get(best_move, 0.0) if best_move is not None else 0.0
        
        event = {
            "mode": mode,
            "depth": completed_depth,
            "best_move": best_move_str,
            "real_ev": ev,
            "ev_per_energy": ev / energy_cost if best_move is not None else 0.0,
            "heuristic_score": heuristic_score,
            "nodes": node_count,
            "elapsed_ms": elapsed_ms,
            "is_final": True,
            # Extra fields for GUI
            "expected_empty": expected_empty,
            "move_values": {DIR_MAP_TO_STR[m]: v for m, v in move_values.items()},
            "move_real_values": {DIR_MAP_TO_STR[m]: v for m, v in move_real_values.items()}
        }
        queue.put(event)
        
        # Let the process exit naturally as requested by the user, but sleep slightly 
        # to ensure that the queue's background thread can flush the final message.
        time.sleep(0.1)
        
    except Exception as e:
        import traceback
        print(f"Error in solver process {mode}:\n{traceback.format_exc()}")


