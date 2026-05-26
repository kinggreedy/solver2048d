# image_parser.py
from PIL import Image, ImageStat
import colorsys
import os
import statistics
from src import game_engine

# X/multiplier mode uses illustrated dishes, fish, and text instead of flat tile
# backgrounds. These points stay on the plate rim or exposed dish area across
# the current capture styles while avoiding most text and fish bodies.
X_PLATE_SAMPLE_POINTS = (
    (0.15, 0.35), (0.25, 0.35), (0.75, 0.35), (0.85, 0.35),
    (0.18, 0.48), (0.82, 0.48),
    (0.35, 0.70), (0.50, 0.70), (0.65, 0.70),
)

X_CANONICAL_COLORS = {
    0: (242, 227, 196),
    1: (238, 238, 238),  # x2 white dish
    2: (210, 205, 125),  # x4 yellow-green dish
    3: (105, 170, 90),   # x8 green dish
    4: (125, 200, 165),  # x16 teal dish
    5: (100, 155, 185),  # x32 blue dish
    6: (205, 120, 220),  # x64 purple dish
    7: (235, 140, 70),   # x128 orange dish
}

X_LABEL_ROI = (0.18, 0.54, 0.86, 0.93)
X_TEMPLATE_SIZE = (96, 48)
X_TEMPLATE_MIN_PIXELS = 32
X_TEMPLATE_MATCH_THRESHOLD = 0.40

def load_capture_config():
    """Loads configuration settings for screenshot capture."""
    config = game_engine.config
    if 'capture' in config and config['capture']:
        return config['capture']

    import yaml
    from src.paths import CAPTURE_CONFIG_PATH
    if os.path.exists(CAPTURE_CONFIG_PATH):
        try:
            with open(CAPTURE_CONFIG_PATH, "r") as f:
                data = yaml.safe_load(f) or {}
                if 'capture' in data:
                    return data['capture']
                return data
        except Exception as e:
            print(f"Error loading capture config from {CAPTURE_CONFIG_PATH}: {e}")
    return {}

def _median_rgb_at(img, x, y, radius=2):
    """Returns a small-patch median RGB while ignoring red debug grid pixels."""
    img_w, img_h = img.size
    pixels = []
    for py in range(max(0, y - radius), min(img_h, y + radius + 1)):
        for px in range(max(0, x - radius), min(img_w, x + radius + 1)):
            rgb = img.getpixel((px, py))
            if _is_debug_grid_pixel(rgb):
                continue
            pixels.append(rgb)

    if not pixels:
        return img.getpixel((x, y))

    return tuple(int(statistics.median(p[channel] for p in pixels)) for channel in range(3))

def _is_debug_grid_pixel(rgb):
    r, g, b = rgb
    return r > 220 and g < 90 and b < 90

def _rgb_to_hsv(rgb):
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return h * 360.0, s, v

def _classify_x_plate_sample(rgb, refs):
    """Classifies one x-mode plate sample into a level vote, or None to ignore."""
    if _is_debug_grid_pixel(rgb):
        return None

    hue, sat, val = _rgb_to_hsv(rgb)

    # Beige board/background pixels surround every dish and should not vote.
    if 32 <= hue <= 46 and sat <= 0.27 and val >= 0.80:
        return None

    # Dark outlines/shadows should not vote.
    if val < 0.50:
        return None

    # Find the nearest color level from refs (levels 1-11)
    min_dist = float('inf')
    closest_lvl = None
    for lvl in range(1, 12):
        if lvl in refs:
            ref = refs[lvl]
            dist = (rgb[0] - ref[0])**2 + (rgb[1] - ref[1])**2 + (rgb[2] - ref[2])**2
            if dist < min_dist:
                min_dist = dist
                closest_lvl = lvl

    if min_dist > 2500:
        return None

    return closest_lvl

def _nearest_color_level(rgb, color_map, include_empty=True):
    min_dist = float('inf')
    closest_lvl = 0
    for lvl, col in color_map.items():
        if not include_empty and lvl == 0:
            continue
        dist = (rgb[0] - col[0])**2 + (rgb[1] - col[1])**2 + (rgb[2] - col[2])**2
        if dist < min_dist:
            min_dist = dist
            closest_lvl = lvl
    return closest_lvl, min_dist

def _x_reference_colors(color_map):
    # Prefer calibrated/configured colors in color_map over canonical defaults
    refs = dict(X_CANONICAL_COLORS)
    for lvl, col in color_map.items():
        refs[lvl] = col
    return refs

def _classify_x_cell(rgb_img, cell_left_px, cell_top_px, cell_right_px, cell_bottom_px,
                     center_lum, stddev_gray, empty_lum_threshold, empty_stddev_threshold,
                     color_map):
    if center_lum >= empty_lum_threshold and stddev_gray < empty_stddev_threshold:
        center_x = (cell_left_px + cell_right_px) // 2
        center_y = (cell_top_px + cell_bottom_px) // 2
        return 0, rgb_img.getpixel((center_x, center_y)), "Empty", 0

    cell_w_px = cell_right_px - cell_left_px
    cell_h_px = cell_bottom_px - cell_top_px
    img_w, img_h = rgb_img.size
    
    # Get active reference colors prioritizing color_map
    refs = _x_reference_colors(color_map)

    votes = {lvl: 0 for lvl in range(1, 12)}
    voted_samples = {}

    for fx, fy in X_PLATE_SAMPLE_POINTS:
        px = max(0, min(int(cell_left_px + fx * cell_w_px), img_w - 1))
        py = max(0, min(int(cell_top_px + fy * cell_h_px), img_h - 1))
        sampled_rgb = _median_rgb_at(rgb_img, px, py)
        lvl = _classify_x_plate_sample(sampled_rgb, refs)
        if lvl is None:
            continue
        votes[lvl] += 1
        voted_samples.setdefault(lvl, []).append(sampled_rgb)

    best_votes = max(votes.values())
    if best_votes > 0:
        candidates = [lvl for lvl, count in votes.items() if count == best_votes]
        if len(candidates) == 1:
            closest_lvl = candidates[0]
        else:
            def avg_ref_distance(lvl):
                ref = refs.get(lvl, (0, 0, 0))
                samples = voted_samples.get(lvl, [])
                if not samples:
                    return float('inf')
                return sum(
                    (rgb[0] - ref[0])**2 + (rgb[1] - ref[1])**2 + (rgb[2] - ref[2])**2
                    for rgb in samples
                ) / len(samples)
            closest_lvl = min(candidates, key=avg_ref_distance)

        samples = voted_samples.get(closest_lvl, [])
        if samples:
            sampled_rgb = tuple(sum(rgb[channel] for rgb in samples) // len(samples) for channel in range(3))
        else:
            sampled_rgb = refs.get(closest_lvl, (0, 0, 0))
        return closest_lvl, sampled_rgb, "PlateVotes", best_votes

    # Fallback for future/unseen dish colors: use the old lower-middle color
    # sample, but compare against corrected x-mode references.
    dish_pixels = []
    for fx in [0.35, 0.42, 0.50, 0.58, 0.65]:
        for fy in [0.65, 0.70, 0.75]:
            px = max(0, min(int(cell_left_px + fx * cell_w_px), img_w - 1))
            py = max(0, min(int(cell_top_px + fy * cell_h_px), img_h - 1))
            dish_pixels.append(_median_rgb_at(rgb_img, px, py))

    sampled_rgb = tuple(int(statistics.median(rgb[channel] for rgb in dish_pixels)) for channel in range(3))
    closest_lvl, min_dist = _nearest_color_level(sampled_rgb, refs, include_empty=False)
    return closest_lvl, sampled_rgb, "ColorFallback", int(min_dist)

def _template_dir(cfg):
    from src.paths import LOGS_DIR
    return cfg.get('template_dir') or os.path.join(LOGS_DIR, "template_samples")

def _is_x_label_pixel(rgb):
    if _is_debug_grid_pixel(rgb):
        return False

    r, g, b = rgb
    hue, sat, val = _rgb_to_hsv(rgb)

    # Yellow label fill.
    if 35 <= hue <= 62 and sat >= 0.35 and val >= 0.55 and r >= 140 and g >= 105 and b <= 135:
        return True

    # Dark orange/brown outline around the label. The ROI keeps most fish pixels
    # out, and the normalized bounding box handles small crop-grid offsets.
    if 15 <= hue <= 45 and sat >= 0.35 and 0.25 <= val <= 0.82 and r >= 65 and g >= 35 and b <= 135:
        return True

    return False

def _x_label_mask(cell_img):
    cell_rgb = cell_img.convert("RGB")
    cell_w, cell_h = cell_rgb.size
    left = int(cell_w * X_LABEL_ROI[0])
    top = int(cell_h * X_LABEL_ROI[1])
    right = int(cell_w * X_LABEL_ROI[2])
    bottom = int(cell_h * X_LABEL_ROI[3])
    label_img = cell_rgb.crop((left, top, right, bottom))
    label_w, label_h = label_img.size

    mask = Image.new("L", (label_w, label_h), 0)
    mask_pixels = mask.load()
    active = []
    for y in range(label_h):
        for x in range(label_w):
            if _is_x_label_pixel(label_img.getpixel((x, y))):
                mask_pixels[x, y] = 255
                active.append((x, y))

    if len(active) < X_TEMPLATE_MIN_PIXELS:
        return None

    min_x = max(0, min(x for x, _ in active) - 4)
    max_x = min(label_w - 1, max(x for x, _ in active) + 4)
    min_y = max(0, min(y for _, y in active) - 4)
    max_y = min(label_h - 1, max(y for _, y in active) + 4)
    return mask.crop((min_x, min_y, max_x + 1, max_y + 1)).resize(
        X_TEMPLATE_SIZE,
        Image.Resampling.NEAREST,
    )

def _mask_similarity(mask_a, mask_b):
    intersection = 0
    union = 0
    for a, b in zip(mask_a, mask_b):
        a_on = a > 0
        b_on = b > 0
        if a_on or b_on:
            union += 1
            if a_on and b_on:
                intersection += 1
    return intersection / union if union else 0.0

_templates_deduplicated = False

def deduplicate_templates(root):
    if not os.path.isdir(root):
        return
    for dirname in os.listdir(root):
        if not dirname.startswith("lvl_"):
            continue
        level_dir = os.path.join(root, dirname)
        if not os.path.isdir(level_dir):
            continue
        # Get all png files
        files = sorted([
            os.path.join(level_dir, f)
            for f in os.listdir(level_dir)
            if f.lower().endswith(".png")
        ])
        
        kept_templates = []
        for p in files:
            try:
                mask = Image.open(p).convert("L").resize(X_TEMPLATE_SIZE, Image.Resampling.NEAREST)
                data = mask.tobytes()
            except Exception:
                try:
                    os.remove(p)
                except Exception:
                    pass
                continue
                
            if sum(1 for value in data if value > 0) < X_TEMPLATE_MIN_PIXELS:
                try:
                    os.remove(p)
                except Exception:
                    pass
                continue
                
            is_dup = False
            for kept_data in kept_templates:
                similarity = _mask_similarity(data, kept_data)
                if similarity >= 0.95:
                    is_dup = True
                    break
            
            if is_dup:
                try:
                    os.remove(p)
                    print(f"Deleted duplicate template: {p}")
                except Exception as e:
                    print(f"Error deleting duplicate template {p}: {e}")
            else:
                kept_templates.append(data)

def _load_x_templates(cfg):
    global _templates_deduplicated
    root = _template_dir(cfg)
    if not os.path.isdir(root):
        return {}

    if not _templates_deduplicated:
        try:
            deduplicate_templates(root)
        except Exception as e:
            print(f"Error deduplicating templates: {e}")
        _templates_deduplicated = True

    max_per_level = int(cfg.get('template_max_per_level', 40))
    templates = {}
    for dirname in sorted(os.listdir(root)):
        if not dirname.startswith("lvl_"):
            continue
        try:
            lvl = int(dirname[4:])
        except ValueError:
            continue

        level_dir = os.path.join(root, dirname)
        if not os.path.isdir(level_dir):
            continue

        files = [
            os.path.join(level_dir, filename)
            for filename in sorted(os.listdir(level_dir), reverse=True)
            if filename.lower().endswith(".png")
        ][:max_per_level]

        for path in files:
            try:
                mask = Image.open(path).convert("L").resize(X_TEMPLATE_SIZE, Image.Resampling.NEAREST)
                data = mask.tobytes()
            except Exception:
                continue
            if sum(1 for value in data if value > 0) >= X_TEMPLATE_MIN_PIXELS:
                templates.setdefault(lvl, []).append(data)

    return templates

def _match_x_template(cell_img, templates_by_level, threshold):
    if not templates_by_level:
        return None, 0.0

    mask = _x_label_mask(cell_img)
    if mask is None:
        return None, 0.0

    data = mask.tobytes()
    best_lvl = None
    best_score = 0.0
    for lvl, templates in templates_by_level.items():
        for template_data in templates:
            score = _mask_similarity(data, template_data)
            if score > best_score:
                best_score = score
                best_lvl = lvl

    if best_score >= threshold:
        return best_lvl, best_score
    return None, best_score

def _save_x_template_sample(cell_img, lvl, root, timestamp, r, c):
    if lvl <= 0:
        return False

    mask = _x_label_mask(cell_img)
    if mask is None:
        return False

    mask_data = mask.tobytes()
    active_pixel_count = sum(1 for value in mask_data if value > 0)
    if active_pixel_count < X_TEMPLATE_MIN_PIXELS:
        return False

    level_dir = os.path.join(root, f"lvl_{lvl}")
    if os.path.exists(level_dir):
        for filename in os.listdir(level_dir):
            if filename.lower().endswith(".png"):
                p = os.path.join(level_dir, filename)
                try:
                    existing_mask = Image.open(p).convert("L").resize(X_TEMPLATE_SIZE, Image.Resampling.NEAREST)
                    existing_data = existing_mask.tobytes()
                    similarity = _mask_similarity(mask_data, existing_data)
                    if similarity >= 0.95:
                        return False
                except Exception:
                    pass

    os.makedirs(level_dir, exist_ok=True)
    sample_path = os.path.join(level_dir, f"{timestamp}_{r}_{c}.png")
    mask.save(sample_path)
    return True

def collect_x_template_samples(image_path, grid, cfg=None):
    """Collects normalized x-label templates using a confirmed 4x4 level grid."""
    if cfg is None:
        cfg = load_capture_config()

    if not os.path.exists(image_path):
        return 0

    try:
        img = Image.open(image_path)
    except Exception:
        return 0

    crop_x = cfg.get('crop_x', 100)
    crop_y = cfg.get('crop_y', 500)
    crop_w = cfg.get('crop_w', 880)
    crop_h = cfg.get('crop_h', 880)
    img_w, img_h = img.size
    crop_x = max(0, min(crop_x, img_w - 1))
    crop_y = max(0, min(crop_y, img_h - 1))
    crop_w = max(1, min(crop_w, img_w - crop_x))
    crop_h = max(1, min(crop_h, img_h - crop_y))

    board_img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h)).convert("RGB")
    cell_w = crop_w / 4
    cell_h = crop_h / 4

    import datetime
    root = _template_dir(cfg)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    saved = 0
    for r in range(4):
        for c in range(4):
            lvl = grid[r][c]
            if lvl <= 0:
                continue

            cell_left = int(c * cell_w)
            cell_top = int(r * cell_h)
            cell_right = int((c + 1) * cell_w)
            cell_bottom = int((r + 1) * cell_h)
            cell_img = board_img.crop((cell_left, cell_top, cell_right, cell_bottom))
            if _save_x_template_sample(cell_img, lvl, root, timestamp, r, c):
                saved += 1

    return saved

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
    
    template_matching_enabled = bool(cfg.get('template_matching', False))
    template_root = _template_dir(cfg)
    template_threshold = float(cfg.get('template_match_threshold', X_TEMPLATE_MATCH_THRESHOLD))
    templates_by_level = _load_x_templates(cfg) if template_matching_enabled else {}
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
                **X_CANONICAL_COLORS,
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

                closest_lvl, sampled_rgb, method, min_dist = _classify_x_cell(
                    rgb_img,
                    cell_left_px,
                    cell_top_px,
                    cell_right_px,
                    cell_bottom_px,
                    center_lum,
                    stddev_gray,
                    empty_lum_threshold,
                    empty_stddev_threshold,
                    color_map,
                )

                if template_matching_enabled and closest_lvl > 0:
                    template_lvl, template_score = _match_x_template(
                        cell_crop.convert("RGB"),
                        templates_by_level,
                        template_threshold,
                    )
                    if template_lvl is not None:
                        # If the color path found a level that has no templates yet,
                        # trust color and collect that missing class instead of forcing
                        # a nearest-neighbor template from some other level.
                        if template_lvl == closest_lvl or closest_lvl in templates_by_level:
                            closest_lvl = template_lvl
                            method = "Template"
                            min_dist = template_score
                        else:
                            method = "PlateVotes+TemplateUnseeded"

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
            
            if method == "Template":
                metric_label = "sim"
                metric_value = f"{min_dist:.3f}"
            elif method.startswith("PlateVotes"):
                metric_label = "score"
                metric_value = str(int(min_dist))
            else:
                metric_label = "dist"
                metric_value = str(int(min_dist))
            row_debug.append(
                f"({r},{c}): cRGB={sampled_rgb} {lum_info} "
                f"-> Lvl {closest_lvl} [{method}] ({metric_label}={metric_value})"
            )
            
        print(" | ".join(row_debug))
        
    print("\nParsed Level Grid:")
    for r in range(4):
        print(f"  {grid[r]}")
    print("------------------------------------------")
    
    return grid
