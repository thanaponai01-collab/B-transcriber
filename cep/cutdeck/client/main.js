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
  const createRpc = (window.CutDeckRpc || require("./core/rpc.js")).createRpc;
  const progressText = (window.CutDeckProgressText || require("./core/progressText.js")).progressText;
  const helperManager = window.CutDeckHelperManager || (typeof require !== "undefined" ? require("./helper_manager.js") : null);

  const rpc = createRpc({
    onRetry: (attempt, total) => setStatus(`Connecting to CutDeck helper… attempt ${attempt} of ${total}.`, "busy"),
  });

  async function ensureHelper() {
    if (helperManager) {
      return helperManager.ensureHelperRunning({
        rpc,
        version: workflow.VERSION,
        csInterface,
        onStatus: (msg) => setStatus(msg, "busy"),
      });
    }
  }

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

  function time(seconds) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;
  }

  async function refresh() {
    const snap = await workflow.capture();
    if ($("sequence")) $("sequence").textContent = snap.context.sequence_name;
    const isFullSeq = snap.inSeconds === 0 && Math.abs(snap.outSeconds - snap.endSeconds) < 0.1;
    if ($("range")) {
      $("range").textContent = isFullSeq
        ? `Full: ${time(snap.outSeconds)}`
        : `${time(snap.inSeconds)} → ${time(snap.outSeconds)}`;
    }
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
      add("", "Auto (First track with clips)");
      const count = snap.context.audio_track_count;
      for (let i = 0; i < count; i++) {
        add(String(i), `Audio Track ${i + 1}`);
      }
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
    if (job.state === "failed") {
      clearJob();
      setStatus(job.message, "error");
      throw new Error(job.message);
    }
    if (job.state === "no_cuts") {
      clearJob();
      setStatus("No cuts found inside this range. Sequence unchanged.", "ready");
      return;
    }
    if (job.state !== "ready") {
      setStatus("Job error: " + job.state, "error");
      throw new Error("Job is not ready: " + job.state);
    }

    if (job.job_type === "sync") {
      setStatus("Opening synchronized multi-cam sequence…", "busy");
      const saved = lastJob() || {};
      await workflow.importResult(job, saved.importAttempted, () => save({ ...saved, ...job, importAttempted: true }));
      clearJob();
      const rep = job.report || {};
      let msg = `Multi-cam sync complete (${rep.synced_groups || 0} angles).`;
      if (rep.unsynced_groups > 0) {
        msg += ` ${rep.unsynced_groups} placed at end.`;
      }
      msg += ` Opened ${job.result_name}`;
      setStatus(msg, "ready");
      return;
    }

    setStatus("Opening rough cut in Premiere…", "busy");
    const saved = lastJob() || {};
    await workflow.importResult(job, saved.importAttempted, () => save({ ...saved, ...job, importAttempted: true }));
    clearJob();
    setStatus(`${job.report.cuts_applied} cuts · ${(job.report.removed_ms / 1000).toFixed(1)}s removed. Opened ${job.result_name}`, "ready");
  }

  async function act(fn) {
    if (busy) return;
    busy = true;
    const targets = ["cut", "sync", "refresh", "resume", "dismiss", "audio", "mode", "socketprobe", "copystatus", "tab-sync", "tab-cut", "pill-speech", "pill-silence"];
    targets.forEach((id) => {
      if ($(id)) $(id).disabled = true;
    });
    setStatus("Processing…", "busy");
    try {
      await fn();
    } catch (error) {
      setStatus(error.message || String(error), "error");
      console.error(error);
    } finally {
      busy = false;
      targets.forEach((id) => {
        if ($(id)) $(id).disabled = false;
      });
      if ($("state-text") && $("state-text").textContent === "BUSY") {
        setStatus($("status") ? $("status").textContent : "Ready", "ready");
      }
    }
  }

  // --- UI Interactivity ---

  // 1. Tab Navigation: Multi-Cam (Default) vs Rough Cut
  function setupTabs() {
    const tabSync = $("tab-sync");
    const tabCut = $("tab-cut");
    const viewSync = $("view-sync");
    const viewCut = $("view-cut");

    if (!tabSync || !tabCut || !viewSync || !viewCut) return;

    tabSync.addEventListener("click", () => {
      tabSync.classList.add("active");
      tabCut.classList.remove("active");
      viewSync.classList.add("active");
      viewCut.classList.remove("active");
    });

    tabCut.addEventListener("click", () => {
      tabCut.classList.add("active");
      tabSync.classList.remove("active");
      viewCut.classList.add("active");
      viewSync.classList.remove("active");
    });
  }

  // 2. Preset Pills for Cutting Mode
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

  // 3. Diagnostics Drawer Toggle
  function setupDiagnostics() {
    const toggleBtn = $("tools-toggle");
    const diag = $("diagnostics");
    if (toggleBtn && diag) {
      toggleBtn.addEventListener("click", () => {
        diag.classList.toggle("open");
      });
    }
  }

  // 4. Click Sequence Card to re-read timeline
  if ($("seq-card")) {
    $("seq-card").addEventListener("click", () => act(async () => {
      await refresh();
      setStatus("Timeline range updated.", "ready");
    }));
  }

  // Button actions
  if ($("refresh")) {
    $("refresh").addEventListener("click", () => act(async () => {
      await refresh();
      setStatus("Timeline marks updated.", "ready");
      ensureHelper().catch(() => {});
    }));
  }

  if ($("sync")) {
    $("sync").addEventListener("click", () => act(async () => {
      if (lastJob()) throw new Error("Resume or dismiss the previous job before starting another operation.");
      await ensureHelper();
      const snap = await refresh();
      setStatus("Exporting sequence XML for multi-camera sync…", "busy");
      const track = $("audio") ? $("audio").value : "";
      const job = await workflow.prepareSync(rpc, snap, {
        audio_track: track === "" ? null : Number(track),
      }, save);
      await follow(job);
    }));
  }

  if ($("cut")) {
    $("cut").addEventListener("click", () => act(async () => {
      if (lastJob()) throw new Error("Resume or dismiss the previous job before starting another rough cut.");
      await ensureHelper();
      const snap = await refresh();
      setStatus("Exporting sequence XML to helper…", "busy");
      const track = $("audio") ? $("audio").value : "";
      const modeVal = $("mode") ? $("mode").value : "protected";
      const job = await workflow.prepare(rpc, snap, {
        audio_track: track === "" ? null : Number(track),
        asr: modeVal === "protected",
      }, save);
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
          setStatus("Previous export did not finish. Start a new job.", "ready");
          return;
        }
        job = await rpc({ type: "start", job_id: saved.job_id });
      }
      await follow(job);
    }));
  }

  if ($("dismiss")) {
    $("dismiss").addEventListener("click", () => act(async () => {
      clearJob();
      setStatus("Previous job dismissed.", "ready");
    }));
  }

  if ($("socketprobe")) {
    $("socketprobe").addEventListener("click", () => act(async () => {
      setStatus("Connecting to CutDeck helper…", "busy");
      try {
        await ensureHelper();
        const res = await rpc({ type: "hello", version: workflow.VERSION });
        setStatus(`Helper online (v${res.version})`, "ready");
      } catch (err) {
        setStatus("Failed to connect: " + (err.message || String(err)), "error");
      }
    }));
  }

  if ($("copystatus")) {
    $("copystatus").addEventListener("click", () => {
      const text = $("status") ? $("status").textContent : "";
      let copied = false;
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
        const orig = $("copystatus").textContent;
        $("copystatus").textContent = "Copied!";
        setTimeout(() => { if ($("copystatus")) $("copystatus").textContent = orig; }, 1500);
      }
    });
  }

  // Init handlers
  setupTabs();
  setupPresets();
  setupDiagnostics();

  // Initial state on panel open
  if (lastJob()) {
    if ($("job-banner")) $("job-banner").classList.add("show");
    if ($("resume")) $("resume").hidden = false;
    if ($("dismiss")) $("dismiss").hidden = false;
  }

  // 1. Immediately read and display timeline marks
  setTimeout(async () => {
    try {
      await refresh();
      setStatus("Ready. Set In/Out and click Sync or Cut.", "ready");
    } catch (_) {
      setStatus("Open a sequence in Premiere to begin.", "ready");
    }
  }, 50);

  // 2. Ensure helper is running in background concurrently
  setTimeout(async () => {
    try {
      await ensureHelper();
    } catch (err) {
      setStatus(err.message || String(err), "error");
    }
  }, 100);
})();
