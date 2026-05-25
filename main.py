# main.py
import sys
import os
import argparse
import unittest

def run_tests():
    print("=== Running Unit Test Suite ===")
    root_dir = os.path.dirname(os.path.abspath(__file__))
    # Discover all split tests in the tests/ directory
    suite = unittest.defaultTestLoader.discover(
        os.path.join(root_dir, "tests"), 
        pattern="test_*.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

def run_gui():
    print("=== Launching PyQt6 GUI Solver ===")
    import src.gui as gui
    gui.main()

def run_history():
    print("=== Launching Move History Viewer ===")
    import src.view_history as view_history
    view_history.main()

def main():
    parser = argparse.ArgumentParser(description="Solver 2048d helper utility")
    parser.add_argument("--test", action="store_true", help="Run the automated unit tests instead of launching the GUI")
    parser.add_argument("--history", action="store_true", help="Launch the interactive move history viewer")
    args = parser.parse_args()
    
    if args.test:
        run_tests()
    elif args.history:
        run_history()
    else:
        run_gui()

if __name__ == "__main__":
    main()
