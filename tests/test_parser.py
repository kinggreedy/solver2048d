# tests/test_parser.py
import unittest
import os
from PIL import Image, ImageDraw
from src import game_engine
from src import image_parser

class TestParser(unittest.TestCase):
    def setUp(self):
        self.config = game_engine.config

    def test_18_image_parsing(self):
        """Verify that image_parser correctly parses a board screenshot with center noise."""
        orig_capture = self.config.get('capture')
        self.config['capture'] = {
            'enabled': True,
            'port': 5000,
            'crop_x': 100,
            'crop_y': 100,
            'crop_w': 800,
            'crop_h': 800,
            'colors': {
                0: [46, 46, 56],
                1: [79, 172, 254],
                2: [0, 242, 254],
                3: [76, 175, 80],
                4: [0, 230, 118],
                5: [255, 235, 59],
                6: [255, 152, 0],
                7: [255, 87, 34],
                8: [244, 67, 54],
                9: [213, 0, 249],
                10: [101, 31, 255],
                11: [55, 71, 79]
            }
        }
        
        try:
            # Create a 1000x1000 dummy screenshot
            img = Image.new("RGB", (1000, 1000), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Target grid
            target_grid = [
                [0, 1, 2, 3],
                [4, 5, 6, 7],
                [8, 9, 10, 11],
                [1, 0, 1, 0]
            ]
            
            colors = self.config['capture']['colors']
            cell_size = 200
            
            for r in range(4):
                for c in range(4):
                    level = target_grid[r][c]
                    col = tuple(colors[level])
                    
                    left = 100 + c * cell_size
                    top = 100 + r * cell_size
                    right = left + cell_size
                    bottom = top + cell_size
                    
                    # Fill cell background (leaving a 10px black border)
                    draw.rectangle([left + 10, top + 10, right - 10, bottom - 10], fill=col)
                    
                    # Add noise in the exact center to simulate numbers/emojis (e.g. a white circle)
                    center_x = (left + right) // 2
                    center_y = (top + bottom) // 2
                    draw.ellipse([center_x - 15, center_y - 15, center_x + 15, center_y + 15], fill=(255, 255, 255))
            
            temp_path = "temp_test_screenshot.png"
            img.save(temp_path)
            
            parsed_grid = image_parser.parse_screenshot(temp_path)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            self.assertEqual(parsed_grid, target_grid, "Parsed grid does not match expected target grid.")
        finally:
            if orig_capture is not None:
                self.config['capture'] = orig_capture
            else:
                del self.config['capture']

if __name__ == '__main__':
    unittest.main()
