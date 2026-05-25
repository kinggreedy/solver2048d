# stats.py
import os
import json
import time
from datetime import datetime

from src.paths import LOGS_DIR, ensure_logs_dir

def append_to_jsonl(filename, data):
    ensure_logs_dir()
    filepath = os.path.join(LOGS_DIR, filename)
    # Add timestamp if not present
    if 'timestamp' not in data:
        data['timestamp'] = datetime.utcnow().isoformat()
    with open(filepath, "a") as f:
        f.write(json.dumps(data) + "\n")

def log_board_evaluation(board_state, enabled_modes, selected_mode, rec_move, alt_values, ev_per_energy, decision, heuristics_features, sim_budget):
    """Logs solver board evaluation details."""
    data = {
        'board_state': hex(board_state),
        'enabled_modes': enabled_modes,
        'selected_mode': selected_mode,
        'recommended_move': rec_move,
        'alternative_move_values': {str(k): float(v) for k, v in alt_values.items()},
        'estimated_ev_per_energy': float(ev_per_energy),
        'decision': decision,
        'heuristics_features': heuristics_features,
        'simulation_budget_used': sim_budget
    }
    append_to_jsonl("board_eval.jsonl", data)

def log_move_result(board_before, move_taken, mode_used, is_valid, merge_score, spawned_cells, board_after):
    """Logs the outcome of a move."""
    data = {
        'board_before': hex(board_before),
        'move_taken': move_taken,
        'mode_used': mode_used,
        'is_valid': is_valid,
        'merge_score_observed': int(merge_score),
        'spawned_cells_observed': spawned_cells,  # list of (index, level)
        'board_after': hex(board_after)
    }
    append_to_jsonl("move_result.jsonl", data)

def log_game_summary(total_moves, total_energy, total_points, final_board, max_level, stones_created, restart_reason):
    """Logs the overall game summary when ended."""
    data = {
        'total_valid_moves': int(total_moves),
        'total_energy_spent': int(total_energy),
        'total_points_earned': int(total_points),
        'final_board': hex(final_board),
        'max_level_reached': int(max_level),
        'stones_created': int(stones_created),
        'restart_reason': restart_reason
    }
    append_to_jsonl("game_summary.jsonl", data)

def log_spawn_observation(selected_mode, num_new_cells, levels_new_cells, empty_before, board_before, board_after):
    """Logs user observations of newly spawned tiles."""
    data = {
        'selected_mode': selected_mode,
        'num_new_cells': int(num_new_cells),
        'levels_new_cells': [int(lvl) for lvl in levels_new_cells],
        'empty_cell_count_before_spawn': int(empty_before) if empty_before is not None else None,
        'board_before_spawn': hex(board_before) if board_before is not None else None,
        'board_after_spawn': hex(board_after) if board_after is not None else None
    }
    append_to_jsonl("spawn_observations.jsonl", data)

def load_spawn_observations():
    """Reads spawn observations file from log folder."""
    filepath = os.path.join(LOGS_DIR, "spawn_observations.jsonl")
    if not os.path.exists(filepath):
        return []
    obs = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                obs.append(json.loads(line))
    return obs

def compute_spawn_statistics(config):
    """Computes empirical statistics of observed spawns, pooling observations across all modes."""
    observations = load_spawn_observations()
    if not observations:
        return {
            'total_observations': 0,
            'confidence_warning': "No observations recorded yet.",
            'empirical_probabilities': {m: None for m in config['modes']},
            'relative_probabilities': {}
        }
        
    total_obs = len(observations)
    
    # 1. Pool all observations to get global relative pattern counts
    global_relative_counts = {}
    global_total = 0
    
    for ob in observations:
        m = ob.get('selected_mode')
        levels = ob.get('levels_new_cells', [])
        if not levels or m not in config['modes']:
            continue
            
        mode_cfg = config['modes'][m]
        L = mode_cfg['low_spawn']
        H = mode_cfg['high_spawn']
        
        # Convert to relative: 1 for low, 2 for high
        rel_pattern = tuple(sorted(1 if lvl == L else 2 for lvl in levels if lvl in (L, H)))
        if rel_pattern:
            global_relative_counts[rel_pattern] = global_relative_counts.get(rel_pattern, 0) + 1
            global_total += 1
            
    # 2. Build empirical probabilities for each mode by mapping relative patterns back to actual levels
    empirical_probs = {}
    
    # Compute relative probabilities
    relative_probs = {}
    if global_total > 0:
        for rel_pat, count in global_relative_counts.items():
            relative_probs[rel_pat] = count / global_total
            
    for m in config['modes']:
        mode_cfg = config['modes'][m]
        L = mode_cfg['low_spawn']
        H = mode_cfg['high_spawn']
        
        if global_total > 0:
            probs = {}
            for rel_pat, p in relative_probs.items():
                # Map back to actual levels for this mode
                actual_pat = tuple(L if idx == 1 else H for idx in rel_pat)
                probs[actual_pat] = p
            probs['_sample_size'] = global_total  # Shared pooled sample size
            empirical_probs[m] = probs
        else:
            empirical_probs[m] = None
            
    confidence_warning = None
    if global_total < 30:
        confidence_warning = f"Confidence warning: low pooled sample size ({global_total} events). Standard assumed probabilities should be preferred."
        
    return {
        'total_observations': total_obs,
        'empirical_probabilities': empirical_probs,
        'relative_probabilities': relative_probs,
        'confidence_warning': confidence_warning
    }

