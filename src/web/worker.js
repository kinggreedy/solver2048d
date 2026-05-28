importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.1/full/pyodide.js");

let pyodide;
let webSolver;
let currentSolveId = 0;

async function initPyodide() {
    pyodide = await loadPyodide();
    await pyodide.loadPackage(["PyYAML"]);
}

self.onmessage = async (e) => {
    const { type, payload, solveId } = e.data;

    if (type === "init") {
        try {
            await initPyodide();
            
            const files = payload.files;
            pyodide.FS.mkdir("src");
            
            for (const [path, content] of Object.entries(files)) {
                pyodide.FS.writeFile(path, content);
            }

            await pyodide.runPythonAsync(`
                import sys
                import os
                import json
                sys.path.append(os.getcwd())
                from src.web_solver import solve, update_config, get_current_config
            `);

            webSolver = {
                solve: pyodide.globals.get("solve"),
                update_config: pyodide.globals.get("update_config"),
                get_current_config: pyodide.globals.get("get_current_config")
            };

            self.postMessage({ type: "ready" });
        } catch (err) {
            self.postMessage({ type: "error", error: err.message });
        }
    } else if (type === "solve") {
        const mySolveId = solveId;
        currentSolveId = mySolveId;
        
        try {
            const { grid, mode, depth, enabled_modes } = payload;
            
            const maxDepth = depth === "dynamic" ? 7 : parseInt(depth);
            let totalElapsed = 0;

            // Iterative Deepening loop controlled by JS to allow interruption
            for (let d = 2; d <= maxDepth; d++) {
                // Check if a new solve request has started
                if (mySolveId !== currentSolveId) {
                    console.log(`WEB_WORKER: Interrupting stale solve ${mySolveId}`);
                    return;
                }

                const resultJson = webSolver.solve(
                    JSON.stringify(grid), 
                    mode, 
                    d, // Current depth
                    0, // No internal time deepening
                    JSON.stringify(enabled_modes)
                );
                
                const result = JSON.parse(resultJson);
                if (result.error) {
                    self.postMessage({ type: "error", error: result.error, traceback: result.traceback, solveId: mySolveId });
                    return;
                }

                totalElapsed += result.elapsed_ms;
                result.elapsed_ms = totalElapsed; // Accumulate time for UI

                const isFinal = (d === maxDepth);
                self.postMessage({ 
                    type: isFinal ? "solve_result" : "solve_progress", 
                    result: result,
                    elapsed_ms: totalElapsed,
                    solveId: mySolveId
                });

                // Crucial: yield to the event loop so the next 'solve' message can be received
                await new Promise(resolve => setTimeout(resolve, 0));
            }
        } catch (err) {
            self.postMessage({ type: "error", error: err.message, solveId: mySolveId });
        }
    } else if (type === "update_config") {
        try {
            webSolver.update_config(JSON.stringify(payload));
            self.postMessage({ type: "config_updated" });
        } catch (err) {
            self.postMessage({ type: "error", error: err.message });
        }
    }
};
