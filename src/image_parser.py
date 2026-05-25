# image_parser.py
from PIL import Image
import os
from src import game_engine

def load_capture_config():
    """Loads configuration settings for screenshot capture."""
    config = game_engine.config
    return config.get('capture', {})

def parse_screenshot(image_path):
    """
    Crops the board region from a screenshot, divides it into 4x4 cells,
    samples background colors from inner/center patches of each cell,
    and maps them to tile levels using Euclidean distance in RGB space.
    """
    if not os.path.exists(image_path):
        print(f"Error: Screenshot file {image_path} does not exist.")
        return None
        
    try:
        img = Image.open(image_path)
    except Exception as e:
        print(f"Error opening screenshot {image_path}: {e}")
        return None
        
    cfg = load_capture_config()
    crop_x = cfg.get('crop_x', 100)
    crop_y = cfg.get('crop_y', 500)
    crop_w = cfg.get('crop_w', 880)
    crop_h = cfg.get('crop_h', 880)
    
    img_w, img_h = img.size
    if crop_x + crop_w > img_w or crop_y + crop_h > img_h:
        print(f"Warning: Crop coordinates ({crop_x}, {crop_y}, {crop_w}, {crop_h}) exceed image size ({img_w}x{img_h}). Clamping.")
        crop_x = max(0, min(crop_x, img_w - 1))
        crop_y = max(0, min(crop_y, img_h - 1))
        crop_w = min(crop_w, img_w - crop_x)
        crop_h = min(crop_h, img_h - crop_y)
        
    board_img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
    rgb_img = board_img.convert("RGB")
    
    cell_w = crop_w / 4
    cell_h = crop_h / 4
    
    # Load color definitions from config
    color_map_raw = cfg.get('colors', {})
    color_map = {}
    for k, v in color_map_raw.items():
        try:
            color_map[int(k)] = tuple(v)
        except ValueError:
            pass
            
    # Fallback default colors if missing from config
    if not color_map:
        color_map = {
            0: (46, 46, 56),
            1: (79, 172, 254),
            2: (0, 242, 254),
            3: (76, 175, 80),
            4: (0, 230, 118),
            5: (255, 235, 59),
            6: (255, 152, 0),
            7: (255, 87, 34),
            8: (244, 67, 54),
            9: (213, 0, 249),
            10: (101, 31, 255),
            11: (55, 71, 79),
        }
        
    grid = [[0 for _ in range(4)] for _ in range(4)]
    
    print("\n--- Board Image Classification Details ---")
    for r in range(4):
        row_debug = []
        for c in range(4):
            # Define cell boundaries relative to cropped board image
            cell_left = c * cell_w
            cell_top = r * cell_h
            
            # Sample 4 inner/center patches (at 25% and 75% dimensions)
            # This avoids tile borders/shadows/corners and central text/emojis
            px1 = int(cell_left + cell_w * 0.25)
            py1 = int(cell_top + cell_h * 0.25)
            
            px2 = int(cell_left + cell_w * 0.75)
            py2 = int(cell_top + cell_h * 0.25)
            
            px3 = int(cell_left + cell_w * 0.25)
            py3 = int(cell_top + cell_h * 0.75)
            
            px4 = int(cell_left + cell_w * 0.75)
            py4 = int(cell_top + cell_h * 0.75)
            
            w_b, h_b = rgb_img.size
            pts = []
            for px, py in [(px1, py1), (px2, py2), (px3, py3), (px4, py4)]:
                px = max(0, min(px, w_b - 1))
                py = max(0, min(py, h_b - 1))
                pts.append(rgb_img.getpixel((px, py)))
                
            # Average color
            avg_r = sum(p[0] for p in pts) // len(pts)
            avg_g = sum(p[1] for p in pts) // len(pts)
            avg_b = sum(p[2] for p in pts) // len(pts)
            sampled_rgb = (avg_r, avg_g, avg_b)
            
            # Classify level via Euclidean distance
            min_dist = float('inf')
            closest_lvl = 0
            for lvl, col in color_map.items():
                dist = (sampled_rgb[0] - col[0])**2 + (sampled_rgb[1] - col[1])**2 + (sampled_rgb[2] - col[2])**2
                if dist < min_dist:
                    min_dist = dist
                    closest_lvl = lvl
                    
            grid[r][c] = closest_lvl
            row_debug.append(f"({r},{c}): RGB={sampled_rgb} -> Lvl {closest_lvl} (dist={int(min_dist)})")
            
        print(" | ".join(row_debug))
        
    print("\nParsed Level Grid:")
    for r in range(4):
        print(f"  {grid[r]}")
    print("------------------------------------------")
    
    return grid
