const ppro = require("premierepro");
const workflow = require("./workflow.js");
const { createRpc } = require("./core/rpc.js");
const { progressText } = require("./core/progressText.js");
const probe = require("./probe.js");  // TEMPORARY DIAGNOSTIC
const capability = require("./capabilityProbe.js");
const assemble = require("./assembleProbe.js");
const helperStart = require("./helperStart.js");
const $ = (id) => document.getElementById(id);
const KEY = "cutdeck.xml.lastJob";
let busy = false;

// One short connection per request makes reconnects independent of long GPU jobs.
// Connecting retries; a sent request never does. See rpc.js for why.
const rpc = createRpc({
  onRetry: (attempt, total) => setStatus(`Connecting to the CutDeck helper… attempt ${attempt} of ${total}.`, "busy"),
});

function lastJob() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (_) { return null; }
}
function save(job) {
  localStorage.setItem(KEY, JSON.stringify(job));
  if ($("job-banner")) $("job-banner").classList.add("show");
  if ($("resume")) $("resume").hidden = false;
  if ($("dismiss")) $("dismiss").hidden = false;
}
function clearJob() {
  localStorage.removeItem(KEY);
  if ($("job-banner")) $("job-banner").classList.remove("show");
  if ($("resume")) $("resume").hidden = true;
  if ($("dismiss")) $("dismiss").hidden = true;
}
function setStatus(message, state = "ready") {
  if ($("status")) $("status").textContent = message;
  const dot = $("dot");
  const stateText = $("state-text");
  const icon = $("status-icon");
  if (dot && stateText && icon) {
    dot.className = "status-dot";
    if (state === "busy" || busy) {
      dot.classList.add("busy");
      stateText.textContent = "BUSY";
      icon.style.background = "#f59e0b";
    } else if (state === "error") {
      dot.classList.add("error");
      stateText.textContent = "ALERT";
      icon.style.background = "#ef4444";
    } else {
      stateText.textContent = "READY";
      icon.style.background = "#10b981";
    }
  }
}
async function ensureHelper() {
  return helperStart.ensureHelperRunning({
    rpc,
    version: workflow.VERSION,
    onStatus: (msg) => setStatus(msg, "busy"),
  });
}
function time(seconds) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
}
async function refresh() {
  const snap = await workflow.capture(ppro);
  if ($("sequence")) $("sequence").textContent = snap.context.sequence_name;
  if ($("range")) $("range").textContent = `${time(snap.inSeconds)} → ${time(snap.outSeconds)}`;
  const audioSelect = $("audio");
  if (audioSelect) {
    const selected = audioSelect.value;
    audioSelect.innerHTML = "";
    const add = (value, label) => {
      const option = document.createElement("option");
      option.setAttribute("value", value);
      option.textContent = label;
      audioSelect.appendChild(option);
    };
    add("", "Auto");
    const count = snap.context.audio_track_count;
    for (let i = 0; i < count; i++) add(String(i), `Track A${i + 1}`);
    audioSelect.value = selected === "" || Number(selected) < count ? selected : "";
  }
  return snap;
}
async function follow(job) {
  while (job.state === "running") {
    setStatus(progressText(job), "busy");
    await new Promise((resolve) => setTimeout(resolve, 1500));
    job = await rpc({ type: "status", job_id: job.job_id });
  }
  if (job.state === "failed") { clearJob(); setStatus(job.message, "error"); throw new Error(job.message); }
  if (job.state === "no_cuts") { clearJob(); setStatus("No cuts found inside this range. Your sequence is unchanged.", "ready"); return; }
  if (job.state !== "ready") { setStatus("Job error: " + job.state, "error"); throw new Error("Job is not ready: " + job.state); }
  const sync = job.job_type === "sync";
  setStatus(sync ? "Opening synchronized multi-cam sequence…" : "Opening your rough cut in Premiere…", "busy");
  const saved = lastJob() || {};
  await workflow.importResult(ppro, job, saved.importAttempted,
    () => save({ ...saved, ...job, importAttempted: true }));
  clearJob();
  if (sync) {
    const rep = job.report || {};
    const unsynced = rep.unsynced_groups > 0 ? ` ${rep.unsynced_groups} placed at end.` : "";
    setStatus(`Multi-cam sync complete (${rep.synced_groups || 0} angles).${unsynced}
Opened ${job.result_name}
Saved ${job.output_path}`, "ready");
    return;
  }
  const note = job.output_note ? `\n${job.output_note}` : "";
  setStatus(`${job.report.cuts_applied} cuts · ${(job.report.removed_ms / 1000).toFixed(1)} seconds removed.`
    + `\nOpened ${job.result_name}\nSaved ${job.output_path}${note}`, "ready");
}

const ACT_TARGETS = ["cut", "sync", "refresh", "resume", "dismiss", "audio", "mode",
  "socketprobe", "timingprobe", "assembleprobe", "copystatus",
  "pill-speech", "pill-silence"];

async function act(fn) {
  if (busy) return;
  busy = true;
  ACT_TARGETS.forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.disabled = true;
    el.setAttribute("disabled", "true");
    el.classList.add("disabled");
  });
  setStatus("Processing…", "busy");
  try { await fn(); }
  catch (error) { setStatus(error.message || String(error), "error"); console.error(error); }
  finally {
    busy = false;
    ACT_TARGETS.forEach((id) => {
      const el = $(id);
      if (!el) return;
      el.disabled = false;
      el.removeAttribute("disabled");
      el.classList.remove("disabled");
    });
    if ($("state-text") && $("state-text").textContent === "BUSY") {
      setStatus($("status") ? $("status").textContent : "Ready", "ready");
    }
  }
}

// --- UI Interactivity ---

// 1. Preset Pills for Cutting Mode
function setupPresets() {
  const pillSpeech = $("pill-speech");
  const pillSilence = $("pill-silence");
  const modeSelect = $("mode");
  if (!pillSpeech || !pillSilence || !modeSelect) return;

  pillSpeech.addEventListener("click", () => {
    pillSpeech.classList.add("active");
    pillSilence.classList.remove("active");
    modeSelect.value = "protected";
  });
  pillSilence.addEventListener("click", () => {
    pillSilence.classList.add("active");
    pillSpeech.classList.remove("active");
    modeSelect.value = "silence";
  });
}

// 2. Diagnostics Drawer Toggle
function setupDiagnostics() {
  const toggleBtn = $("tools-toggle");
  const diag = $("diagnostics");
  if (toggleBtn && diag) {
    toggleBtn.addEventListener("click", () => diag.classList.toggle("open"));
  }
}

// 3. Click Sequence Card to re-read timeline
if ($("seq-card")) {
  $("seq-card").addEventListener("click", () => act(async () => {
    await refresh();
    setStatus("Range updated", "ready");
  }));
}

if ($("refresh")) {
  $("refresh").addEventListener("click", () => act(async () => {
    await refresh();
    setStatus("Range ready", "ready");
  }));
}
if ($("cut")) {
  $("cut").addEventListener("click", () => act(async () => {
    if (lastJob()) throw new Error("Resume the previous job before starting another rough cut.");
    await ensureHelper();
    const snap = await refresh();
    setStatus("Preparing your sequence…", "busy");
    const track = $("audio") ? $("audio").value : "";
    const modeVal = $("mode") ? $("mode").value : "protected";
    const job = await workflow.prepare(ppro, rpc, snap,
      { audio_track: track === "" ? null : Number(track), asr: modeVal === "protected" }, save);
    await follow(job);
  }));
}
if ($("sync")) {
  $("sync").addEventListener("click", () => act(async () => {
    if (lastJob()) throw new Error("Resume or dismiss the previous job before starting another operation.");
    await ensureHelper();
    const snap = await refresh();
    setStatus("Exporting sequence XML for multi-camera sync…", "busy");
    const track = $("audio") ? $("audio").value : "";
    const job = await workflow.prepareSync(ppro, rpc, snap, { audio_track: track === "" ? null : Number(track) }, save);
    await follow(job);
  }));
}
if ($("resume")) {
  $("resume").addEventListener("click", () => act(async () => {
    const saved = lastJob();
    if (!saved) return;
    await ensureHelper();
    await rpc({ type: "hello", version: workflow.VERSION });
    let job;
    try { job = await rpc({ type: "status", job_id: saved.job_id }); }
    catch (error) {
      if (error.message && error.message.startsWith("Unknown job")) clearJob();
      throw error;
    }
    if (job.state === "prepared") {
      if (!saved.exported) { clearJob(); setStatus("The previous export did not finish. Start a new rough cut.", "ready"); return; }
      job = await rpc({ type: "start", job_id: saved.job_id });
    }
    await follow(job);
  }));
}
if ($("dismiss")) {
  $("dismiss").addEventListener("click", () => act(async () => {
    const saved = lastJob();
    clearJob();
    setStatus("Previous job dismissed. Any running analysis continues in the helper. Saved result location:\n" + (saved ? saved.output_path : ""), "ready");
  }));
}

// Phase 0 probe 1. Read-only: it creates and changes nothing, so it is safe on a
// real project, and it needs no helper running.
if ($("timingprobe")) {
  $("timingprobe").addEventListener("click", () => act(async () => {
    setStatus("Reading this build's marks and timebase…", "busy");
    const report = await capability.probeMarksAndTiming(ppro);
    console.log("CutDeck capability probe", JSON.stringify(report, null, 2));
    setStatus(capability.formatReport(report), "ready");
  }));
}

// The only control in this panel that mutates a project, so it arms before it runs.
// A misclick on a real edit would leave a stray sequence behind — recoverable, but
// the panel should not make it a one-click mistake. Disarms itself after 10s so an
// armed button can never be inherited by a later, unrelated click.
let assembleArmed = null;
function disarmAssemble() {
  if (assembleArmed) clearTimeout(assembleArmed);
  assembleArmed = null;
  if ($("assembleprobe")) {
    $("assembleprobe").classList.remove("armed");
    $("assembleprobe").textContent = "Run assemble probe (MUTATES — disposable projects only)";
  }
}
if ($("assembleprobe")) {
  $("assembleprobe").addEventListener("click", () => {
    if (!assembleArmed) {
      assembleArmed = setTimeout(disarmAssemble, 10000);
      $("assembleprobe").classList.add("armed");
      $("assembleprobe").textContent = "Click again to run — this CREATES a sequence";
      setStatus("The assemble probe mutates the open project: it creates a sequence, places three spans, "
        + "disables one and ripple-removes it. Use a DISPOSABLE project.\nClick the red button again "
        + "within 10 seconds to run it, or wait for it to disarm.", "ready");
      return;
    }
    disarmAssemble();
    act(async () => {
      setStatus("Running the assemble probe (issue #25, Phase 0)…", "busy");
      const report = await assemble.runAssembleProbe(ppro, (line) => console.log("[assemble probe]", line));
      console.log("CutDeck assemble probe", JSON.stringify(report, null, 2));
      setStatus(assemble.formatReport(report), "ready");
    });
  });
}

// Diagnostic only, and never on load: it opens sockets, so running it automatically would
// make a panel that needs no helper report a helper failure every time it opens.
if ($("socketprobe")) {
  $("socketprobe").addEventListener("click", () => act(async () => {
    setStatus("Probing which socket URLs this Premiere build permits…", "busy");
    const { report, written } = await probe.run();
    setStatus([`Socket permission probe:`, ...report.results.map((r) => `${r.url} -> ${r.outcome}`),
      ``, `written: ${written}`].join(`\n`), "ready");
  }));
}

// Probe reports are long and are meant to be pasted onto an issue. Dual fallback
// (navigator.clipboard, then the uxp module's) is the pattern spike18 confirmed
// against a live Premiere plugin rather than assumed.
if ($("copystatus")) {
  $("copystatus").addEventListener("click", () => {
    // Captured before act() runs: act() immediately overwrites #status to
    // "Processing…", so reading it from inside the act() callback below
    // would copy that placeholder instead of the report the user clicked to copy.
    const text = $("status") ? $("status").textContent : "";
    act(async () => {
      if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(text);
      else if (require("uxp").clipboard) require("uxp").clipboard.copyText(text);
      else throw new Error("No clipboard API on this build. The full report is in the UXP Developer Tool console as JSON.");
      setStatus(text + "\n\n--- copied to clipboard ---", "ready");
    });
  });
}

// Init handlers
setupPresets();
setupDiagnostics();

if (lastJob()) {
  if ($("job-banner")) $("job-banner").classList.add("show");
  if ($("resume")) $("resume").hidden = false;
  if ($("dismiss")) $("dismiss").hidden = false;
} else {
  if ($("resume")) $("resume").hidden = true;
  if ($("dismiss")) $("dismiss").hidden = true;
}

// Immediately read and display timeline marks, if a sequence with marks is already open.
setTimeout(async () => {
  try {
    await refresh();
    setStatus("Ready", "ready");
  } catch (_) {
    setStatus("No sequence open", "ready");
  }
}, 50);
