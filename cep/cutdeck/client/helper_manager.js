/* CutDeck Background Helper Manager
 * Automatically starts cutdeck.xml_bridge in the background when the panel opens.
 */

(function (global) {
  let activeProcess = null;

  function getRepoRoot(csInterface) {
    if (typeof require === "undefined") return null;
    const path = require("path");
    const fs = require("fs");

    if (csInterface && typeof csInterface.getSystemPath === "function") {
      try {
        const extPath = csInterface.getSystemPath("extension");
        const real = fs.realpathSync(extPath);
        return path.resolve(real, "../..");
      } catch (_) {}
    }

    // Fallback: look relative to current script or default project path
    return "E:\\Me\\5.Claude\\Transcriber_v2";
  }

  function findPython(repoRoot) {
    if (typeof require === "undefined") return "python";
    const path = require("path");
    const fs = require("fs");

    if (repoRoot) {
      const venvPy = path.join(repoRoot, ".venv", "Scripts", "python.exe");
      if (fs.existsSync(venvPy)) return venvPy;
    }
    return "python";
  }

  async function ensureHelperRunning(options) {
    const opts = options || {};
    const rpc = opts.rpc;
    const version = opts.version || "cutdeck-xml-1";
    const onStatus = opts.onStatus || (() => {});
    const csInterface = opts.csInterface;

    // 1. Fast single-shot ping (checks in <10ms without wasting 3 seconds on backoffs)
    let isAlive = false;
    try {
      if (rpc) {
        const reply = await rpc({ type: "hello", version });
        if (reply && reply.version === version) {
          isAlive = true;
        }
      } else {
        const rpcModule = global.CutDeckRpc || (typeof require !== "undefined" ? require("./core/rpc.js") : null);
        if (rpcModule && typeof rpcModule.createRpc === "function") {
          const fastRpc = rpcModule.createRpc({
            attempts: 1,
            connectTimeoutMs: 300,
            replyTimeoutMs: 1000,
          });
          const reply = await fastRpc({ type: "hello", version });
          if (reply && reply.version === version) {
            isAlive = true;
          }
        }
      }
    } catch (_) {
      // Helper not running; proceed to auto-start immediately
    }

    if (isAlive) {
      return { started: false, alreadyRunning: true };
    }

    if (typeof require === "undefined") {
      throw new Error("Node.js is disabled in this panel. Start the helper manually with Start CutDeck.cmd.");
    }

    onStatus("Starting CutDeck helper in background…");

    const { spawn } = require("child_process");
    const repoRoot = getRepoRoot(csInterface);
    const pythonExe = findPython(repoRoot);

    try {
      activeProcess = spawn(pythonExe, ["-m", "cutdeck.xml_bridge"], {
        cwd: repoRoot,
        windowsHide: true,
        stdio: "ignore",
        detached: true,
      });
      if (typeof activeProcess.unref === "function") {
        activeProcess.unref();
      }

      activeProcess.on("error", (err) => {
        console.error("CutDeck helper spawn error:", err);
      });
    } catch (err) {
      throw new Error("Could not spawn CutDeck helper: " + (err.message || String(err)));
    }

    // 2. Poll until the helper responds to hello (up to 15 seconds)
    const timeoutMs = opts.timeoutMs || 15000;
    const startTime = Date.now();
    let lastError = null;

    while (Date.now() - startTime < timeoutMs) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      try {
        const reply = await rpc({ type: "hello", version });
        if (reply && reply.version === version) {
          onStatus("CutDeck helper ready.");
          return { started: true, alreadyRunning: false };
        }
      } catch (err) {
        lastError = err;
      }
    }

    throw new Error("CutDeck helper did not start in time. You can still run Start CutDeck.cmd manually. Details: " + (lastError ? lastError.message : "timed out"));
  }

  function stopHelper() {
    if (activeProcess && !activeProcess.killed) {
      try {
        activeProcess.kill();
      } catch (_) {}
      activeProcess = null;
    }
  }

  const exportObj = {
    getRepoRoot,
    findPython,
    ensureHelperRunning,
    stopHelper,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckHelperManager = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
