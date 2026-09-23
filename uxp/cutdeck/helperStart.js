/* Starts the CutDeck helper the only way UXP can: `shell.openPath` on
   "Start CutDeck (Hidden).vbs", then poll `hello` until it answers.

   UXP has no `child_process` (the retired CEP panel's helper_manager.js
   spawned the helper directly and silently instead — see issue #41).
   `openPath` cannot pass arguments, capture output, report an exit code, or
   run its target hidden (Adobe's own external-process recipe says as much).
   The .vbs wrapper is how a visible console window is avoided anyway:
   wscript.exe (the default .vbs handler) shows no window of its own, and its
   WshShell.Run(path, 0, False) call hides the console it starts — including
   Start CutDeck.cmd's python.exe — while still running it in the background.
   If the helper silently fails to come up, that hides the real error too:
   run "Start CutDeck.cmd" directly to see it.

   The path it launches must be a plain native path string. `require("path")`
   plus `__dirname` is NOT trustworthy for that here: UXP's own `path` module
   is documented as a global registered only since UXP v6.4.0, and its
   require()-module behavior (and __dirname inside it) isn't something this
   plugin has ever exercised — it produced "path should be a string type"
   from shell.openPath in a real Premiere run. `storage.localFileSystem
   .getPluginFolder().nativePath` is the route probe.js already proves works
   in this exact plugin (uxp/cutdeck/probe.js), so derive the repo root from
   that instead. */

const HELPER_LAUNCHER_NAME = "Start CutDeck (Hidden).vbs";

/* Pure and independently testable: given the plugin folder's own native
   path (".../uxp/cutdeck"), returns the repo root's hidden-launch script. */
function deriveHelperScriptPath(pluginNativePath) {
  const sep = pluginNativePath.indexOf("\\") !== -1 ? "\\" : "/";
  const trimmed = pluginNativePath.replace(/[\\/]+$/, "");
  const repoRoot = trimmed.replace(/[\\/]uxp[\\/]cutdeck$/, "");
  if (repoRoot === trimmed) {
    throw new Error("Could not find the repo root from plugin path: " + pluginNativePath);
  }
  return repoRoot + sep + HELPER_LAUNCHER_NAME;
}

async function findHelperScript() {
  const localFileSystem = require("uxp").storage.localFileSystem;
  const pluginFolder = await localFileSystem.getPluginFolder();
  return deriveHelperScriptPath(pluginFolder.nativePath);
}

async function ensureHelperRunning(options) {
  const opts = options || {};
  const rpc = opts.rpc;
  const version = opts.version;
  if (!version) {
    throw new Error("opts.version is required");
  }
  const onStatus = opts.onStatus || (() => {});
  const now = opts.now || Date.now;
  const sleep = opts.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));

  // 1. Fast single-shot ping: skip the consent prompt entirely if already running.
  try {
    const reply = await rpc({ type: "hello", version });
    if (reply && reply.version === version) {
      return { started: false, alreadyRunning: true };
    }
  } catch (_) {
    // Not running yet; launch it below.
  }

  const shell = opts.shell || (typeof require !== "undefined" ? require("uxp").shell : null);
  if (!shell || typeof shell.openPath !== "function") {
    throw new Error("This UXP build cannot launch external processes. Start the helper manually with Start CutDeck.cmd.");
  }

  const scriptPath = opts.scriptPath || await findHelperScript();

  onStatus("Starting CutDeck helper…");
  const result = await shell.openPath(scriptPath, "Start the CutDeck helper");
  if (result !== "") {
    throw new Error("Could not launch Start CutDeck.cmd: " + result);
  }

  // 2. Poll until the helper responds to hello (up to 15 seconds).
  const timeoutMs = opts.timeoutMs || 15000;
  const pollMs = opts.pollMs || 500;
  const startTime = now();
  let lastError = null;

  while (now() - startTime < timeoutMs) {
    await sleep(pollMs);
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

  throw new Error("CutDeck helper did not start in time. Run Start CutDeck.cmd manually. Details: "
    + (lastError ? lastError.message : "timed out"));
}

/* Asks a running helper to replace itself with a fresh process, so helper code edited since it
   started is picked up (the helper spawns its successor: no launch prompt). Waits until a
   helper with a different pid answers. Returns what happened; never launches one itself. */
async function restartHelper(options) {
  const { rpc, version } = options;
  const now = options.now || Date.now;
  const sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  let before;
  try {
    before = await rpc({ type: "hello", version });
  } catch (_) {
    return "not-running";
  }
  try {
    await rpc({ type: "restart" });
  } catch (error) {
    return "kept: " + error.message; // busy with a job, or a helper too old to restart itself
  }
  const startTime = now();
  while (now() - startTime < (options.timeoutMs || 15000)) {
    await sleep(options.pollMs || 300);
    try {
      const reply = await rpc({ type: "hello", version });
      if (reply && reply.pid !== before.pid) return "restarted";
    } catch (_) { /* the new one is still starting */ }
  }
  throw new Error("The CutDeck helper did not come back after restarting. Run Start CutDeck.cmd.");
}

module.exports = { ensureHelperRunning, restartHelper, findHelperScript, deriveHelperScriptPath };
