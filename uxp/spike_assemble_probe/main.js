/* Panel glue for the issue #25 assemble probe. All the orchestration lives in
   assembleProbe.js, which takes the host as an argument and never touches the DOM
   — that is what lets tests/cutdeck_assemble_probe.test.cjs drive it against mock
   hosts in Node. This file holds only what cannot be tested outside Premiere:
   require("premierepro"), the log element and the buttons.

   Deliberately NOT part of the CutDeck panel. These calls mutate the project, and
   the handoff (docs/HANDOFF_CUTDECK_TIMELINE_IN_OUT.md section 4) puts mutating
   probes in a disposable test project, not the panel a human uses on real work. */

let ppro = null;
try {
  ppro = require("premierepro");
} catch (error) {
  // require() should not fail inside a real UXP host; if it does, the plugin is
  // not running where it thinks it is, and the probe reports that as a finding.
  ppro = null;
}

const logEl = document.getElementById("log");
let busy = false;

function log(message) {
  console.log("[assemble-probe]", message);
  logEl.textContent += message + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

async function run() {
  if (busy) return;
  busy = true;
  document.getElementById("run").disabled = true;
  logEl.textContent = "";
  try {
    const probe = require("./assembleProbe.js");
    log("Running the assemble probe. This MUTATES the project — disposable projects only.\n");
    const report = await probe.runAssembleProbe(ppro, log);
    // JSON in the UXP Developer Tool console is the paste-onto-the-issue copy.
    console.log("assemble probe report", JSON.stringify(report, null, 2));
    log("\n" + probe.formatReport(report));
  } catch (error) {
    // runAssembleProbe is written not to throw, so reaching here is itself a
    // finding worth seeing rather than a silently swallowed panel error.
    log(`PROBE ITSELF FAILED: ${(error && error.message) || error}`);
    if (error && error.stack) log(error.stack);
  } finally {
    busy = false;
    document.getElementById("run").disabled = false;
  }
}

/* Dual fallback (navigator.clipboard, then the uxp module's clipboard) — the
   pattern spike18 confirmed against a real live Premiere UXP plugin. */
async function copyLog() {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(logEl.textContent);
    } else if (require("uxp").clipboard) {
      require("uxp").clipboard.copyText(logEl.textContent);
    } else {
      throw new Error("no clipboard API available");
    }
    log("--- log copied to clipboard ---");
  } catch (error) {
    log(`FAILED to copy log: ${(error && error.message) || error}`);
  }
}

document.getElementById("run").addEventListener("click", run);
document.getElementById("copyLog").addEventListener("click", copyLog);
