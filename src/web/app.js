/**
 * 2048 Expectimax Solver - App Controller (Qt Styled)
 */

class App {
    constructor() {
        this.grid = Array(4).fill().map(() => Array(4).fill(0));
        this.history = [];
        this.worker = null;
        this.isSolving = false;
        this.needsReSolve = false;
        this.workerReady = false;
        this.solveDebounceTimeout = null;
        this.hardKillTimeout = null;
        this.currentSolveId = 0;
        this.cachedFileContents = null;
        
        // Game states matching Qt
        this.guiState = "NORMAL"; // "NORMAL" or "WAITING_FOR_SPAWN"
        
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
        this.workerReady = false;
        
        if (!this.cachedFileContents) {
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
            const timestamp = new Date().getTime();
            for (const f of filesToLoad) {
                try {
                    const response = await fetch(`../../${f}?t=${timestamp}`);
                    fileContents[f] = await response.text();
                } catch (e) {
                    console.error(`Failed to load ${f}`, e);
                }
            }
            this.cachedFileContents = fileContents;
        }

        this.worker = new Worker('worker.js');
        
        return new Promise((resolve) => {
            this.worker.onmessage = (e) => {
                const { type, result, elapsed_ms, error, solveId } = e.data;
                
                if (type === 'ready') {
                    console.log("Worker ready");
                    this.workerReady = true;
                    
                    if (this.needsReSolve) {
                        this.needsReSolve = false;
                        this.solve();
                    }
                    resolve();
                } else if (type === 'solve_progress') {
                    if (solveId === this.currentSolveId) {
                        this.handleSolveResult(result, true, elapsed_ms);
                    }
                } else if (type === 'solve_result') {
                    if (solveId === this.currentSolveId) {
                        this.handleSolveResult(result, false, elapsed_ms);
                    }
                } else if (type === 'error') {
                    if (solveId === this.currentSolveId || !solveId) {
                        console.error("Worker error:", error);
                        if (this.hardKillTimeout) clearTimeout(this.hardKillTimeout);
                        this.isSolving = false; 
                        this.solveBtn.disabled = false;
                        this.solveBtn.textContent = "Solve";
                        this.statusBanner.textContent = `ERROR: ${error}`;
                        this.statusBanner.style.backgroundColor = "#b71c1c";
                        this.statusBanner.style.color = "#ffffff";
                    }
                }
            };

            this.worker.postMessage({
                type: 'init',
                payload: { files: this.cachedFileContents }
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

        const triggerSolve = () => { if (this.guiState === "NORMAL") this.triggerSolve(); };
        this.modeSelect.onchange = triggerSolve;
        this.depthSelect.onchange = triggerSolve;
        this.timeSelect.onchange = triggerSolve;
        this.chkX8.onchange = triggerSolve;
        this.chkX16.onchange = triggerSolve;
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
                    if (this.guiState === "NORMAL") this.triggerSolve();
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
            
            this.guiState = "WAITING_FOR_SPAWN";
            
            this.renderGrid();
            this.updateStats();
            this.updateUIState();
            this.solve(); 
        }
    }

    confirmSpawn() {
        if (this.guiState !== "WAITING_FOR_SPAWN") return;
        
        this.guiState = "NORMAL";
        this.updateUIState();
        this.renderGrid();
        this.solve();
    }

    updateUIState() {
        const isNormal = this.guiState === "NORMAL";
        
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
        } else {
            this.statusBanner.textContent = "⚠️ WAITING FOR SPAWN: Click spawned tiles, then ENTER or Confirm Spawn";
            this.statusBanner.style.backgroundColor = "#0d47a1";
            this.statusBanner.style.color = "#ffffff";
        }
    }

    async restartWorker() {
        console.log("WEB_APP: Silent worker restart initiated due to unresponsiveness...");
        if (this.worker) this.worker.terminate();
        this.isSolving = false;
        
        // Update UI to show maintenance state
        this.recDirEl.textContent = "⚙️ Restarting Engine...";
        this.statusBanner.textContent = "INTERRUPTING: Refreshing Python Runtime...";
        this.statusBanner.style.backgroundColor = "#4527a0"; 
        
        this.needsReSolve = true;
        await this.initWorker();
        this.updateUIState(); // Reset banner to Normal/Waiting state
    }

    triggerSolve(delay = 250) {
        if (this.solveDebounceTimeout) clearTimeout(this.solveDebounceTimeout);
        this.solveDebounceTimeout = setTimeout(() => {
            this.solve();
        }, delay);
    }

    solve() {
        if (!this.worker) return;

        if (!this.workerReady) {
            this.needsReSolve = true;
            return;
        }

        this.currentSolveId++;
        const mySolveId = this.currentSolveId;

        this.isSolving = true;
        this.solveBtn.disabled = true;
        this.solveBtn.textContent = "Analyzing...";

        this.recDirEl.textContent = "⌛ Thinking...";
        this.decisionBadge.textContent = "⌛ THINKING";
        this.decisionBadge.style.backgroundColor = "#e65100";
        this.reasonsBox.innerText = "Searching deeper...";

        const enabledModes = ["x1", "x4"];
        if (this.chkX8.checked) enabledModes.push("x8");
        if (this.chkX16.checked) enabledModes.push("x16");
        if (!enabledModes.includes(this.modeSelect.value)) enabledModes.push(this.modeSelect.value);

        this.worker.postMessage({
            type: 'solve',
            solveId: mySolveId,
            payload: {
                grid: this.grid,
                mode: this.modeSelect.value,
                depth: this.depthSelect.value,
                time_limit_ms: parseInt(this.timeSelect.value),
                enabled_modes: enabledModes
            }
        });

        // Watchdog: If the worker doesn't respond to THIS SPECIFIC solve request 
        // within the grace period, we hard kill it to guarantee responsiveness.
        const maxTimeMs = parseInt(this.timeSelect.value);
        const gracePeriod = maxTimeMs > 0 ? (maxTimeMs * 0.5) : 5000;

        if (this.hardKillTimeout) clearTimeout(this.hardKillTimeout);
        this.hardKillTimeout = setTimeout(() => {
            if (this.isSolving && this.currentSolveId === mySolveId) {
                console.log(`WEB_APP: Worker unresponsive for ${gracePeriod}ms. Hard killing.`);
                this.restartWorker();
            }
        }, gracePeriod);
    }

    handleSolveResult(evaluation, isPartial = false, elapsedMs = 0) {
        if (this.hardKillTimeout) clearTimeout(this.hardKillTimeout);

        if (!isPartial) {
            this.isSolving = false;
            this.solveBtn.disabled = false;
            this.solveBtn.textContent = "Solve";
        }

        if (this.guiState === "WAITING_FOR_SPAWN") {
            this.recDirEl.textContent = "Waiting for spawn input... 🕒";
            this.decisionBadge.textContent = "WAITING FOR SPAWN";
            this.decisionBadge.style.backgroundColor = "#0d47a1";
            return;
        }

        const bestMove = evaluation.best_move_str;
        const DIR_ICONS = { "LEFT": "◀", "RIGHT": "▶", "UP": "▲", "DOWN": "▼" };
        const icon = DIR_ICONS[bestMove] || "";
        
        let prefix = isPartial ? `🔍 CURRENT BEST (d${evaluation.completed_depth}):` : "✅ RECOMMEND:";
        this.recDirEl.textContent = bestMove ? `${prefix} ${bestMove} (${icon})` : "GAME OVER 💀";
        
        const selectedMode = this.modeSelect.value;
        const modeResults = evaluation.results[selectedMode];
        
        if (modeResults) {
            this.evValEl.textContent = `${modeResults.ev.toFixed(2)} pts`;
            this.evEnergyValEl.textContent = `${modeResults.ev_per_energy.toFixed(2)} pts/energy`;
        }

        const survivalScore = evaluation.survival_score;
        this.survivalFill.style.width = `${survivalScore}%`;
        
        let decision = evaluation.decision.replace("_", " ");
        let badgeColor = "#2e7d32";
        
        if (isPartial) {
            decision = "⌛ " + decision;
            badgeColor = "#e65100";
        } else if (decision === "GAME OVER") {
            badgeColor = "#552222";
        } else if (decision === "STOP AND CONVERT") {
            badgeColor = "#c62828";
        } else if (decision === "RESTART GAME") {
            badgeColor = "#ef6c00";
        }
        
        this.decisionBadge.textContent = decision;
        this.decisionBadge.style.backgroundColor = badgeColor;

        this.reasonsBox.innerText = this.buildRichReport(evaluation, isPartial, elapsedMs);

        this.resetActionButtonStyles();
        if (bestMove) {
            const moveMap = { "LEFT": this.moveLeftBtn, "RIGHT": this.moveRightBtn, "UP": this.moveUpBtn, "DOWN": this.moveDownBtn };
            if (moveMap[bestMove]) {
                moveMap[bestMove].classList.add('highlighted');
            }
            this.applyRecBtn.classList.add('apply-rec-highlighted');
        }
    }

    buildRichReport(evaluation, isPartial, elapsedMs) {
        let report = [];
        const selectedMode = this.modeSelect.value;

        report.push("Per-Mode Progress:");
        for (const [mode, res] of Object.entries(evaluation.results)) {
            if (res) {
                const status = isPartial ? "searching..." : "finished";
                report.push(`  ● ${mode.toUpperCase()}: best ${res.best_move_str} at d${res.completed_depth} (Nodes: ${res.node_count.toLocaleString()} | ${Math.round(elapsedMs)}ms) [${status}]`);
            } else {
                report.push(`  ● ${mode.toUpperCase()}: initializing...`);
            }
        }
        report.push("");

        report.push(`Global Fair Recommendation (at depth ${evaluation.completed_depth}):`);
        for (const [mode, res] of Object.entries(evaluation.results)) {
            if (res) {
                report.push(`  ● ${mode.toUpperCase()}: EV/Energy = ${res.ev_per_energy.toFixed(2)} (best ${res.best_move_str})`);
            } else {
                report.push(`  ● ${mode.toUpperCase()}: N/A`);
            }
        }
        if (evaluation.best_mode) {
            report.push(`  🏆 Winner: ${evaluation.best_mode.toUpperCase()} mode`);
        }
        report.push("");

        let statusLine = `Search Stats: Depth ${evaluation.completed_depth} | Nodes ${evaluation.node_count.toLocaleString()} | Time ${Math.round(elapsedMs)}ms`;
        if (isPartial) statusLine += "  ⏳";
        report.push(statusLine);
        report.push("=".repeat(45));
        report.push("");

        report.push("Heuristic Rationale:");
        if (evaluation.explanation) {
            evaluation.explanation.forEach(text => report.push(` • ${text}`));
        }
        report.push("");

        report.push("Move Comparison (ranked by heuristic search score):");
        const modeResults = evaluation.results[selectedMode];
        if (modeResults && modeResults.move_values) {
            const sortedMoves = Object.entries(modeResults.move_values).sort((a, b) => b[1] - a[1]);
            const DIR_MAP_FROM_INT = { 0: "LEFT", 1: "RIGHT", 2: "UP", 3: "DOWN" };
            const DIR_ICONS = { "LEFT": "◀", "RIGHT": "▶", "UP": "▲", "DOWN": "▼" };
            
            for (const [mInt, hScore] of sortedMoves) {
                const mStr = DIR_MAP_FROM_INT[mInt];
                const isBest = mStr === modeResults.best_move_str;
                const pref = isBest ? "★ " : "  ";
                const realEv = modeResults.move_real_values_str[mStr] || 0;
                const energyCost = { "x1": 1, "x4": 4, "x8": 8, "x16": 16 }[selectedMode] || 1;
                const evEnergy = realEv / energyCost;
                
                report.push(`${pref}${mStr.padEnd(8)} (${DIR_ICONS[mStr]}): RealEV=${realEv.toFixed(2).padEnd(9)} EV/Energy=${evEnergy.toFixed(2)} [HeuristicScore=${Math.round(hScore)}]`);
            }
        }

        report.push("");
        report.push("[RealEV = accumulated real merge+spawn pts across search tree]");
        report.push("[HeuristicScore = search ranking value; used for move ordering only]");

        return report.join('\n');
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
