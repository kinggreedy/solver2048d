# view_history.py
import os
import json
import sys
import tty
import termios
import select
from datetime import datetime
from src import game_engine
from src.paths import LOGS_DIR
MOVE_LOG_PATH = os.path.join(LOGS_DIR, "move_result.jsonl")

# Fallback energy costs if config loading fails
DEFAULT_ENERGY_COSTS = {
    'x1': 1,
    'x4': 4,
    'x8': 8,
    'x16': 16
}

# 24-bit Truecolor definitions matching PyQt6 GUI colors
CELL_COLORS = {
    0: (46, 46, 56),     # empty: #2e2e38
    1: (79, 172, 254),   # x1 spawn low: #4facfe
    2: (0, 242, 254),    # x1 spawn high: #00f2fe
    3: (76, 175, 80),    # x4 spawn low: #4caf50
    4: (0, 230, 118),    # x4 spawn high: #00e676
    5: (255, 235, 59),   # #ffeb3b
    6: (255, 152, 0),    # #ff9800
    7: (255, 87, 34),    # #ff5722
    8: (244, 67, 54),    # #f44336
    9: (213, 0, 249),    # #d500f9
    10: (101, 31, 255),  # #651fff
    11: (55, 71, 79),    # stone: #37474f
}

def get_energy_cost(mode):
    """Retrieves energy cost for a mode from the config, falling back if not found."""
    try:
        return game_engine.config['modes'][mode]['energy_cost']
    except Exception:
        return DEFAULT_ENERGY_COSTS.get(mode, 1)

def parse_time(ts_str):
    """Parses ISO timestamp string into datetime object."""
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return datetime.utcnow()

def parse_logs():
    """Reads and parses the move results log file."""
    if not os.path.exists(MOVE_LOG_PATH):
        return []
    
    moves = []
    with open(MOVE_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                moves.append(json.loads(line))
            except Exception:
                pass
    return moves

def group_into_sessions(moves):
    """Groups a flat list of moves into gameplay sessions based on discontinuities, starting boards, and time gaps."""
    sessions = []
    current_session = []
    
    for move in moves:
        start_new = False
        if not current_session:
            start_new = True
        else:
            prev_move = current_session[-1]
            # Time gap > 10 mins
            t_curr = parse_time(move.get('timestamp', ''))
            t_prev = parse_time(prev_move.get('timestamp', ''))
            time_gap = (t_curr - t_prev).total_seconds()
            
            # Discontinuity in board state (current board_before doesn't match prev board_after)
            discontinuity = (move.get('board_before') != prev_move.get('board_after'))
            
            # Check if current board is a starting board
            board_int = int(move.get('board_before', '0'), 16)
            grid = game_engine.board_to_list(board_int)
            flat = [cell for row in grid for cell in row]
            non_zeros = [c for c in flat if c > 0]
            is_start_board = (len(non_zeros) <= 2 and all(c <= 2 for c in non_zeros))
            
            if time_gap > 600 or discontinuity or is_start_board:
                start_new = True
                
        if start_new:
            if current_session:
                sessions.append(current_session)
            current_session = [move]
        else:
            current_session.append(move)
            
    if current_session:
        sessions.append(current_session)
        
    return sessions

def get_session_summary(session):
    """Computes high-level statistics for a gameplay session."""
    if not session:
        return {}
    
    first_move = session[0]
    ts_str = first_move.get('timestamp', '')
    dt = parse_time(ts_str)
    date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    
    total_moves = len(session)
    valid_moves = sum(1 for m in session if m.get('is_valid', True))
    total_score = sum(m.get('merge_score_observed', 0) for m in session)
    
    # Calculate max level achieved
    max_level = 0
    for m in session:
        for b_hex in [m.get('board_before'), m.get('board_after')]:
            if b_hex:
                board_int = int(b_hex, 16)
                grid = game_engine.board_to_list(board_int)
                for row in grid:
                    for cell in row:
                        if cell > max_level:
                            max_level = cell
                            
    # Energy
    total_energy = sum(get_energy_cost(m.get('mode_used', 'x1')) for m in session if m.get('is_valid', True))
    
    return {
        'date': date_str,
        'moves': total_moves,
        'valid_moves': valid_moves,
        'score': total_score,
        'max_level': max_level,
        'energy': total_energy
    }

def color_text(text, fg_rgb, bg_rgb):
    """Applies truecolor foreground and background ANSI escapes to text."""
    return f"\033[38;2;{fg_rgb[0]};{fg_rgb[1]};{fg_rgb[2]};48;2;{bg_rgb[0]};{bg_rgb[1]};{bg_rgb[2]}m{text}\033[0m"

def get_cell_text_and_colors(level, is_spawned=False):
    """Determines formatting for a tile based on level and spawn state."""
    bg = CELL_COLORS.get(level, (18, 18, 20))
    # Text color: dark for cyan/yellow/bright-green
    if level in [2, 4, 5]:
        fg = (18, 18, 20)
    else:
        fg = (255, 255, 255)
        
    if level == 0:
        text = "      "
    elif level == 11:
        text = " 🪨11 "
    else:
        if is_spawned:
            text = f"  {level}*  "
        else:
            if level >= 10:
                text = f"  {level}  "
            else:
                text = f"  {level}   "
                
    return text, fg, bg

def get_board_lines(board, spawned_cells=None):
    """Formats a board representation into a list of ANSI color-formatted lines."""
    grid = game_engine.board_to_list(board)
    spawn_coords = set()
    if spawned_cells:
        for idx, lvl in spawned_cells:
            spawn_coords.add((idx // 4, idx % 4))
            
    lines = []
    for r in range(4):
        line_top_parts = []
        line_mid_parts = []
        line_bot_parts = []
        
        for c in range(4):
            level = grid[r][c]
            is_spawn = (r, c) in spawn_coords
            text, fg, bg = get_cell_text_and_colors(level, is_spawn)
            
            top_part = color_text("      ", fg, bg)
            mid_part = color_text(text, fg, bg)
            bot_part = color_text("      ", fg, bg)
            
            line_top_parts.append(top_part)
            line_mid_parts.append(mid_part)
            line_bot_parts.append(bot_part)
            
        lines.append(" ".join(line_top_parts))
        lines.append(" ".join(line_mid_parts))
        lines.append(" ".join(line_bot_parts))
        
        if r < 3:
            lines.append(" " * (4 * 6 + 3 * 1))
            
    return lines

def clear_screen():
    """Clears the terminal and puts the cursor at home position."""
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

def get_char():
    """Reads a single key input from terminal in raw mode (non-blocking escape sequences)."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            # Check if this is an arrow key
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    r, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if r:
                        ch3 = sys.stdin.read(1)
                        return '\x1b[' + ch3
                return '\x1b' + ch2
            return '\x1b'
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def draw_buttons(is_playing=False):
    """Draws styled command buttons at the bottom of the TUI."""
    buttons = [
        ("A", "Prev"),
        ("D", "Next"),
        ("SPC", "Stop" if is_playing else "Auto"),
        ("S", "Sess"),
        ("G", "Jump"),
        ("Q", "Quit")
    ]
    
    top_line = "  "
    mid_line = "  "
    bot_line = "  "
    
    for key, label in buttons:
        btn_text = f"[{key}] {label}"
        width = len(btn_text) + 2
        
        if key == "Q":
            bg = (130, 20, 20)  # Red background
        elif key == "SPC" and is_playing:
            bg = (40, 167, 69)  # Green background
        else:
            bg = (40, 60, 90)   # Blue background
            
        fg = (255, 255, 255)
        
        top = color_text(" " * width, fg, bg)
        mid = color_text(f" {btn_text} ", fg, bg)
        bot = color_text(" " * width, fg, bg)
        
        top_line += top + "  "
        mid_line += mid + "  "
        bot_line += bot + "  "
        
    print(top_line)
    print(mid_line)
    print(bot_line)

def prompt_jump(current_idx, total_moves):
    """Asks user to jump to a specific move index."""
    print(f"\n  Jump to move (1-{total_moves}): ", end="", flush=True)
    try:
        val = sys.stdin.readline().strip()
        idx = int(val) - 1
        if 0 <= idx < total_moves:
            return idx
    except Exception:
        pass
    return current_idx

def select_session_tui(sessions):
    """Displays interactive session chooser screen using arrow keys."""
    if not sessions:
        print("  No sessions found in log.")
        return None
        
    summaries = [get_session_summary(s) for s in sessions]
    selected_idx = len(sessions) - 1  # Default to the most recent game
    
    while True:
        clear_screen()
        print("  Select Gameplay Session:")
        print("  " + "=" * 70)
        
        for idx, s in enumerate(summaries):
            prefix = " > " if idx == selected_idx else "   "
            line = f"{prefix}[Session {idx+1}] {s['date']} | Moves: {s['moves']} | Score: {s['score']} | Max Lvl: {s['max_level']}"
            
            if idx == selected_idx:
                print(f"\033[48;2;40;167;69m\033[38;2;255;255;255m{line:<74}\033[0m")
            else:
                print(line)
                
        print("  " + "=" * 70)
        print("  Controls: [W/Up] Move Up | [S/Down] Move Down | [Enter/Space] Select | [Q] Quit")
        
        key = get_char()
        if key == 'q' or key == 'Q' or key == '\x03':
            return None
        elif key == '\x1b[A' or key == 'w' or key == 'W':
            selected_idx = (selected_idx - 1) % len(sessions)
        elif key == '\x1b[B' or key == 's' or key == 'S':
            selected_idx = (selected_idx + 1) % len(sessions)
        elif key in ['\n', '\r', ' ']:
            return selected_idx

def view_session(session, session_num):
    """Interactively steps through moves within a selected gameplay session."""
    total_moves = len(session)
    if total_moves == 0:
        return
        
    move_idx = 0
    is_playing = False
    play_delay = 1.0  # Seconds per frame in autoplay
    
    # Precompute cumulative score and energy
    cum_scores = []
    cum_energies = []
    current_score = 0
    current_energy = 0
    
    for m in session:
        current_score += m.get('merge_score_observed', 0)
        if m.get('is_valid', True):
            current_energy += get_energy_cost(m.get('mode_used', 'x1'))
        cum_scores.append(current_score)
        cum_energies.append(current_energy)
        
    while True:
        clear_screen()
        move = session[move_idx]
        
        print(f"  SESSION {session_num} | Move {move_idx + 1} of {total_moves}")
        efficiency = (cum_scores[move_idx] / cum_energies[move_idx]) if cum_energies[move_idx] > 0 else 0.0
        print(f"  Cumulative Score: {cum_scores[move_idx]} | Energy Spent: {cum_energies[move_idx]} | Pts/Energy: {efficiency:.2f}")
        print("  " + "=" * 70)
        
        board_before = int(move.get('board_before', '0'), 16)
        board_after = int(move.get('board_after', '0'), 16)
        move_taken = move.get('move_taken', '')
        mode_used = move.get('mode_used', 'x1')
        is_valid = move.get('is_valid', True)
        merge_score = move.get('merge_score_observed', 0)
        spawned_cells = move.get('spawned_cells_observed', [])
        
        before_lines = get_board_lines(board_before)
        after_lines = get_board_lines(board_after, spawned_cells)
        
        print(f"  Action: {move_taken:<15} Mode: {mode_used:<8} Valid: {str(is_valid):<8} Score: +{merge_score}")
        print("  " + "-" * 70)
        print("  Before Move:                        After Move & Spawn:")
        
        for b_line, a_line in zip(before_lines, after_lines):
            print(f"  {b_line}      {a_line}")
            
        print()
        spawn_desc = ", ".join([f"({idx // 4}, {idx % 4}) Lvl {lvl}" for idx, lvl in spawned_cells]) if spawned_cells else "None"
        print(f"  Spawned Tiles at: {spawn_desc}")
        print("  " + "-" * 70)
        
        draw_buttons(is_playing)
        print()
        
        if is_playing:
            r, _, _ = select.select([sys.stdin], [], [], play_delay)
            if r:
                key = get_char()
                if key == ' ':
                    is_playing = False
                elif key == 'q' or key == 'Q' or key == '\x03':
                    return 'quit'
                elif key == 's' or key == 'S':
                    return 'select_session'
                elif key == 'g' or key == 'G':
                    is_playing = False
                    move_idx = prompt_jump(move_idx, total_moves)
                elif key == '+':
                    play_delay = max(0.1, play_delay - 0.2)
                elif key == '-':
                    play_delay = min(5.0, play_delay + 0.2)
            else:
                if move_idx < total_moves - 1:
                    move_idx += 1
                else:
                    is_playing = False
        else:
            key = get_char()
            if key == 'q' or key == 'Q' or key == '\x03':
                return 'quit'
            elif key == '\x1b[D' or key == 'a' or key == 'A':  # Left/Prev
                if move_idx > 0:
                    move_idx -= 1
            elif key == '\x1b[C' or key == 'd' or key == 'D':  # Right/Next
                if move_idx < total_moves - 1:
                    move_idx += 1
            elif key == '0':
                move_idx = 0
            elif key == '$':
                move_idx = total_moves - 1
            elif key == ' ':
                is_playing = True
            elif key == 's' or key == 'S':
                return 'select_session'
            elif key == 'g' or key == 'G':
                move_idx = prompt_jump(move_idx, total_moves)

def main():
    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    try:
        moves = parse_logs()
        if not moves:
            print("  Error: logs/move_result.jsonl not found or empty.")
            print("  Please play some moves using main.py to populate logs first.")
            return
            
        sessions = group_into_sessions(moves)
        
        active_session_idx = len(sessions) - 1
        
        while True:
            res = view_session(sessions[active_session_idx], active_session_idx + 1)
            if res == 'select_session':
                sel = select_session_tui(sessions)
                if sel is not None:
                    active_session_idx = sel
                else:
                    break
            else:
                break
    finally:
        # Show cursor and reset style
        sys.stdout.write("\033[?25h\033[0m")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
