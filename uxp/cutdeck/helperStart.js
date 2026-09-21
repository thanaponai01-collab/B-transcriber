/* Starts the CutDeck helper the only way UXP can: `shell.openPath` on
   Start CutDeck.cmd, then poll `hello` until it answers.

   UXP has no `child_process` — see cep/cutdeck/client/helper_manager.js for
   the CEP equivalent, which spawns the helper directly and silently instead.
   `openPath` cannot pass arguments, capture output, or report an exit code
   (Adobe's own external-process recipe: no parameters, no stdout capture,
   no hidden run) — Start CutDeck.cmd takes no arguments, so that limitation
   doesn't bite here. It resolves to "" on success or an error message
   string on failure, requires user consent, and needs the plugin
   manifest's `launchProcess` permission (uxp/cutdeck/manifest.json). */
const path = require("path");

function findHelperScript() {
  return path.resolve(__dirname, "..", "..", "Start CutDeck.cmd");
}

async function ensureHelperRunning(options) {
  const opts = options || {};
  const rpc = opts.rpc;
  const version = opts.version || "cutdeck-xml-1";
  const onStatus = opts.onStatus || (() => {});
  const scriptPath = opts.scriptPath || findHelperScript();
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

module.exports = { ensureHelperRunning, findHelperScript };
