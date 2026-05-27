# test_parser.py
import unittest
import os
import sys
import json
import tempfile
from PIL import Image

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src import image_parser
from src import game_engine

class TestImageParser(unittest.TestCase):
    def setUp(self):
        self.config = game_engine.config
        from src.image_parser import load_capture_config
        self.config['capture'] = load_capture_config()
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
            },
            {
                "name": "sample3.png",
                "ground_truth": [
                    [2, 0, 3, 7],
                    [0, 1, 3, 4],
                    [0, 0, 1, 3],
                    [0, 0, 0, 0]
                ]
            }
            # Add more samples here:
            # { "name": "sample2.png", "ground_truth": [...] }
        ]
        
        # Load dynamic samples if they exist
        tests_dir = os.path.dirname(__file__)
        dynamic_path = os.path.join(tests_dir, "dynamic_samples.json")
        if os.path.exists(dynamic_path):
            try:
                with open(dynamic_path, "r") as f:
                    dynamic_data = json.load(f)
                    self.samples.extend(dynamic_data)
            except Exception as e:
                print(f"Error loading dynamic samples: {e}")

    def _configure_sample(self, sample, img_path, template_matching=False, template_dir=None,
                          template_match_policy="dominant"):
        with Image.open(img_path) as img:
            w, h = img.size

        self.config['capture']['crop_x'] = 0
        self.config['capture']['crop_y'] = 0
        self.config['capture']['crop_w'] = w
        self.config['capture']['crop_h'] = h

        # Keep high-level calibrated colors from the capture config, but pin the
        # canonical low-level palette so tests are stable across local machines.
        from src.image_parser import X_CANONICAL_COLORS
        test_colors = self.config['capture'].get('colors_x', {}).copy()
        for k, v in X_CANONICAL_COLORS.items():
            test_colors[str(k)] = list(v)
        self.config['capture']['colors_x'] = test_colors

        self.config['capture']['mode'] = sample.get("mode", "x")
        self.config['capture']['template_matching'] = template_matching
        self.config['capture']['template_match_policy'] = template_match_policy
        if template_dir is not None:
            self.config['capture']['template_dir'] = template_dir

    def _run_samples(self, samples, label, template_matching=False, template_dir=None,
                     template_match_policy="dominant"):
        tests_dir = os.path.dirname(__file__)
        results = []
        failed_samples = []

        print("\n" + "="*50)
        print(f"IMAGE PARSER VALIDATION REPORT: {label}")
        print("="*50)

        for sample in samples:
            img_path = os.path.join(tests_dir, sample["name"])
            if not os.path.exists(img_path):
                print(f"\n❌ {sample['name']}: file not found!")
                results.append(False)
                failed_samples.append(f"{sample['name']}: file not found")
                continue

            orig_crop = self.config['capture'].copy()
            try:
                self._configure_sample(
                    sample,
                    img_path,
                    template_matching,
                    template_dir,
                    template_match_policy,
                )

                import time
                start_time = time.perf_counter()
                parsed_grid = image_parser.parse_screenshot(img_path)
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                gt = sample["ground_truth"]
                mismatches = []
                if parsed_grid is None:
                    mismatches.append("parser returned None")
                else:
                    for r in range(4):
                        for c in range(4):
                            if parsed_grid[r][c] != gt[r][c]:
                                mismatches.append(f"({r},{c}): expected {gt[r][c]}, got {parsed_grid[r][c]}")

                if not mismatches:
                    print(f"\n✅ {sample['name']}: perfect match! ({elapsed_ms:.1f} ms)")
                    results.append(True)
                else:
                    print(f"\n❌ {sample['name']}: {len(mismatches)} mismatch(es) found. ({elapsed_ms:.1f} ms)")
                    for m in mismatches:
                        print(f"   - {m}")
                    results.append(False)
                    failed_samples.append(f"{sample['name']}: " + "; ".join(mismatches))
            finally:
                self.config['capture'] = orig_crop

        print("\n" + "="*50)
        passed = sum(results)
        total = len(results)
        print(f"SUMMARY: {passed}/{total} boards passed.")
        print("="*50 + "\n")
        self.assertEqual(passed, total, "\n".join(failed_samples))

    def test_color_palette_samples(self):
        color_samples = [
            sample for sample in self.samples
            if max(max(row) for row in sample["ground_truth"]) <= 8
        ]
        self._run_samples(color_samples, "color palette", template_matching=False)

    def test_template_matching_samples(self):
        tests_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(prefix="solver2048d_templates_") as template_dir:
            orig_crop = self.config['capture'].copy()
            try:
                for sample in self.samples:
                    if sample.get("mode", "x") != "x":
                        continue
                    img_path = os.path.join(tests_dir, sample["name"])
                    if not os.path.exists(img_path):
                        continue
                    self._configure_sample(sample, img_path, template_matching=False, template_dir=template_dir)
                    image_parser.collect_x_template_samples(
                        img_path,
                        sample["ground_truth"],
                        self.config['capture'],
                    )
            finally:
                self.config['capture'] = orig_crop

            self._run_samples(
                self.samples,
                "template matching",
                template_matching=True,
                template_dir=template_dir,
            )

    def test_mixed_ambiguous_template_samples(self):
        tests_dir = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory(prefix="solver2048d_templates_") as template_dir:
            orig_crop = self.config['capture'].copy()
            try:
                for sample in self.samples:
                    if sample.get("mode", "x") != "x":
                        continue
                    img_path = os.path.join(tests_dir, sample["name"])
                    if not os.path.exists(img_path):
                        continue
                    self._configure_sample(sample, img_path, template_matching=False, template_dir=template_dir)
                    image_parser.collect_x_template_samples(
                        img_path,
                        sample["ground_truth"],
                        self.config['capture'],
                    )
            finally:
                self.config['capture'] = orig_crop

            self._run_samples(
                self.samples,
                "mixed ambiguous template",
                template_matching=True,
                template_dir=template_dir,
                template_match_policy="ambiguous",
            )

if __name__ == "__main__":
    unittest.main()
