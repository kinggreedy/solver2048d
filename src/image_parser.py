# image_parser.py
from PIL import Image, ImageStat
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
    
    # Setup OCR/Dataset collection if enabled
    collect_ocr = cfg.get('collect_ocr', False)
    ocr_dir = None
    timestamp = None
    if collect_ocr:
        import datetime
        from src.paths import LOGS_DIR
        ocr_dir = os.path.join(LOGS_DIR, "ocr_data")
        os.makedirs(ocr_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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
    
    # Save a debug cropped image with grid overlay for alignment verification
    try:
        from PIL import ImageDraw
        from src.paths import LOGS_DIR
        debug_img = board_img.copy()
        draw = ImageDraw.Draw(debug_img)
        # Draw 4x4 cell grid lines
        for i in range(1, 4):
            # Vertical lines
            vx = int(i * (crop_w / 4))
            draw.line([(vx, 0), (vx, crop_h)], fill=(255, 0, 0), width=3)
            # Horizontal lines
            vy = int(i * (crop_h / 4))
            draw.line([(0, vy), (crop_w, vy)], fill=(255, 0, 0), width=3)
        # Draw borders
        draw.rectangle([(0, 0), (crop_w - 1, crop_h - 1)], outline=(255, 0, 0), width=4)
        
        debug_path = os.path.join(LOGS_DIR, "debug_cropped.png")
        debug_img.save(debug_path)
        print(f"Saved crop debug image to {debug_path}")
    except Exception as e:
        print(f"Error saving debug_cropped.png: {e}")
        
    cell_w = crop_w / 4
    cell_h = crop_h / 4
    
    # Determine capture mode: "level" or "x"
    mode = cfg.get('mode', 'level')
    
    # Load color definitions from config based on mode
    if mode == 'x':
        color_map_raw = cfg.get('colors_x', {})
    else:
        color_map_raw = cfg.get('colors_level', cfg.get('colors', {}))
        
    color_map = {}
    for k, v in color_map_raw.items():
        try:
            color_map[int(k)] = tuple(v)
        except ValueError:
            pass
            
    # Fallback default colors if missing from config
    if not color_map:
        if mode == 'x':
            color_map = {
                0: (241, 225, 194),
                1: (204, 164, 142),   # x2
                2: (202, 163, 142),   # x4
                3: (181, 146, 133),   # x8
                4: (170, 130, 118),   # x16
                5: (166, 126, 114),   # x32
                6: (232, 204, 190),   # x64
                7: (220, 190, 150),   # x128
                8: (215, 185, 140),   # x256
                9: (210, 180, 130),   # x512
                10: (205, 175, 120),  # x1024
                11: (200, 170, 110),  # x2048/stone
            }
        else:
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
    
    # Thresholds for empty cell detection.
    # Empty cells are usually bright and very flat (low standard deviation).
    empty_lum_threshold = cfg.get('empty_lum_threshold', 200)
    empty_stddev_threshold = cfg.get('empty_stddev_threshold', 10.0)
        
    grid = [[0 for _ in range(4)] for _ in range(4)]
    
    print("\n--- Board Image Classification Details ---")
    for r in range(4):
        row_debug = []
        for c in range(4):
            # Cell pixel boundaries
            cell_left_px = int(c * cell_w)
            cell_top_px = int(r * cell_h)
            cell_right_px = int((c + 1) * cell_w)
            cell_bottom_px = int((r + 1) * cell_h)
            cell_w_px = cell_right_px - cell_left_px
            cell_h_px = cell_bottom_px - cell_top_px

            w_b, h_b = rgb_img.size

            # Grayscale stddev across the whole cell
            cell_crop = board_img.crop((cell_left_px, cell_top_px, cell_right_px, cell_bottom_px))
            cell_gray = cell_crop.convert("L")
            stat_gray = ImageStat.Stat(cell_gray)
            stddev_gray = stat_gray.stddev[0]

            if mode == 'x':
                # --- "x" / multiplier mode ---
                # Step 1: Sample a 3x3 grid at the center for luminance.
                # Use a robust median-based approach to ignore specular highlights.
                center_pixels = []
                for fx in [0.45, 0.50, 0.55]:
                    for fy in [0.45, 0.50, 0.55]:
                        px = max(0, min(int(cell_left_px + fx * cell_w_px), w_b - 1))
                        py = max(0, min(int(cell_top_px + fy * cell_h_px), h_b - 1))
                        center_pixels.append(rgb_img.getpixel((px, py)))
                
                # Calculate median RGB for center
                sorted_r = sorted([p[0] for p in center_pixels])
                sorted_g = sorted([p[1] for p in center_pixels])
                sorted_b = sorted([p[2] for p in center_pixels])
                mid = len(center_pixels) // 2
                avg_r_c, avg_g_c, avg_b_c = sorted_r[mid], sorted_g[mid], sorted_b[mid]
                center_lum = int(0.299 * avg_r_c + 0.587 * avg_g_c + 0.114 * avg_b_c)
                
                # Robust Empty Detection:
                if center_lum >= empty_lum_threshold and stddev_gray < empty_stddev_threshold:
                    sampled_rgb = (avg_r_c, avg_g_c, avg_b_c)
                    closest_lvl = 0
                    min_dist = 0
                    method = "Empty"
                else:
                    # Step 2: Sample the dish background (the plate color).
                    # We sample a 5x3 grid in the lower-middle region (Y=65% to 75%).
                    dish_pixels = []
                    for fx in [0.35, 0.42, 0.50, 0.58, 0.65]:
                        for fy in [0.65, 0.70, 0.75]:
                            px = max(0, min(int(cell_left_px + fx * cell_w_px), w_b - 1))
                            py = max(0, min(int(cell_top_px + fy * cell_h_px), h_b - 1))
                            dish_pixels.append(rgb_img.getpixel((px, py)))
                    
                    # Robust color selection: use Median to filter out fish tail/fringe overlaps
                    sorted_r = sorted([p[0] for p in dish_pixels])
                    sorted_g = sorted([p[1] for p in dish_pixels])
                    sorted_b = sorted([p[2] for p in dish_pixels])
                    mid = len(dish_pixels) // 2
                    avg_r, avg_g, avg_b = sorted_r[mid], sorted_g[mid], sorted_b[mid]
                    sampled_rgb = (avg_r, avg_g, avg_b)

                    min_dist = float('inf')
                    closest_lvl = 0
                    for lvl, col in color_map.items():
                        if lvl == 0:
                            continue  # empty handled by luminance/stddev check
                        dist = (avg_r - col[0])**2 + (avg_g - col[1])**2 + (avg_b - col[2])**2
                        if dist < min_dist:
                            min_dist = dist
                            closest_lvl = lvl
                    method = "Dish"
                lum_info = f"Lum={center_lum} Std={stddev_gray:.1f}"

            else:
                # --- "level" mode ---
                # Tiles have solid background colors; text/numbers appear at the center.
                # Sample 4 inner patches at 25%/75% offsets to AVOID the central text.
                cell_left = c * cell_w
                cell_top = r * cell_h
                pts = []
                for fx, fy in [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]:
                    px = max(0, min(int(cell_left + fx * cell_w), w_b - 1))
                    py = max(0, min(int(cell_top + fy * cell_h), h_b - 1))
                    pts.append(rgb_img.getpixel((px, py)))
                avg_r = sum(p[0] for p in pts) // len(pts)
                avg_g = sum(p[1] for p in pts) // len(pts)
                avg_b = sum(p[2] for p in pts) // len(pts)
                sampled_rgb = (avg_r, avg_g, avg_b)
                lum_info = f"Std={stddev_gray:.0f}"

                min_dist = float('inf')
                closest_lvl = 0
                for lvl, col in color_map.items():
                    dist = (avg_r - col[0])**2 + (avg_g - col[1])**2 + (avg_b - col[2])**2
                    if dist < min_dist:
                        min_dist = dist
                        closest_lvl = lvl
                method = "Color"

            grid[r][c] = closest_lvl
            
            # Save cropped cell image (grayscale) if dataset collection is enabled
            if collect_ocr and ocr_dir and timestamp:
                cell_filename = f"cell_{timestamp}_{r}_{c}_lvl{closest_lvl}.png"
                cell_gray.save(os.path.join(ocr_dir, cell_filename))
                
            # Run pytesseract verification if available and requested
            ocr_text = ""
            if collect_ocr:
                try:
                    import pytesseract
                    ocr_text_raw = pytesseract.image_to_string(cell_gray, config='--psm 10 -c tessedit_char_whitelist=0123456789Lv.x').strip()
                    if ocr_text_raw:
                        ocr_text = f" | OCR='{ocr_text_raw}'"
                except Exception:
                    pass
                    
            row_debug.append(
                f"({r},{c}): cRGB={sampled_rgb} {lum_info} "
                f"-> Lvl {closest_lvl} [{method}] (dist={int(min_dist)}){ocr_text}"
            )
            
        print(" | ".join(row_debug))
        
    print("\nParsed Level Grid:")
    for r in range(4):
        print(f"  {grid[r]}")
    print("------------------------------------------")
    
    return grid
