# PROJECT SPECIFICATION

## Project context

We are building a helper/solver for a 2048-like 4x4 grid game with custom scoring and energy mechanics.

The player spends energy only on **valid swipes**. A valid swipe is a swipe that changes the board. If the board does not change, it is invalid, costs no energy, and does not spawn new random tiles.

The game supports multiplier modes. For the first implementation, support only:

* `x1`
* `x4`

Leave the architecture open for later adding:

* `x8`
* `x16`

The tool should be efficient enough for repeated manual use through a GUI on KDE Plasma remote desktop. The user will manually input the current board state by clicking cells. The solver then recommends the best move, whether to continue, and whether to use x1 or x4.

We are not trying to perfectly solve the game in this iteration. We want a strong practical solver that can later be improved with better statistics and deeper simulation.

---

## Game model

### Board

* Board size: `4 x 4`.
* Empty cell: `0`.
* Tile levels are integer levels.
* Level examples:

  * `1` corresponds to the lowest tile in x1 mode.
  * `2` corresponds to the high tile in x1 mode.
  * `3` / `4` are the x4 spawn levels.
* Maximum level: `11`.
* For this iteration, level `11` is treated as a **stone / terminal tile**.
* A level-11 tile cannot merge further.
* The game ends when no legal moves remain, or when the solver recommends restart/stop because the current board has lower expected value than starting a fresh game.

### Valid moves

A move can be one of:

* `UP`
* `DOWN`
* `LEFT`
* `RIGHT`

A move is valid only if it changes the board by moving or merging at least one tile.

After every valid move, random tiles spawn.

### Merge rule

Use standard 2048 merge semantics:

* A row/column compresses toward the swipe direction.
* Equal adjacent nonzero tiles merge once per move.
* A tile created by a merge cannot merge again in the same move.
* Two level-11 tiles do **not** merge in this iteration, because level 11 is a stone.

### Scoring

There are two point sources:

1. Appear points when random tiles spawn.
2. Merge points when tiles merge.

#### Appear points

| Level |            Appear points |
| ----: | -----------------------: |
|     1 |                        0 |
|     2 |                        1 |
|     3 |                        4 |
|     4 |                       12 |
|     5 |                       32 |
|     6 |                       80 |
|    7+ | 0 unless later confirmed |

For this iteration, only spawned levels need appear points. Since x1 and x4 are implemented first, this means levels 1-4.

#### Merge points

| Resulting level | Merge points |
| --------------: | -----------: |
|               1 |          N/A |
|               2 |            1 |
|               3 |            2 |
|               4 |            4 |
|               5 |            8 |
|               6 |           16 |
|               7 |           30 |
|               8 |           50 |
|               9 |          100 |
|              10 |          150 |
|              11 |          200 |

A merge from two level-10 tiles creates one level-11 stone and awards 200 points.

---

## Energy modes

For this iteration:

| Mode | Energy cost per valid action | Low spawn level | High spawn level |
| ---- | ---------------------------: | --------------: | ---------------: |
| x1   |                            1 |               1 |                2 |
| x4   |                            4 |               3 |                4 |

Later modes should be config-driven:

| Mode | Energy cost | Low spawn level | High spawn level |
| ---- | ----------: | --------------: | ---------------: |
| x8   |           8 |               4 |                5 |
| x16  |          16 |               5 |                6 |

Do not hard-code only x1/x4 in the solver core. Use a configuration table so x8/x16 can be added later.

---

## Spawn model

Use this assumed spawn distribution until real statistics are collected:

| Probability | Spawn event                           |
| ----------: | ------------------------------------- |
|         50% | 1 low-level tile                      |
|         35% | 2 low-level tiles                     |
|         15% | 2 low-level tiles + 1 high-level tile |

Therefore, each valid action produces on average:

* `1.5` low tiles
* `0.15` high tiles
* `1.65` total spawned tiles

Spawn cells should be chosen uniformly from currently empty cells, unless real data later proves otherwise.

If there are fewer empty cells than required by the sampled spawn event, use one of these policies and make it configurable:

1. **Truncated spawn policy**: spawn as many tiles as possible.
2. **Invalid event policy**: resample an event that fits.

Default to truncated spawn policy for the first implementation unless the observed game behavior says otherwise.

---

## User input GUI

The user manually inputs the board through a clickable 4x4 grid.

### Cell click behavior

For each cell:

* Empty cell starts at `0`.
* Left click once on an empty cell sets it to the mode's low level by default.
* Left click again advances it to the mode's high level.
* Third click and above increments the level by `+1` each time.
* Right click clears the cell to `0`.

Recommended implementation detail:

* The input widget should not depend too strongly on the current mode.
* A simple cycle is acceptable:

  * `0 -> 1 -> 2 -> 3 -> ... -> 11 -> 0`
* But also support quick-entry behavior:

  * if current selected mode is x1: first click gives level 1, second gives level 2.
  * if current selected mode is x4: first click gives level 3, second gives level 4.

### Statistics helper input

The user may input only the newly spawned cells after each move, often 1 or 2 cells.

The helper should record these observations independently of the solver, so we can later estimate the real spawn distribution.

Record at minimum:

* timestamp
* selected mode
* number of new cells observed
* levels of new cells
* empty-cell count before spawn if known
* board before spawn if known
* board after spawn if known

If the user only enters partial spawn data, still record it as a partial observation.

The statistics module should be able to compute:

* count of observed spawn events
* distribution of spawn count: 1 / 2 / 3 / other
* distribution of low vs high tiles by mode
* empirical probability of high tile
* confidence warning when sample size is small

The solver config should be able to switch from assumed probabilities to empirical probabilities later.

---

## Solver outputs

Each time the board is evaluated, output three things:

### 1. Best action

Recommend one move among:

* `UP`
* `DOWN`
* `LEFT`
* `RIGHT`

Also show runner-up moves and approximate values if cheap to compute.

Display:

* best move
* expected points
* expected points per energy
* estimated survival / risk score
* reason summary, such as:

  * preserves corner chain
  * creates many empty cells
  * merges high tiles
  * avoids isolating stones

### 2. Continue / restart decision

The old threshold `> 2 points per energy` only compares against direct energy-to-point conversion. It is not enough, because unused energy can be spent on a fresh new game.

The correct rule is:

```text
Continue current board if:
    best_current_board_value_per_energy >= fresh_game_baseline_value_per_energy
Otherwise:
    recommend restart / stop current game
```

The fresh-game baseline should be learned or estimated.

Initial default baseline:

```text
fresh_game_baseline_value_per_energy = 6.0
```

Make this configurable.

Also show comparison against direct conversion:

```text
direct_conversion_value_per_energy = 2.0
```

This gives three possible interpretations:

* Below 2.0: do not play; direct conversion is better.
* Between 2.0 and fresh baseline: current board is still positive value, but restarting is better.
* Above fresh baseline: continue this board.

### 3. Mode recommendation

For this iteration, compare:

* x1
* x4

Recommend the mode with the highest expected value per energy on the current board.

Expected common behavior:

* Clean board: usually x1.
* Damaged board / low future merge confidence: x4 may become better.
* If x4 creates too much clogging, x1 remains better.

Do not hard-lock this behavior. Let simulation decide.

---

## Solver algorithm

The first implementation should NOT rely purely on brute-force Monte Carlo.

Use a hybrid architecture inspired by strong historical 2048 solvers.

Recommended architecture:

```text
fast move engine
+ expectimax search
+ transposition table / memoization
+ heuristic evaluator
+ optional Monte Carlo rollout fallback
```

The classic 2048 AI ecosystem already demonstrated that this structure is extremely fast and effective on a 4x4 board.

This project should reuse the important ideas from historical 2048 solvers while adapting them to:

* variable spawn count (1-3 tiles)
* mode-dependent spawn levels
* custom scoring
* level-11 stones
* continue/restart logic
* mode switching between x1/x4/x8/x16

### Search strategy

Recommended first implementation:

1. Enumerate legal player moves.
2. Enumerate or sample spawn outcomes.
3. Evaluate resulting states recursively.
4. Use heuristic evaluation at depth cutoff.
5. Use memoization/transposition tables aggressively.

Recommended initial search:

```text
expectimax depth: 3-5
```

Because the spawn branching factor can become large (up to 3 spawned cells), the solver may:

* fully enumerate small spawn sets
* sample spawn outcomes when branching becomes too large
* prune clearly dominated states
* cache board evaluations aggressively

The solver should prefer fast iterative evaluations over extremely deep exhaustive search.

### Memoization / transposition tables

Memoization is required.

At minimum implement:

```text
move_cache[(board, direction)]
    -> new_board, merge_score, valid

legal_moves_cache[board]
    -> valid_moves

heuristic_cache[board]
    -> heuristic_score
```

Later optional caches:

```text
EV_cache[(board, depth, mode)]
spawn_cache[(board, mode)]
```

The solver should avoid recomputing identical board transitions repeatedly.

### Bitboard recommendation

Strongly recommended for performance:

Represent the board as a compact integer bitboard, similar to historical 2048 solvers.

Suggested encoding:

* 4 bits per cell is sufficient for levels 0-15.
* Entire 4x4 board fits inside a 64-bit integer.

Benefits:

* fast hashing
* fast memoization keys
* compact copies
* efficient row/column lookup tables
* SIMD-friendly future optimizations

Recommended optimization approach:

* precompute all row move transitions
* precompute row scores
* use lookup tables for row transforms

This was one of the key optimizations in strong classic 2048 implementations.

### Heuristic evaluation

The heuristic evaluator is extremely important.

Core features:

* empty cell count
* monotonicity
* smoothness
* merge potential
* corner stability
* stone penalty
* unreachable tile penalty
* chain preservation
* future mobility

The heuristic should estimate:

```text
future_realization_probability
```

which approximates how much future merge value can realistically still be realized before the board collapses.

### Monte Carlo fallback

Monte Carlo rollout remains useful as:

* tie-breaker
* uncertainty estimator
* robustness checker
* later experimentation mode

But the first implementation should prioritize:

```text
expectimax + heuristics + memoization
```

instead of pure random rollouts.

### Search budget

Use configurable budgets:

```yaml
simulation:
  rollouts_per_action: 200
  rollout_depth: 8
  max_time_ms: 1000
```

For interactive use, prefer time-bounded search over fixed huge rollout counts.

The solver should return quickly, then optionally refine if implemented later.

### Rollout policy

For rollout moves, do not use random moves only. Use a light policy based on board heuristics.

Candidate heuristic features:

* number of empty cells
* number of legal moves
* immediate merge score
* monotonicity / snake-chain shape
* smoothness: adjacent similar levels are good
* max tile / stone placement in corner
* number of stones
* number of unreachable or isolated tiles
* merge potential by level
* penalty for breaking the main chain

Recommended board shape heuristic:

* Prefer keeping high tiles in one corner.
* Prefer a snake-like descending order from that corner.
* Penalize high tiles isolated away from the chain.
* Penalize stones outside the stable corner/edge.

### Terminal handling

Terminal board states:

* no legal moves
* too many stones/unreachable tiles and EV below baseline
* optional user-requested restart

Because level 11 is a stone, the solver should heavily penalize creating stones unless the point reward and board position justify it.

---

## Approximate value model

The solver should not rely only on handcrafted thresholds, but thresholds are useful as fallback and for explainability.

### Perfect lifetime value

Under the theoretical assumption that all spawned tiles eventually merge up to level 11, the modes have similar value per energy. Real gameplay differs because tiles become stranded.

Therefore real value should be modeled as:

```text
real_value = immediate_value + future_merge_value * realization_probability
```

Where realization probability is estimated from board quality.

### Board-quality based realization estimate

Use this as an initial simple fallback if Monte Carlo rollout is disabled or too shallow:

```text
realization_probability = clamp(
    1.00
    - 0.10 * stone_count
    - 0.08 * unreachable_tile_count
    - 0.05 * isolated_tile_count
    - 0.04 * low_empty_cell_penalty
    - 0.03 * broken_monotonicity_penalty,
    0.0,
    1.0
)
```

This formula is intentionally rough. The Monte Carlo result should be preferred when available.

### Unreachable tile definition

A tile can be considered unreachable/stranded if:

* it has no same-level tile in its connected merge-accessible region, and
* it is not adjacent to a plausible future chain position, and
* moving it toward the main chain would require breaking high-value structure.

For the first implementation, approximate unreachable count with simpler signals:

* Count tiles that have no same-level neighbor and no same-level tile in the same row or column.
* Add penalty if the tile is high level and far from the main chain/corner.
* Count stones not on the preferred corner/edge as highly unreachable.

---

## Stop / restart rule

Use this decision hierarchy:

```text
best_option = max over enabled modes and legal moves of EV_per_energy

if no legal moves:
    GAME_OVER
elif best_option < direct_conversion_value_per_energy:
    STOP_AND_CONVERT
elif best_option < fresh_game_baseline_value_per_energy:
    RESTART_GAME
else:
    CONTINUE
```

Default constants:

```yaml
direct_conversion_value_per_energy: 2.0
fresh_game_baseline_value_per_energy: 6.0
```

The fresh baseline should later be calibrated from actual completed games.

---

## Data logging

Log every solver evaluation and user outcome so the system can improve.

Recommended logs:

### Board evaluation log

* timestamp
* board state
* enabled modes
* selected mode
* recommended move
* alternative move values
* estimated EV per energy
* decision: continue/restart/convert
* heuristic features
* simulation budget used

### Move result log

* board before move
* move taken
* mode used
* whether move was valid
* merge score observed
* spawned cells observed
* board after spawn

### Game summary log

* total valid moves
* total energy spent
* total points earned
* final board
* max level reached
* number of stones created
* restart reason

Use JSON Lines (`.jsonl`) for easy append-only logging.

---

## Implemented implementation structure

Our actual implementation utilizes a flatter, highly modular structure for simplicity, reliability, and fast imports in the remote desktop environment:

```text
project/
  PROJECT_INSTRUCTION.md
  README.md
  config.yaml
  main.py
  game_engine.py
  solver.py
  stats.py
  gui.py
  view_history.py
  tests.py
```

### `game_engine.py`

Responsibilities:
* Bitboard manipulation (compact 64-bit board representation).
* Fast lookup tables (`ROW_LEFT_TABLE`, `ROW_SCORE_TABLE`, `ROW_VALID_TABLE`, `ROW_REVERSE_TABLE`) precomputed on import for $O(1)$ shifts.
* Merge rules (incorporating the configurable level-11 stone constraint where stones cannot merge).
* Appear/merge scoring.
* Spawn outcomes enumeration based on configuration probabilities and policies (truncated vs invalid event).

### `solver.py`

Responsibilities:
* Expectimax search algorithm with depth cutoffs.
* Dynamic depth selection based on board fullness.
* Caching / memoization of heuristic scores.
* Heuristic board evaluation (exponential tile value scaling, smoothness, monotonicity templates, corner anchoring, unreachable/isolated tile penalties, and stone penalties).
* Compare modes (e.g. x1 vs x4) based on expected value per energy cost.
* Continue/restart/stop decision hierarchy.

### `stats.py`

Responsibilities:
* Appending JSONL logs for board evaluations, move results, and game summaries.
* Tracking manual spawn observations to build empirical spawn probability distributions.

### `gui.py`

Responsibilities:
* Dark-themed PyQt6 GUI mapping the manual grid entry, swipe controls, undo stack, recommendations panel, and double-confirmation warning for empty spawns.

### `view_history.py`

Responsibilities:
* An interactive GUI or terminal-based tool that loads the move results history and lets users step through past games and analyze individual decisions.

### `tests.py`

Responsibilities:
* Complete unit test suite (16 tests) verifying basic merges, stones, spawn bounds, crash resistance, restart logic, and seeded step-by-step game simulations.

### `main.py`

Responsibilities:
* Single entry point to either run unit tests (`--test`), run the GUI (`python3 main.py`), or run the history viewer (`--history`).

---

## Testing requirements

Before tuning the solver, implement correctness tests.

Required tests:

1. Moving left merges `[1,1,1,0]` into `[2,1,0,0]`, with one level-2 merge score.
2. Moving left merges `[1,1,1,1]` into `[2,2,0,0]`, not `[3,0,0,0]`.
3. Level-11 tiles do not merge.
4. Invalid moves are detected and cost no energy.
5. x1 spawn events create only levels 1 and 2.
6. x4 spawn events create only levels 3 and 4.
7. Spawn distribution approximately matches configured probabilities after many samples.
8. Solver returns only valid moves.
9. Solver can evaluate a nearly full board without crashing.
10. Restart decision triggers when estimated EV is below fresh baseline.

---

## First milestone

Build a working local prototype that can:

1. Accept a manually clicked 4x4 board.
2. Evaluate all valid moves for x1 and x4.
3. Recommend best move.
4. Recommend x1 or x4.
5. Recommend continue/restart/convert.
6. Log board evaluations and spawn observations.
7. Run basic tests for rules and scoring.

Do not over-optimize the first version. Correct rules, clean config, and good logging are more important than perfect play.

---

## Important design principle

Keep the solver configurable.

The following should live in config, not hard-coded constants:

* max level
* whether max merges or becomes stone
* mode definitions
* spawn probabilities
* scoring tables
* direct conversion value
* fresh game baseline
* simulation budget
* heuristic weights

This is important because the exact game mechanics and spawn statistics are not fully known yet.
