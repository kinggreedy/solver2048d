# game_engine.py
import os
import yaml
import itertools

# Constants for directions
LEFT = 0
RIGHT = 1
UP = 2
DOWN = 3

# Tables for precomputed row transitions
# Each row of 4 cells is represented as a 16-bit integer (4 bits per cell)
ROW_LEFT_TABLE = [0] * 65536
ROW_SCORE_TABLE = [0] * 65536
ROW_VALID_TABLE = [False] * 65536
ROW_REVERSE_TABLE = [0] * 65536

from src.paths import CONFIG_PATH

def load_config(config_path=None):
    """Loads configuration from yaml file."""
    if config_path is None:
        config_path = CONFIG_PATH
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

# Load configuration globally for engine setup
config = load_config(CONFIG_PATH)

def init_tables():
    """Precomputes lookup tables for fast 2048 operations."""
    merge_points = config['merge_points']
    
    stone_level = 11 if config.get('game', {}).get('level_11_stone', True) else None
    
    for row_key in range(65536):
        # Decode row key (16-bit) to 4 cells (4 bits each)
        # Low bits map to leftmost cell, high bits to rightmost cell
        a = row_key & 0xF
        b = (row_key >> 4) & 0xF
        c = (row_key >> 8) & 0xF
        d = (row_key >> 12) & 0xF
        
        # Precompute reverse table
        ROW_REVERSE_TABLE[row_key] = ((row_key & 0x000F) << 12) | ((row_key & 0x00F0) << 4) | ((row_key & 0x0F00) >> 4) | ((row_key & 0xF000) >> 12)
        
        # Compute left merge
        non_zeros = [x for x in (a, b, c, d) if x > 0]
        new_row = []
        score = 0
        i = 0
        while i < len(non_zeros):
            is_stone = (stone_level is not None and non_zeros[i] == stone_level)
            if i + 1 < len(non_zeros) and non_zeros[i] == non_zeros[i+1] and not is_stone:
                res_level = non_zeros[i] + 1
                if res_level > 15:
                    res_level = 15
                new_row.append(res_level)
                score += merge_points.get(res_level, 0)
                i += 2
            else:
                new_row.append(non_zeros[i])
                i += 1
                
        while len(new_row) < 4:
            new_row.append(0)
            
        new_key = new_row[0] | (new_row[1] << 4) | (new_row[2] << 8) | (new_row[3] << 12)
        ROW_LEFT_TABLE[row_key] = new_key
        ROW_SCORE_TABLE[row_key] = score
        ROW_VALID_TABLE[row_key] = (new_key != row_key)


# Initialize the tables immediately on import
init_tables()

# Bitboard helpers
def board_to_list(board):
    """Converts 64-bit integer board to a 4x4 list of integers."""
    grid = []
    for r in range(4):
        row = []
        for c in range(4):
            cell_idx = r * 4 + c
            level = (board >> (cell_idx * 4)) & 0xF
            row.append(level)
        grid.append(row)
    return grid

def list_to_board(grid):
    """Converts 4x4 list of integers to a 64-bit integer board."""
    board = 0
    for r in range(4):
        for c in range(4):
            cell_idx = r * 4 + c
            level = grid[r][c] & 0xF
            board |= (level << (cell_idx * 4))
    return board

def get_cell(board, r, c):
    """Gets level of cell at row r, column c (0-indexed)."""
    cell_idx = r * 4 + c
    return (board >> (cell_idx * 4)) & 0xF

def set_cell(board, r, c, val):
    """Sets cell at row r, column c to val, returns new board."""
    cell_idx = r * 4 + c
    mask = ~(0xF << (cell_idx * 4))
    return (board & mask) | ((val & 0xF) << (cell_idx * 4))

def transpose(board):
    """Transposes a 64-bit board representation (4 bits per cell)."""
    r0 = board & 0xFFFF
    r1 = (board >> 16) & 0xFFFF
    r2 = (board >> 32) & 0xFFFF
    r3 = (board >> 48) & 0xFFFF
    
    tr0 = (r0 & 0xF) | ((r1 & 0xF) << 4) | ((r2 & 0xF) << 8) | ((r3 & 0xF) << 12)
    tr1 = ((r0 >> 4) & 0xF) | (((r1 >> 4) & 0xF) << 4) | (((r2 >> 4) & 0xF) << 8) | (((r3 >> 4) & 0xF) << 12)
    tr2 = ((r0 >> 8) & 0xF) | (((r1 >> 8) & 0xF) << 4) | (((r2 >> 8) & 0xF) << 8) | (((r3 >> 8) & 0xF) << 12)
    tr3 = ((r0 >> 12) & 0xF) | (((r1 >> 12) & 0xF) << 4) | (((r2 >> 12) & 0xF) << 8) | (((r3 >> 12) & 0xF) << 12)
    
    return tr0 | (tr1 << 16) | (tr2 << 32) | (tr3 << 48)

# Move functions
def move_left(board):
    r0 = board & 0xFFFF
    r1 = (board >> 16) & 0xFFFF
    r2 = (board >> 32) & 0xFFFF
    r3 = (board >> 48) & 0xFFFF
    
    nr0 = ROW_LEFT_TABLE[r0]
    nr1 = ROW_LEFT_TABLE[r1]
    nr2 = ROW_LEFT_TABLE[r2]
    nr3 = ROW_LEFT_TABLE[r3]
    
    new_board = nr0 | (nr1 << 16) | (nr2 << 32) | (nr3 << 48)
    score = ROW_SCORE_TABLE[r0] + ROW_SCORE_TABLE[r1] + ROW_SCORE_TABLE[r2] + ROW_SCORE_TABLE[r3]
    valid = (new_board != board)
    return new_board, score, valid

def move_right(board):
    r0 = board & 0xFFFF
    r1 = (board >> 16) & 0xFFFF
    r2 = (board >> 32) & 0xFFFF
    r3 = (board >> 48) & 0xFFFF
    
    rr0 = ROW_REVERSE_TABLE[r0]
    rr1 = ROW_REVERSE_TABLE[r1]
    rr2 = ROW_REVERSE_TABLE[r2]
    rr3 = ROW_REVERSE_TABLE[r3]
    
    nr0 = ROW_LEFT_TABLE[rr0]
    nr1 = ROW_LEFT_TABLE[rr1]
    nr2 = ROW_LEFT_TABLE[rr2]
    nr3 = ROW_LEFT_TABLE[rr3]
    
    nrr0 = ROW_REVERSE_TABLE[nr0]
    nrr1 = ROW_REVERSE_TABLE[nr1]
    nrr2 = ROW_REVERSE_TABLE[nr2]
    nrr3 = ROW_REVERSE_TABLE[nr3]
    
    new_board = nrr0 | (nrr1 << 16) | (nrr2 << 32) | (nrr3 << 48)
    score = ROW_SCORE_TABLE[rr0] + ROW_SCORE_TABLE[rr1] + ROW_SCORE_TABLE[rr2] + ROW_SCORE_TABLE[rr3]
    valid = (new_board != board)
    return new_board, score, valid

def move_up(board):
    t_board = transpose(board)
    t_new, score, valid = move_left(t_board)
    return transpose(t_new), score, valid

def move_down(board):
    t_board = transpose(board)
    t_new, score, valid = move_right(t_board)
    return transpose(t_new), score, valid

def apply_move(board, direction):
    """Applies move in a direction. Returns (new_board, score, valid)."""
    if direction == LEFT:
        return move_left(board)
    elif direction == RIGHT:
        return move_right(board)
    elif direction == UP:
        return move_up(board)
    elif direction == DOWN:
        return move_down(board)
    return board, 0, False

def get_valid_moves(board):
    """Returns a list of valid directions (0-3)."""
    valid_moves = []
    for d in [LEFT, RIGHT, UP, DOWN]:
        _, _, valid = apply_move(board, d)
        if valid:
            valid_moves.append(d)
    return valid_moves

# Spawn model
def get_spawn_outcomes(board, mode_name, spawn_patterns=None):
    """
    Returns list of tuples (probability, spawned_board, spawn_score).
    spawn_patterns: dict mapping pattern (tuple of sorted levels) to probability.
                    If None, we build it from the default config.
    """
    empty_cells = []
    for i in range(16):
        if ((board >> (i * 4)) & 0xF) == 0:
            empty_cells.append(i)
            
    if not empty_cells:
        return []
        
    K = len(empty_cells)
    mode_cfg = config['modes'][mode_name]
    L = mode_cfg['low_spawn']
    H = mode_cfg['high_spawn']
    
    appear = config['appear_points']
    policy = config.get('spawn_policy', 'truncated')
    
    # If no spawn patterns provided, build default from config
    if spawn_patterns is None:
        p_cfg = config['spawn_probabilities']
        spawn_patterns = {
            (L,): p_cfg.get('event_1_low', 0.50),
            (L, L): p_cfg.get('event_2_low', 0.35),
            (L, L, H): p_cfg.get('event_2_low_1_high', 0.15)
        }
        
    outcomes = {} # new_board -> (prob, score)
    
    # Filter patterns that have probability > 0
    active_patterns = {pat: p for pat, p in spawn_patterns.items() if p > 0}
    
    if policy == "invalid_event":
        # Keep only patterns that fit
        valid_patterns = {pat: p for pat, p in active_patterns.items() if len(pat) <= K}
        total_p = sum(valid_patterns.values())
        if total_p > 0:
            active_patterns = {pat: p / total_p for pat, p in valid_patterns.items()}
        else:
            active_patterns = {(L,): 1.0}
            
    for pattern, p_pat in active_patterns.items():
        # Truncate pattern if too long
        if len(pattern) > K:
            p_act = pattern[:K]
        else:
            p_act = pattern
            
        N = len(p_act)
        if N == 0:
            if board in outcomes:
                outcomes[board] = (outcomes[board][0] + p_pat, outcomes[board][1])
            else:
                outcomes[board] = (p_pat, 0)
            continue
            
        cells_combinations = list(itertools.combinations(empty_cells, N))
        unique_perms = list(set(itertools.permutations(p_act)))
        
        num_outcomes = len(cells_combinations) * len(unique_perms)
        prob_per_outcome = p_pat / num_outcomes
        appear_score = sum(appear.get(lvl, 0) for lvl in p_act)
        
        for cells in cells_combinations:
            for perm in unique_perms:
                nb = board
                for cell_idx, lvl in zip(cells, perm):
                    nb |= (lvl << (cell_idx * 4))
                    
                if nb in outcomes:
                    outcomes[nb] = (outcomes[nb][0] + prob_per_outcome, appear_score)
                else:
                    outcomes[nb] = (prob_per_outcome, appear_score)
                    
    return [(prob, nb, score) for nb, (prob, score) in outcomes.items()]


def pretty_print_board(board):
    """Returns a string representation of the board."""
    grid = board_to_list(board)
    out = []
    for r in range(4):
        row_str = " | ".join(f"{grid[r][c]:2d}" if grid[r][c] > 0 else "  " for c in range(4))
        out.append(f"| {row_str} |")
    return "\n".join(out)
