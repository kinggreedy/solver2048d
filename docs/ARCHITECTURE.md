# Architecture & Solver Design - Solver 2048d

This document describes the underlying design, board representation, heuristics, and search algorithms of the `solver2048d` utility.

---

## 1. Game Mechanics

`solver2048d` is a helper for a custom 4x4 grid 2048-like game with these rules:
- **Energy Costs**: Valid swipes cost energy (defined per mode in `config.yaml`). Invalid swipes (swipes that do not change the board) cost 0 energy and trigger no tile spawns.
- **Merge Restrictions**: Level-11 tiles act as **stones**. They cannot merge further (two 11s do not merge).
- **Spawn Rules**: Multiple low-level or high-level tiles can spawn simultaneously depending on the multiplier mode (`x1`, `x4`, etc.).

---

## 2. Board Representation & Bitboards

To perform deep search trees within milliseconds, the board is represented as a single **64-bit unsigned integer**:
- Each of the 16 cells is allocated **4 bits** (representing level levels from `0` to `15`).
- The 16-bit row representations are used as indices for precomputed lookup tables (`ROW_LEFT_TABLE`, `ROW_SCORE_TABLE`, etc.) to perform swipe transitions and scoring in $O(1)$ time.
- All cell manipulations are implemented using bitwise shifts and masks in `src/game_engine.py`.

---

## 3. Heuristics & Board Evaluation

The board evaluator (`src/solver.py`) judges board quality using several heuristics weights:
- **Monotonicity**: Evaluates if tile values decrease along a snake-like path towards a chosen corner. Keeping high tiles anchored in a corner ensures they are always available for merges.
- **Smoothness**: Penalizes adjacent cells with large level differences, minimizing gaps and isolated tiles.
- **Empty Cells**: Heavily weights keeping cells empty to preserve maneuverability.
- **Stone Penalties**: Actively penalizes placement of level-11 stones in critical corner anchors, as they block merges.
- **Unreachable Cell Penalties**: Penalizes structures that block access to lower-value merging tiles.

---

## 4. Expectimax Search & Decision Tree

- **Expectimax Algorithm**: Recursively searches the game tree. Maximizes choices for player moves, and averages outcomes for random spawns based on configured probabilities.
- **Memoization & Transposition Tables**: Cache evaluation results for quick reuse across different search branches.
- **Dynamic Search Depth**: Dynamically matches search depth based on board density (e.g. searching deeper when board has many empty cells and shallowing up when near full).
- **Monte Carlo Rollout Fallback**: Runs MC simulations on close-scoring moves to determine the highest survivability.
- **Decision Engine**: Compares the expected value (EV) per energy of the current board against a fresh game baseline. If the current board's potential is lower than starting over, the solver recommends `RESTART_GAME`.
