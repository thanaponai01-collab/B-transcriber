/* CutDeck CEP Panel Main Controller */

(function () {
  const $ = (id) => document.getElementById(id);
  const KEY = "cutdeck.cep.lastJob";
  let busy = false;

  // Initialize CSInterface and ensure host.jsx is loaded
  const csInterface = typeof CSInterface !== "undefined" ? new CSInterface() : null;
  if (csInterface) {
    try {
      const extPath = csInterface.getSystemPath("extension").replace(/\\/g, "/");
      csInterface.evalScript('try { $.evalFile("' + extPath + '/jsx/host.jsx"); } catch(e) {}');
    } catch (_) {}
  }

  function evalScript(code) {
    return new Promise((resolve, reject) => {
      if (!csInterface) {
        reject(new Error("CSInterface not found. Are you running inside Premiere Pro?"));
        return;
      }
      const wrapped = 'try { ' + code + '; } catch (e) { JSON.stringify({ error: String(e.message || e) }); }';
      csInterface.evalScript(wrapped, (result) => {
        if (result === "EvalScript error." || result === "EvalScript error") {
          reject(new Error("ExtendScript error occurred in Premiere Pro."));
          return;
        }
        resolve(result);
      });
    });
  }

  const workflow = (window.CutDeckWorkflow || require("./workflow.js")).createWorkflow(evalScript);
  const createRpc = (window.CutDeckRpc || require("./rpc.js")).createRpc;
  const helperManager = window.CutDeckHelperManager || (typeof require !== "undefined" ? require("./helper_manager.js") : null);

  const rpc = createRpc({
    onRetry: (attempt, total) => status(`Connecting to the CutDeck helper… attempt ${attempt} of ${total}.`),
  });

  async function ensureHelper() {
    if (helperManager) {
      return helperManager.ensureHelperRunning({
        rpc,
        version: workflow.VERSION,
        csInterface,
        onStatus: status,
      });
    }
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

  function status(message) {
    $("status").textContent = message;
  }

  function time(seconds) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
  }

  async function refresh() {
    const snap = await workflow.capture();
    $("sequence").textContent = snap.context.sequence_name;
    const isFullSeq = snap.inSeconds === 0 && Math.abs(snap.outSeconds - snap.endSeconds) < 0.1;
    $("range").textContent = isFullSeq
      ? `Full sequence: ${time(snap.outSeconds)}`
      : `In/Out: ${time(snap.inSeconds)} → ${time(snap.outSeconds)}`;
    const selected = $("audio").value;
    $("audio").innerHTML = "";
    const add = (value, label) => {
      const option = document.createElement("option");
      option.setAttribute("value", value);
      option.textContent = label;
      $("audio").appendChild(option);
    };
    add("", "First audio track with clips");
    const count = snap.context.audio_track_count;
    for (let i = 0; i < count; i++) {
      add(String(i), `Audio ${i + 1}`);
    }
    $("audio").setAttribute("value", selected === "" || Number(selected) < count ? selected : "");
    return snap;
  }

  async function follow(job) {
    while (job.state === "running") {
      status("Analyzing sequence audio with your current preset.\nCuts stay strictly inside the captured In/Out range.\nThis can take several minutes for long sequences.");
      await new Promise((resolve) => setTimeout(resolve, 1500));
      job = await rpc({ type: "status", job_id: job.job_id });
    }
    if (job.state === "failed") {
      clearJob();
      throw new Error(job.message);
    }
    if (job.state === "no_cuts") {
      clearJob();
      status("No cuts found inside this range. Your sequence is unchanged.");
      return;
    }
    if (job.state !== "ready") {
      throw new Error("Job is not ready: " + job.state);
    }

    if (job.job_type === "sync") {
      status("Opening synchronized multi-cam sequence in Premiere…");
      const saved = lastJob() || {};
      await workflow.importResult(job, saved.importAttempted, () => save({ ...saved, ...job, importAttempted: true }));
      clearJob();
      const rep = job.report || {};
      const note = job.output_note ? `\n${job.output_note}` : "";
      let msg = `Multi-cam sync complete! Synced ${rep.synced_groups || 0} angles.`;
      if (rep.unsynced_groups > 0) {
        msg += `\n${rep.unsynced_groups} angle(s) could not be synced with confidence and were placed at the end.`;
      }
      msg += `\nOpened ${job.result_name}\nSaved ${job.output_path}${note}`;
      status(msg);
      return;
    }

    status("Opening your rough cut in Premiere…");
    const saved = lastJob() || {};
    await workflow.importResult(job, saved.importAttempted, () => save({ ...saved, ...job, importAttempted: true }));
    clearJob();
    const note = job.output_note ? `\n${job.output_note}` : "";
    status(`${job.report.cuts_applied} cuts · ${(job.report.removed_ms / 1000).toFixed(1)} seconds removed.`
      + `\nOpened ${job.result_name}\nSaved ${job.output_path}${note}`);
  }

  async function act(fn) {
    if (busy) return;
    busy = true;
    ["cut", "sync", "refresh", "resume", "dismiss", "audio", "mode", "socketprobe", "copystatus"].forEach((id) => {
      if ($(id)) $(id).disabled = true;
    });
    try {
      await fn();
    } catch (error) {
      status(error.message || String(error));
      console.error(error);
    } finally {
      busy = false;
      ["cut", "sync", "refresh", "resume", "dismiss", "audio", "mode", "socketprobe", "copystatus"].forEach((id) => {
        if ($(id)) $(id).disabled = false;
      });
    }
  }

  $("refresh").addEventListener("click", () => act(async () => {
    await refresh();
    status("Range ready. Click Sync Multi-Cam or Rough Cut In–Out.");
    ensureHelper().catch(() => {});
  }));

  $("sync").addEventListener("click", () => act(async () => {
    if (lastJob()) throw new Error("Resume or dismiss the previous job before starting another operation.");
    await ensureHelper();
    const snap = await refresh();
    status("Exporting sequence XML to helper for multi-camera sync…");
    const track = $("audio").value;
    const job = await workflow.prepareSync(rpc, snap, {
      audio_track: track === "" ? null : Number(track),
    }, save);
    await follow(job);
  }));

  $("cut").addEventListener("click", () => act(async () => {
    if (lastJob()) throw new Error("Resume or dismiss the previous job before starting another rough cut.");
    await ensureHelper();
    const snap = await refresh();
    status("Exporting sequence XML to helper…");
    const track = $("audio").value;
    const job = await workflow.prepare(rpc, snap, {
      audio_track: track === "" ? null : Number(track),
      asr: $("mode").value === "protected",
    }, save);
    await follow(job);
  }));

  $("resume").addEventListener("click", () => act(async () => {
    const saved = lastJob();
    if (!saved) return;
    await ensureHelper();
    await rpc({ type: "hello", version: workflow.VERSION });
    let job;
    try {
      job = await rpc({ type: "status", job_id: saved.job_id });
    } catch (error) {
      if (error.message && error.message.startsWith("Unknown job")) {
        clearJob();
      }
      throw error;
    }
    if (job.state === "prepared") {
      if (!saved.exported) {
        clearJob();
        status("The previous export did not finish. Start a new rough cut.");
        return;
      }
      job = await rpc({ type: "start", job_id: saved.job_id });
    }
    await follow(job);
  }));

  $("dismiss").addEventListener("click", () => act(async () => {
    const saved = lastJob();
    clearJob();
    status("Previous job dismissed. Any running analysis continues in the helper. Saved result location:\n" + (saved ? saved.output_path : ""));
  }));

  $("socketprobe").addEventListener("click", () => act(async () => {
    status("Connecting to CutDeck helper…");
    try {
      await ensureHelper();
      const res = await rpc({ type: "hello", version: workflow.VERSION });
      status("Helper is running and reachable!\nVersion: " + res.version);
    } catch (err) {
      status("Failed to connect to helper:\n" + (err.message || String(err)));
    }
  }));

  $("copystatus").addEventListener("click", () => {
    const text = $("status").textContent;
    let copied = false;

    // 1. Synchronous textarea execCommand (standard for Adobe CEP panels)
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      ta.style.top = "-9999px";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      copied = document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (_) {}

    // 2. Windows clip fallback via Node.js
    if (!copied) {
      try {
        if (typeof require !== "undefined") {
          const { spawn } = require("child_process");
          const p = spawn("clip", { windowsHide: true });
          p.stdin.write(text);
          p.stdin.end();
          copied = true;
        }
      } catch (_) {}
    }

    if (copied) {
      status(text + "\n\n--- copied to clipboard ---");
    } else {
      status(text + "\n\n--- select text above and press Ctrl+C ---");
    }
  });

  // Initial state on panel open
  $("resume").hidden = !lastJob();
  $("dismiss").hidden = !lastJob();

  // 1. Immediately read and display timeline marks (<50ms)
  setTimeout(async () => {
    try {
      await refresh();
      status("Ready. Click Sync Multi-Cam or Rough Cut In–Out.");
    } catch (_) {
      status("Open a sequence in Premiere, then click Read timeline range.");
    }
  }, 50);

  // 2. Ensure helper is running in background concurrently
  setTimeout(async () => {
    try {
      await ensureHelper();
    } catch (err) {
      status(err.message || String(err));
    }
  }, 100);
})();
