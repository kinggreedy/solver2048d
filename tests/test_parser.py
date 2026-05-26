# test_parser.py
import unittest
import os
import sys
from PIL import Image

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src import image_parser
from src import game_engine

class TestImageParser(unittest.TestCase):
    def setUp(self):
        self.config = game_engine.config
        self.samples = [
            {
                "name": "sample1.png",
                "ground_truth": [
                    [0, 0, 3, 3],
                    [0, 3, 5, 6],
                    [0, 1, 2, 1],
                    [0, 1, 0, 0]
                ]
            },
            {
                "name": "sample2.png",
                "ground_truth": [
                    [0, 1, 5, 6],
                    [0, 3, 5, 3],
                    [0, 0, 2, 1],
                    [1, 0, 2, 1]
                ]
            }
            # Add more samples here:
            # { "name": "sample2.png", "ground_truth": [...] }
        ]

    def test_all_samples(self):
        tests_dir = os.path.dirname(__file__)
        results = []
        
        print("\n" + "="*50)
        print("IMAGE PARSER VALIDATION REPORT")
        print("="*50)

        for sample in self.samples:
            img_path = os.path.join(tests_dir, sample["name"])
            if not os.path.exists(img_path):
                print(f"\n❌ {sample['name']}: file not found!")
                results.append(False)
                continue

            # Mock crop settings for the test board
            img = Image.open(img_path)
            w, h = img.size
            orig_crop = self.config['capture'].copy()
            
            try:
                self.config['capture']['crop_x'] = 0
                self.config['capture']['crop_y'] = 0
                self.config['capture']['crop_w'] = w
                self.config['capture']['crop_h'] = h
                
                import time
                start_time = time.perf_counter()
                parsed_grid = image_parser.parse_screenshot(img_path)
                end_time = time.perf_counter()
                elapsed_ms = (end_time - start_time) * 1000

                gt = sample["ground_truth"]
                
                board_match = True
                mismatches = []
                for r in range(4):
                    for c in range(4):
                        if parsed_grid[r][c] != gt[r][c]:
                            board_match = False
                            mismatches.append(f"({r},{c}): expected {gt[r][c]}, got {parsed_grid[r][c]}")

                if board_match:
                    print(f"\n✅ {sample['name']}: perfect match! ({elapsed_ms:.1f} ms)")
                    results.append(True)
                else:
                    print(f"\n❌ {sample['name']}: {len(mismatches)} mismatch(es) found. ({elapsed_ms:.1f} ms)")
                    for m in mismatches:
                        print(f"   - {m}")
                    results.append(False)
                    
            finally:
                self.config['capture'] = orig_crop

        print("\n" + "="*50)
        passed = sum(results)
        total = len(results)
        print(f"SUMMARY: {passed}/{total} boards passed.")
        print("="*50 + "\n")

if __name__ == "__main__":
    unittest.main()
