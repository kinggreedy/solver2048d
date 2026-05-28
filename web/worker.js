importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.1/full/pyodide.js");

let pyodide;
let webSolver;

async function initPyodide() {
    pyodide = await loadPyodide();
    await pyodide.loadPackage(["PyYAML"]);
    
    // We need to fetch the python source files
    // In a real hosting environment, these would be served relative to index.html
    // For now, we assume the worker can see the src directory via some mechanism
    // or we inject the code.
    // Efficient way: Fetch and write to virtual FS.
}

self.onmessage = async (e) => {
    const { type, payload } = e.data;

    if (type === "init") {
        try {
            await initPyodide();
            
            // Load the source files into Pyodide's FS
            const files = payload.files;
            pyodide.FS.mkdir("src");
            
            for (const [path, content] of Object.entries(files)) {
                pyodide.FS.writeFile(path, content);
            }

            // Import the bridge
            await pyodide.runPythonAsync(`
                import sys
                import os
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
        try {
            const { grid, mode, depth, time_limit_ms } = payload;
            const resultJson = webSolver.solve(
                JSON.stringify(grid), 
                mode, 
                depth === "dynamic" ? "dynamic" : parseInt(depth), 
                time_limit_ms
            );
            self.postMessage({ type: "solve_result", result: JSON.parse(resultJson) });
        } catch (err) {
            self.postMessage({ type: "error", error: err.message });
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
