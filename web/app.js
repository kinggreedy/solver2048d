/**
 * 2048 Expectimax Solver - App Controller (Qt Styled)
 */

class App {
    constructor() {
        this.grid = Array(4).fill().map(() => Array(4).fill(0));
        this.history = [];
        this.worker = null;
        this.isSolving = false;
        
        // Game states matching Qt
        this.guiState = "NORMAL"; // "NORMAL" or "WAITING_FOR_SPAWN"
        this.boardBeforeMove = 0;
        this.boardAfterMoveNoSpawn = 0;
        
        // Game stats matching Qt app
        this.score = 0;
        this.energy = 0;
        this.moves = 0;

        this.init();
    }

    async init() {
        this.setupDOM();
        await this.initWorker();
        this.newGame();
        this.bindEvents();
        this.hideLoader();
    }

    setupDOM() {
        this.gridContainer = document.getElementById('grid-container');
        
        // Stats
        this.scoreEl = document.getElementById('score-val');
        this.energyEl = document.getElementById('energy-val');
        this.movesEl = document.getElementById('moves-val');
        this.efficiencyEl = document.getElementById('efficiency-val');
        
        // Solver Recommendation
        this.recDirEl = document.getElementById('rec-dir');
        this.decisionBadge = document.getElementById('decision-badge');
        this.evValEl = document.getElementById('ev-val');
        this.evEnergyValEl = document.getElementById('ev-energy-val');
        this.survivalFill = document.getElementById('survival-fill');
        this.reasonsBox = document.getElementById('reasons-box');
        
        // Status
        this.statusBanner = document.getElementById('status-banner');
        
        // Settings
        this.depthSelect = document.getElementById('depth-select');
        this.modeSelect = document.getElementById('mode-select');
        this.timeSelect = document.getElementById('time-select');
        this.chkX8 = document.getElementById('chk-x8');
        this.chkX16 = document.getElementById('chk-x16');
        this.chkEmpirical = document.getElementById('chk-empirical');
        
        // Buttons
        this.solveBtn = document.getElementById('solve-btn');
        this.resetBtn = document.getElementById('reset-btn');
        this.newGameBtn = document.getElementById('new-game-btn');
        this.undoBtn = document.getElementById('undo-btn');
        this.confirmSpawnBtn = document.getElementById('confirm-spawn-btn');
        this.applyRecBtn = document.getElementById('apply-rec');
        
        // Move buttons
        this.moveLeftBtn = document.getElementById('move-left');
        this.moveRightBtn = document.getElementById('move-right');
        this.moveUpBtn = document.getElementById('move-up');
        this.moveDownBtn = document.getElementById('move-down');
    }

    async initWorker() {
        const loaderText = document.getElementById('loader-text');
        loaderText.textContent = "Loading Python Files...";
        
        const filesToLoad = [
            'src/__init__.py',
            'src/game_engine.py',
            'src/solver.py',
            'src/paths.py',
            'src/web_solver.py',
            'config.yaml'
        ];

        const fileContents = {};
        for (const f of filesToLoad) {
            try {
                const response = await fetch(`../${f}`);
                fileContents[f] = await response.text();
            } catch (e) {
                console.error(`Failed to load ${f}`, e);
            }
        }

        loaderText.textContent = "Initializing Pyodide...";
        this.worker = new Worker('worker.js');
        
        return new Promise((resolve) => {
            this.worker.onmessage = (e) => {
                const { type, result, error } = e.data;
                if (type === 'ready') {
                    console.log("Worker ready");
                    resolve();
                } else if (type === 'solve_result') {
                    this.handleSolveResult(result);
                } else if (type === 'error') {
                    console.error("Worker error:", error);
                    this.statusBanner.textContent = `ERROR: ${error}`;
                    this.statusBanner.style.backgroundColor = "#b71c1c";
                    this.statusBanner.style.color = "#ffffff";
                }
            };

            this.worker.postMessage({
                type: 'init',
                payload: { files: fileContents }
            });
        });
    }

    bindEvents() {
        this.solveBtn.onclick = () => this.solve();
        this.resetBtn.onclick = () => this.resetBoard();
        this.newGameBtn.onclick = () => this.newGame();
        this.undoBtn.onclick = () => this.undo();
        this.confirmSpawnBtn.onclick = () => this.confirmSpawn();
        this.applyRecBtn.onclick = () => this.executeRecommendedMove();
        
        this.moveLeftBtn.onclick = () => this.executeMove(0);
        this.moveRightBtn.onclick = () => this.executeMove(1);
        this.moveUpBtn.onclick = () => this.executeMove(2);
        this.moveDownBtn.onclick = () => this.executeMove(3);

        // Keyboard support
        window.onkeydown = (e) => {
            if (this.guiState === "WAITING_FOR_SPAWN") {
                if (e.key === "Enter") this.confirmSpawn();
                return;
            }
            if (e.key === 'ArrowLeft') this.executeMove(0);
            if (e.key === 'ArrowRight') this.executeMove(1);
            if (e.key === 'ArrowUp') this.executeMove(2);
            if (e.key === 'ArrowDown') this.executeMove(3);
        };

        // Rerender when settings change to update solver
        this.modeSelect.onchange = () => this.solve();
        this.depthSelect.onchange = () => this.solve();
        this.timeSelect.onchange = () => this.solve();
        this.chkX8.onchange = () => this.solve();
        this.chkX16.onchange = () => this.solve();
        this.chkEmpirical.onchange = () => this.solve();
    }

    hideLoader() {
        document.getElementById('loader').classList.add('hidden');
    }

    renderGrid() {
        this.gridContainer.innerHTML = '';
        for (let r = 0; r < 4; r++) {
            for (let c = 0; c < 4; c++) {
                const val = this.grid[r][c];
                const cell = document.createElement('div');
                cell.className = `cell tile-${val}`;
                if (this.guiState === "WAITING_FOR_SPAWN" && val === 0) {
                    cell.classList.add('waiting-spawn');
                }
                
                cell.textContent = val > 0 ? Math.pow(2, val) : '';
                
                if (val === 11) {
                    const stone = document.createElement('span');
                    stone.className = 'stone-indicator';
                    stone.textContent = '🗿';
                    cell.appendChild(stone);
                }

                cell.onmousedown = (e) => {
                    if (e.button === 0) { // Left click
                        // Qt logic: if 0 -> spawn_low, if spawn_low -> spawn_high, else increment
                        const mode = this.modeSelect.value;
                        const spawns = { "x1": [1, 2], "x4": [3, 4], "x8": [4, 5], "x16": [5, 6] };
                        const [low, high] = spawns[mode] || [1, 2];
                        
                        if (this.grid[r][c] === 0) this.grid[r][c] = low;
                        else if (this.grid[r][c] === low) this.grid[r][c] = high;
                        else this.grid[r][c] = (this.grid[r][c] + 1) % 16;
                    } else if (e.button === 2) { // Right click
                        this.grid[r][c] = 0;
                    }
                    this.renderGrid();
                    if (this.guiState === "NORMAL") this.solve();
                };
                cell.oncontextmenu = (e) => e.preventDefault();
                
                this.gridContainer.appendChild(cell);
            }
        }
    }

    updateStats() {
        this.scoreEl.textContent = `Score: ${this.score}`;
        this.energyEl.textContent = `Energy: ${this.energy}`;
        this.movesEl.textContent = `Moves: ${this.moves}`;
        const eff = this.energy > 0 ? (this.score / this.energy).toFixed(1) : "0.0";
        this.efficiencyEl.textContent = `Pts/Energy: ${eff}`;
    }

    spawnRandom() {
        const empties = [];
        for (let r = 0; r < 4; r++) {
            for (let c = 0; c < 4; c++) {
                if (this.grid[r][c] === 0) empties.push({r, c});
            }
        }
        if (empties.length === 0) return;
        const spot = empties[Math.floor(Math.random() * empties.length)];
        this.grid[spot.r][spot.c] = Math.random() < 0.9 ? 1 : 2;
    }

    newGame() {
        this.grid = Array(4).fill().map(() => Array(4).fill(0));
        this.score = 0;
        this.energy = 0;
        this.moves = 0;
        this.guiState = "NORMAL";
        this.spawnRandom();
        this.spawnRandom();
        this.renderGrid();
        this.updateStats();
        this.updateUIState();
        this.history = [];
        this.solve();
    }

    resetBoard() {
        this.grid = Array(4).fill().map(() => Array(4).fill(0));
        this.guiState = "NORMAL";
        this.renderGrid();
        this.updateUIState();
        this.solve();
    }

    saveHistory() {
        this.history.push({
            grid: JSON.stringify(this.grid),
            score: this.score,
            energy: this.energy,
            moves: this.moves,
            guiState: this.guiState
        });
        if (this.history.length > 100) this.history.shift();
    }

    undo() {
        if (this.history.length > 0) {
            const state = this.history.pop();
            this.grid = JSON.parse(state.grid);
            this.score = state.score;
            this.energy = state.energy;
            this.moves = state.moves;
            this.guiState = state.guiState;
            this.renderGrid();
            this.updateStats();
            this.updateUIState();
            this.solve();
        }
    }

    executeMove(direction) {
        if (this.guiState === "WAITING_FOR_SPAWN") return;
        
        const { moved, score } = this.moveLogic(direction);
        if (moved) {
            this.saveHistory();
            this.score += score;
            const mode = this.modeSelect.value;
            const energyCost = { "x1": 1, "x4": 4, "x8": 8, "x16": 16 }[mode] || 1;
            this.energy += energyCost;
            this.moves += 1;
            
            // Qt state transition
            this.guiState = "WAITING_FOR_SPAWN";
            
            this.renderGrid();
            this.updateStats();
            this.updateUIState();
        }
    }

    confirmSpawn() {
        if (this.guiState !== "WAITING_FOR_SPAWN") return;
        
        // Normally we'd calculate spawn score here
        // For simplicity in JS simulation, we just return to normal
        this.guiState = "NORMAL";
        this.updateUIState();
        this.renderGrid();
        this.solve();
    }

    updateUIState() {
        const isNormal = this.guiState === "NORMAL";
        
        // Buttons
        this.moveLeftBtn.disabled = !isNormal;
        this.moveRightBtn.disabled = !isNormal;
        this.moveUpBtn.disabled = !isNormal;
        this.moveDownBtn.disabled = !isNormal;
        this.applyRecBtn.disabled = !isNormal;
        this.confirmSpawnBtn.disabled = isNormal;
        
        if (isNormal) {
            this.statusBanner.textContent = "STATUS: Active Game / Edit Mode";
            this.statusBanner.style.backgroundColor = "#2b2b36";
            this.statusBanner.style.color = "#b0bec5";
            this.confirmSpawnBtn.style.backgroundColor = "";
        } else {
            this.statusBanner.textContent = "⚠️ WAITING FOR SPAWN: Click spawned tiles, then ENTER or Confirm Spawn";
            this.statusBanner.style.backgroundColor = "#0d47a1";
            this.statusBanner.style.color = "#ffffff";
            this.confirmSpawnBtn.style.backgroundColor = "#0d47a1";
        }
    }

    solve() {
        if (this.isSolving || !this.worker) return;
        this.isSolving = true;
        this.solveBtn.disabled = true;
        this.solveBtn.textContent = "Analyzing...";

        this.worker.postMessage({
            type: 'solve',
            payload: {
                grid: this.grid,
                mode: this.modeSelect.value,
                depth: this.depthSelect.value,
                time_limit_ms: parseInt(this.timeSelect.value)
            }
        });
    }

    handleSolveResult(result) {
        this.isSolving = false;
        this.solveBtn.disabled = false;
        this.solveBtn.textContent = "Solve";

        if (this.guiState === "WAITING_FOR_SPAWN") {
            this.recDirEl.textContent = "Waiting for spawn input... 🕒";
            this.decisionBadge.textContent = "WAITING FOR SPAWN";
            this.decisionBadge.style.backgroundColor = "#0d47a1";
            return;
        }

        const DIR_ICONS = { "LEFT": "◀", "RIGHT": "▶", "UP": "▲", "DOWN": "▼" };
        const icon = DIR_ICONS[result.best_move] || "";
        this.recDirEl.textContent = result.best_move ? `✅ RECOMMEND: ${result.best_move} (${icon})` : "GAME OVER 💀";
        
        this.evValEl.textContent = `${result.ev.toFixed(2)} pts`;
        
        const mode = this.modeSelect.value;
        const energyCost = { "x1": 1, "x4": 4, "x8": 8, "x16": 16 }[mode] || 1;
        const evPerEnergy = (result.ev / energyCost).toFixed(2);
        this.evEnergyValEl.textContent = `${evPerEnergy} pts/energy`;
        
        const survivalScore = (result.expected_empty / 16.0) * 100.0;
        this.survivalFill.style.width = `${survivalScore}%`;
        
        let decision = "CONTINUE";
        let badgeColor = "#2e7d32"; // Darker green like Qt
        
        if (!result.best_move) {
            decision = "GAME OVER";
            badgeColor = "#552222";
        } else if (parseFloat(evPerEnergy) < 2.0) {
            decision = "STOP & CONVERT";
            badgeColor = "#c62828";
        } else if (parseFloat(evPerEnergy) < 6.0) {
            decision = "RESTART GAME";
            badgeColor = "#ef6c00";
        }
        
        this.decisionBadge.textContent = decision;
        this.decisionBadge.style.backgroundColor = badgeColor;

        // Build report matching GUI
        let report = [];
        report.push(`Search Stats: Depth ${result.completed_depth} | Nodes ${result.node_count.toLocaleString()} | Time ${Math.round(result.elapsed_ms)}ms`);
        report.push("=".repeat(45));
        report.push("Heuristic Rationale:");
        result.explanation.forEach(text => report.push(` • ${text}`));
        
        this.reasonsBox.innerText = report.join('\n');

        // Highlight recommended move
        this.resetActionButtonStyles();
        if (result.best_move) {
            const moveMap = { "LEFT": this.moveLeftBtn, "RIGHT": this.moveRightBtn, "UP": this.moveUpBtn, "DOWN": this.moveDownBtn };
            if (moveMap[result.best_move]) {
                moveMap[result.best_move].classList.add('highlighted');
            }
            this.applyRecBtn.classList.add('apply-rec-highlighted');
        }
    }

    executeRecommendedMove() {
        const moveStr = this.recDirEl.textContent;
        const moveMap = { "LEFT": 0, "RIGHT": 1, "UP": 2, "DOWN": 3 };
        const cleanMove = Object.keys(moveMap).find(k => moveStr.includes(k));
        if (cleanMove !== undefined) {
            this.executeMove(moveMap[cleanMove]);
        }
    }

    resetActionButtonStyles() {
        [this.moveLeftBtn, this.moveRightBtn, this.moveUpBtn, this.moveDownBtn, this.applyRecBtn].forEach(btn => {
            btn.classList.remove('highlighted');
            btn.classList.remove('apply-rec-highlighted');
        });
    }

    // JS Move logic (must match game_engine.py logic for local UI updates)
    moveLogic(direction) {
        let moved = false;
        let score = 0;
        const grid = this.grid;

        const getLine = (i, isRow) => isRow ? grid[i] : [grid[0][i], grid[1][i], grid[2][i], grid[3][i]];
        const setLine = (i, line, isRow) => {
            for (let j = 0; j < 4; j++) {
                if (isRow) grid[i][j] = line[j];
                else grid[j][i] = line[j];
            }
        };

        const isRow = (direction === 0 || direction === 1);
        const reverse = (direction === 1 || direction === 3);

        for (let i = 0; i < 4; i++) {
            let line = getLine(i, isRow);
            if (reverse) line.reverse();
            
            let original = [...line];
            let nonZeros = line.filter(x => x > 0);
            let merged = [];
            for (let j = 0; j < nonZeros.length; j++) {
                if (j + 1 < nonZeros.length && nonZeros[j] === nonZeros[j+1] && nonZeros[j] !== 11) {
                    let resLevel = nonZeros[j] + 1;
                    if (resLevel > 15) resLevel = 15;
                    merged.push(resLevel);
                    score += Math.pow(2, resLevel); 
                    j++;
                } else {
                    merged.push(nonZeros[j]);
                }
            }
            while (merged.length < 4) merged.push(0);
            
            if (reverse) merged.reverse();
            setLine(i, merged, isRow);
            
            if (JSON.stringify(original) !== JSON.stringify(reverse ? [...merged].reverse() : merged)) {
                moved = true;
            }
        }
        return { moved, score };
    }
}

new App();
