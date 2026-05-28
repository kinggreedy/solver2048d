import sys
import json
import time
import math
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

def sanitize_floats(obj):
    """Recursively converts NaN and Infinity to None for JSON compliance."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(x) for x in obj]
    return obj

def update_config(new_config_json):
    global current_config
    new_cfg = json.loads(new_config_json)
    current_config.update(new_cfg)
    init_tables()
    return json.dumps({"status": "ok"})

def solve(grid_json, mode="x1", depth=None, time_limit_ms=None, enabled_modes_json=None, progress_fn=None):
    try:
        grid = json.loads(grid_json)
        board = list_to_board(grid)
        
        start_time = time.time()
        DIR_MAP = {0: "LEFT", 1: "RIGHT", 2: "UP", 3: "DOWN"}

        def _on_depth_complete(bm, br, be, mv, mrv, d, nc):
            if progress_fn:
                try:
                    energy_cost = current_config['modes'][mode]['energy_cost']
                    
                    mode_res = {
                        'best_move': bm,
                        'best_move_str': DIR_MAP.get(bm),
                        'ev': br,
                        'ev_per_energy': br / energy_cost,
                        'expected_empty': be,
                        'move_values': mv,
                        'move_real_values': mrv,
                        'move_real_values_str': {DIR_MAP[mv_i]: v for mv_i, v in mrv.items()},
                        'completed_depth': d,
                        'node_count': nc
                    }
                    
                    from src.solver import _build_eval_dict
                    eval_dict = _build_eval_dict({mode: mode_res}, current_config)
                    eval_dict['best_move_str'] = DIR_MAP.get(eval_dict.get('best_move'))
                    eval_dict['explanation'] = explain_move(board, bm, current_config)
                    
                    elapsed = (time.time() - start_time) * 1000
                    sanitized = sanitize_floats(eval_dict)
                    progress_fn(json.dumps(sanitized), elapsed)
                except Exception as e:
                    print(f"Error in progress callback: {e}")

        from src.solver import get_best_move
        
        best_move, ev, expected_empty, move_values, move_real_values, completed_depth, node_count = get_best_move(
            board, 
            mode, 
            current_config, 
            spawn_patterns=None, 
            override_depth=depth, 
            override_time_ms=time_limit_ms,
            on_depth_complete=_on_depth_complete
        )
        
        # Final result
        energy_cost = current_config['modes'][mode]['energy_cost']
        mode_res = {
            'best_move': best_move,
            'best_move_str': DIR_MAP.get(best_move),
            'ev': ev,
            'ev_per_energy': ev / energy_cost if best_move is not None else 0.0,
            'expected_empty': expected_empty,
            'move_values': move_values,
            'move_real_values': move_real_values,
            'move_real_values_str': {DIR_MAP[mv_i]: v for mv_i, v in move_real_values.items()},
            'completed_depth': completed_depth,
            'node_count': node_count
        }
        
        from src.solver import _build_eval_dict
        final_eval = _build_eval_dict({mode: mode_res}, current_config)
        final_eval['best_move_str'] = DIR_MAP.get(final_eval.get('best_move'))
        final_eval['explanation'] = explain_move(board, best_move, current_config) if best_move is not None else []
        final_eval['elapsed_ms'] = (time.time() - start_time) * 1000
        
        sanitized = sanitize_floats(final_eval)
        return json.dumps(sanitized)
    except Exception as e:
        import traceback
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})

def get_current_config():
    return json.dumps(current_config)
