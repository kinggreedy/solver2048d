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
from src.solver import evaluate_board_options, explain_move

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

def solve(grid_json, mode="x1", depth=None, time_limit_ms=None, enabled_modes_json=None, progress_fn=None):
    # This is now the "One-Shot" or "Fixed-Step" entry point
    try:
        grid = json.loads(grid_json)
        board = list_to_board(grid)
        enabled_modes = json.loads(enabled_modes_json) if enabled_modes_json else [mode]
        
        start_time = time.time()
        DIR_MAP = {0: "LEFT", 1: "RIGHT", 2: "UP", 3: "DOWN"}

        # We now use the standard solver's evaluate_board_options but we 
        # can call it with a fixed depth to prevent internal looping if needed.
        # However, to support multi-mode comparison (X1 vs X4) at a specific depth:
        from src.solver import evaluate_board_options
        
        # We pass override_time_ms=0 to force sequential evaluation of modes
        # at the exact provided depth.
        eval_dict = evaluate_board_options(
            board, 
            current_config, 
            enabled_modes=enabled_modes,
            override_depth=depth, 
            override_time_ms=0 # Force fixed depth, no time-based deepening
        )
        
        # Map moves to strings for JS
        if 'best_move' in eval_dict and eval_dict['best_move'] is not None:
            eval_dict['best_move_str'] = DIR_MAP.get(eval_dict['best_move'])
        
        for m, res in eval_dict.get('results', {}).items():
            if res and 'best_move' in res and res['best_move'] is not None:
                res['best_move_str'] = DIR_MAP.get(res['best_move'])
                res['move_real_values_str'] = {DIR_MAP[mv_i]: v for mv_i, v in res.get('move_real_values', {}).items()}

        eval_dict['explanation'] = explain_move(board, eval_dict.get('best_move'), current_config) if eval_dict.get('best_move') is not None else []
        eval_dict['elapsed_ms'] = (time.time() - start_time) * 1000
        
        return json.dumps(eval_dict)
    except Exception as e:
        import traceback
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})

def get_current_config():
    return json.dumps(current_config)
