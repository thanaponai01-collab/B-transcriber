const ppro = require("premierepro");
const workflow = require("./workflow.js");
const $ = (id) => document.getElementById(id);
const KEY = "cutdeck.xml.lastJob";
let busy = false;

// One short connection per request makes reconnects independent of long GPU jobs.
function rpc(request) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket("ws://127.0.0.1:7891");
    let settled = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.close();
      if (error) reject(error); else resolve(result);
    };
    const timer = setTimeout(() => finish(new Error("CutDeck helper timed out. Start the helper and use Resume last job.")), 15000);
    socket.onopen = () => socket.send(JSON.stringify(request));
    socket.onmessage = (event) => {
      try {
        const result = JSON.parse(event.data);
        finish(result.ok ? null : new Error(result.message), result);
      } catch (error) { finish(error); }
    };
    socket.onerror = () => finish(new Error("Cannot reach CutDeck. Run Start CutDeck.cmd, then try again."));
    socket.onclose = () => finish(new Error("Helper disconnected. Use Resume last job after reconnecting."));
  });
}

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
    status("Analyzing the full sequence with your current preset. Cuts will stay inside the captured In/Out range.\nThis can take several minutes.");
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
  status(`${job.report.cuts_applied} cuts · ${(job.report.removed_ms / 1000).toFixed(1)} seconds removed.\nOpened ${job.result_name}`);
}
async function act(fn) {
  if (busy) return;
  busy = true;
  ["cut", "refresh", "resume", "dismiss", "audio", "mode"].forEach((id) => $(id).disabled = true);
  try { await fn(); } catch (error) { status(error.message || String(error)); console.error(error); }
  finally {
    busy = false;
    ["cut", "refresh", "resume", "dismiss", "audio", "mode"].forEach((id) => $(id).disabled = false);
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
$("resume").hidden = !lastJob();
$("dismiss").hidden = !lastJob();
$("dismiss").addEventListener("click", () => act(async () => {
  const saved = lastJob();
  clearJob();
  status("Previous job dismissed. Any running analysis continues in the helper. Saved result location:\n" + (saved ? saved.output_path : ""));
}));
