import sys
import json
import time
from src.game_engine import (
    list_to_board,
    board_to_list,
    apply_move,
    get_valid_moves,
    config as default_config,
    init_tables
)
from src.solver import get_best_move, explain_move

# Global config that can be updated from JS
current_config = default_config.copy()

def update_config(new_config_json):
    global current_config
    new_cfg = json.loads(new_config_json)
    # Deep merge or replace
    current_config.update(new_cfg)
    # Re-initialize engine tables in case stone level or merge points changed
    init_tables()
    return json.dumps({"status": "ok"})

def solve(grid_json, mode="x1", depth=None, time_limit_ms=None):
    grid = json.loads(grid_json)
    board = list_to_board(grid)
    
    # We use sequential evaluation for the web
    # because ProcessPoolExecutor is not available in Pyodide
    
    start_time = time.time()
    
    # get_best_move(board, mode_name, config, spawn_patterns=None, override_depth=None, override_time_ms=None, cancel_token=None, on_depth_complete=None)
    best_move, ev, expected_empty, move_values, move_real_values, completed_depth, node_count = get_best_move(
        board, 
        mode, 
        current_config, 
        spawn_patterns=None, 
        override_depth=depth, 
        override_time_ms=time_limit_ms
    )
    
    elapsed = (time.time() - start_time) * 1000
    
    DIR_MAP = {0: "LEFT", 1: "RIGHT", 2: "UP", 3: "DOWN"}
    
    result = {
        "best_move": DIR_MAP.get(best_move),
        "ev": ev,
        "expected_empty": expected_empty,
        "completed_depth": completed_depth,
        "node_count": node_count,
        "elapsed_ms": elapsed,
        "move_evaluations": {DIR_MAP[m]: v for m, v in move_real_values.items()},
        "explanation": explain_move(board, best_move, current_config) if best_move is not None else []
    }
    
    return json.dumps(result)

def get_current_config():
    return json.dumps(current_config)
