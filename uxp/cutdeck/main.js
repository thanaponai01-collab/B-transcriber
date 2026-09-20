const ppro = require("premierepro");
const workflow = require("./workflow.js");
const { createRpc } = require("./rpc.js");
const { progressText } = require("./progressText.js");
const probe = require("./probe.js");  // TEMPORARY DIAGNOSTIC
const capability = require("./capabilityProbe.js");
const assemble = require("./assembleProbe.js");
const $ = (id) => document.getElementById(id);
const KEY = "cutdeck.xml.lastJob";
let busy = false;

// One short connection per request makes reconnects independent of long GPU jobs.
// Connecting retries; a sent request never does. See rpc.js for why.
const rpc = createRpc({
  onRetry: (attempt, total) => status(`Connecting to the CutDeck helper… attempt ${attempt} of ${total}.`),
});

function lastJob() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (_) { return null; }
}
function save(job) {
  localStorage.setItem(KEY, JSON.stringify(job));
  $("resume").hidden = false;
  $("dismiss").hidden = false;
}
function clearJob() {
  localStorage.removeItem(KEY);
  $("resume").hidden = true;
  $("dismiss").hidden = true;
}
function status(message) { $("status").textContent = message; }
function time(seconds) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
}
async function refresh() {
  const snap = await workflow.capture(ppro);
  $("sequence").textContent = snap.context.sequence_name;
  $("range").textContent = `${time(snap.inSeconds)} → ${time(snap.outSeconds)}`;
  const selected = $("audio").value;
  $("audio").innerHTML = "";
  const add = (value, label) => {
    const option = document.createElement("option");
    option.setAttribute("value", value); option.textContent = label; $("audio").appendChild(option);
  };
  add("", "First audio track with clips");
  const count = snap.context.audio_track_count;
  for (let i = 0; i < count; i++) add(String(i), `Audio ${i + 1}`);
  $("audio").setAttribute("value", selected === "" || Number(selected) < count ? selected : "");
  return snap;
}
async function follow(job) {
  while (job.state === "running") {
    status(progressText(job));
    await new Promise((resolve) => setTimeout(resolve, 1500));
    job = await rpc({ type: "status", job_id: job.job_id });
  }
  if (job.state === "failed") { clearJob(); throw new Error(job.message); }
  if (job.state === "no_cuts") { clearJob(); status("No cuts found inside this range. Your sequence is unchanged."); return; }
  if (job.state !== "ready") throw new Error("Job is not ready: " + job.state);
  status("Opening your rough cut in Premiere…");
  const saved = lastJob() || {};
  await workflow.importResult(ppro, job, saved.importAttempted,
    () => save({ ...saved, ...job, importAttempted: true }));
  clearJob();
  const note = job.output_note ? `\n${job.output_note}` : "";
  status(`${job.report.cuts_applied} cuts · ${(job.report.removed_ms / 1000).toFixed(1)} seconds removed.`
    + `\nOpened ${job.result_name}\nSaved ${job.output_path}${note}`);
}
async function act(fn) {
  if (busy) return;
  busy = true;
  ["cut", "refresh", "resume", "dismiss", "audio", "mode", "socketprobe", "timingprobe", "assembleprobe", "copystatus"].forEach((id) => $(id).disabled = true);
  try { await fn(); } catch (error) { status(error.message || String(error)); console.error(error); }
  finally {
    busy = false;
    ["cut", "refresh", "resume", "dismiss", "audio", "mode", "socketprobe", "timingprobe", "assembleprobe", "copystatus"].forEach((id) => $(id).disabled = false);
  }
}
$("refresh").addEventListener("click", () => act(async () => { await refresh(); status("Range ready. Click Rough Cut In–Out."); }));
$("cut").addEventListener("click", () => act(async () => {
  if (lastJob()) throw new Error("Resume the previous job before starting another rough cut.");
  const snap = await refresh();
  status("Preparing your sequence…");
  const track = $("audio").value;
  const job = await workflow.prepare(ppro, rpc, snap,
    { audio_track: track === "" ? null : Number(track), asr: $("mode").value === "protected" }, save);
  await follow(job);
}));
$("resume").addEventListener("click", () => act(async () => {
  const saved = lastJob();
  if (!saved) return;
  await rpc({ type: "hello", version: workflow.VERSION });
  let job;
  try { job = await rpc({ type: "status", job_id: saved.job_id }); }
  catch (error) {
    if (error.message.startsWith("Unknown job")) { clearJob(); }
    throw error;
  }
  if (job.state === "prepared") {
    if (!saved.exported) { clearJob(); status("The previous export did not finish. Start a new rough cut."); return; }
    job = await rpc({ type: "start", job_id: saved.job_id });
  }
  await follow(job);
}));
// Phase 0 probe 1. Read-only: it creates and changes nothing, so it is safe on a
// real project, and it needs no helper running.
$("timingprobe").addEventListener("click", () => act(async () => {
  status("Reading this build's marks and timebase…");
  const report = await capability.probeMarksAndTiming(ppro);
  console.log("CutDeck capability probe", JSON.stringify(report, null, 2));
  status(capability.formatReport(report));
}));

// The only control in this panel that mutates a project, so it arms before it runs.
// A misclick on a real edit would leave a stray sequence behind — recoverable, but
// the panel should not make it a one-click mistake. Disarms itself after 10s so an
// armed button can never be inherited by a later, unrelated click.
let assembleArmed = null;
function disarmAssemble() {
  if (assembleArmed) clearTimeout(assembleArmed);
  assembleArmed = null;
  $("assembleprobe").classList.remove("armed");
  $("assembleprobe").textContent = "Run assemble probe (MUTATES — disposable projects only)";
}
$("assembleprobe").addEventListener("click", () => {
  if (!assembleArmed) {
    assembleArmed = setTimeout(disarmAssemble, 10000);
    $("assembleprobe").classList.add("armed");
    $("assembleprobe").textContent = "Click again to run — this CREATES a sequence";
    status("The assemble probe mutates the open project: it creates a sequence, places three spans, "
      + "disables one and ripple-removes it. Use a DISPOSABLE project.\nClick the red button again "
      + "within 10 seconds to run it, or wait for it to disarm.");
    return;
  }
  disarmAssemble();
  act(async () => {
    status("Running the assemble probe (issue #25, Phase 0)…");
    const report = await assemble.runAssembleProbe(ppro, (line) => console.log("[assemble probe]", line));
    console.log("CutDeck assemble probe", JSON.stringify(report, null, 2));
    status(assemble.formatReport(report));
  });
});

// Diagnostic only, and never on load: it opens sockets, so running it automatically would
// make a panel that needs no helper report a helper failure every time it opens.
$("socketprobe").addEventListener("click", () => act(async () => {
  status("Probing which socket URLs this Premiere build permits…");
  const { report, written } = await probe.run();
  status([`Socket permission probe:`, ...report.results.map((r) => `${r.url} -> ${r.outcome}`),
    ``, `written: ${written}`].join(`\n`));
}));

// Probe reports are long and are meant to be pasted onto an issue. Dual fallback
// (navigator.clipboard, then the uxp module's) is the pattern spike18 confirmed
// against a live Premiere plugin rather than assumed.
$("copystatus").addEventListener("click", () => act(async () => {
  const text = $("status").textContent;
  if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(text);
  else if (require("uxp").clipboard) require("uxp").clipboard.copyText(text);
  else throw new Error("No clipboard API on this build. The full report is in the UXP Developer Tool console as JSON.");
  status(text + "\n\n--- copied to clipboard ---");
}));

$("resume").hidden = !lastJob();
$("dismiss").hidden = !lastJob();
$("dismiss").addEventListener("click", () => act(async () => {
  const saved = lastJob();
  clearJob();
  status("Previous job dismissed. Any running analysis continues in the helper. Saved result location:\n" + (saved ? saved.output_path : ""));
}));
