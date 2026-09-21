/* CutDeck CEP Panel Main Controller */

(function () {
  const $ = (id) => document.getElementById(id);
  const KEY = "cutdeck.cep.lastJob";
  const SETTINGS_KEY = "cutdeck.adj.settings";
  let busy = false;

  const DEFAULT_SETTINGS = {
    frames: 16,
    bin: "CutDeck AL/FX",
    color: "Iris",
    clamp: true,
    activeFx: "Zoom In",
    fxList: [
      "Zoom In", "Zoom Out", "Whip Pan L", "Whip Pan R",
      "Camera Shake", "Motion Blur", "Film Glow", "Letterbox", "Custom FX"
    ]
  };

  function loadSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null");
      return { ...DEFAULT_SETTINGS, ...saved };
    } catch (_) {
      return { ...DEFAULT_SETTINGS };
    }
  }

  function saveSettings(s) {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
    } catch (_) {}
    updateUIFromSettings(s);
  }

  function updateUIFromSettings(s) {
    if ($("setting-frames")) $("setting-frames").value = s.frames;
    if ($("setting-bin")) $("setting-bin").value = s.bin;
    if ($("setting-color")) $("setting-color").value = s.color;
    if ($("setting-clamp")) $("setting-clamp").checked = !!s.clamp;
    if ($("setting-active-fx")) $("setting-active-fx").value = s.activeFx;

    // Highlight mini pills if matching
    const miniPills = document.querySelectorAll(".pill-mini");
    miniPills.forEach((p) => {
      const f = parseInt(p.getAttribute("data-frames"), 10);
      if (f === s.frames) {
        p.classList.add("active");
      } else {
        p.classList.remove("active");
      }
    });

    if ($("badge-transition")) {
      $("badge-transition").textContent = `⚡ ${s.frames}f (50/50)`;
    }
    if ($("badge-active-fx")) {
      $("badge-active-fx").textContent = `✦ Active: ${s.activeFx}`;
    }
  }

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
    const targets = [
      "cut", "sync", "refresh", "resume", "dismiss", "audio", "mode",
      "socketprobe", "copystatus", "tab-edit", "tab-adj", "pill-speech",
      "pill-silence", "btn-adj", "btn-fx", "badge-transition", "badge-active-fx",
      "btn-capture-preset"
    ];
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

  // 1. Two-Page Tab Navigation: Cut & Sync vs Adjustment & FX
  function setupTabs() {
    const tabEdit = $("tab-edit");
    const tabAdj = $("tab-adj");
    const viewEdit = $("view-edit");
    const viewAdj = $("view-adj");

    if (!tabEdit || !tabAdj || !viewEdit || !viewAdj) return;

    tabEdit.addEventListener("click", () => {
      tabEdit.classList.add("active");
      tabAdj.classList.remove("active");
      viewEdit.classList.add("active");
      viewAdj.classList.remove("active");
    });

    tabAdj.addEventListener("click", () => {
      tabAdj.classList.add("active");
      tabEdit.classList.remove("active");
      viewAdj.classList.add("active");
      viewEdit.classList.remove("active");
    });
  }

  // 2. Preset Pills for Rough Cut
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

  // 3. Settings & Configuration Drawer (3-Dots Button)
  function setupSettingsDrawer() {
    const toggleBtn = $("tools-toggle");
    const closeBtn = $("close-settings");
    const diag = $("diagnostics");

    if (toggleBtn && diag) {
      toggleBtn.addEventListener("click", () => {
        diag.classList.toggle("open");
      });
    }

    if (closeBtn && diag) {
      closeBtn.addEventListener("click", () => {
        diag.classList.remove("open");
      });
    }

    // Mini pill frame buttons
    const miniPills = document.querySelectorAll(".pill-mini");
    miniPills.forEach((p) => {
      p.addEventListener("click", () => {
        const frames = parseInt(p.getAttribute("data-frames"), 10);
        if (frames > 0) {
          const s = loadSettings();
          s.frames = frames;
          saveSettings(s);
        }
      });
    });

    // Stepper buttons
    if ($("frame-dec")) {
      $("frame-dec").addEventListener("click", () => {
        const s = loadSettings();
        if (s.frames > 2) {
          s.frames -= 2;
          saveSettings(s);
        }
      });
    }
    if ($("frame-inc")) {
      $("frame-inc").addEventListener("click", () => {
        const s = loadSettings();
        if (s.frames < 240) {
          s.frames += 2;
          saveSettings(s);
        }
      });
    }
    if ($("setting-frames")) {
      $("setting-frames").addEventListener("change", (e) => {
        const val = parseInt(e.target.value, 10);
        if (!isNaN(val) && val >= 2 && val <= 240) {
          const s = loadSettings();
          s.frames = val;
          saveSettings(s);
        }
      });
    }

    // Bin Name input
    if ($("setting-bin")) {
      $("setting-bin").addEventListener("change", (e) => {
        const s = loadSettings();
        s.bin = e.target.value.trim() || "CutDeck AL/FX";
        saveSettings(s);
      });
    }

    // Color selector
    if ($("setting-color")) {
      $("setting-color").addEventListener("change", (e) => {
        const s = loadSettings();
        s.color = e.target.value;
        saveSettings(s);
      });
    }

    // Clamp checkbox
    if ($("setting-clamp")) {
      $("setting-clamp").addEventListener("change", (e) => {
        const s = loadSettings();
        s.clamp = e.target.checked;
        saveSettings(s);
      });
    }

    // Active FX preset dropdown
    if ($("setting-active-fx")) {
      $("setting-active-fx").addEventListener("change", (e) => {
        const s = loadSettings();
        s.activeFx = e.target.value;
        saveSettings(s);
      });
    }

    // Capture preset button
    if ($("btn-capture-preset")) {
      $("btn-capture-preset").addEventListener("click", () => act(async () => {
        const s = loadSettings();
        const safeName = JSON.stringify(s.activeFx);
        const rawRes = await evalScript("captureSelectedClipAsPreset(" + safeName + ")");
        const res = typeof rawRes === "string" ? JSON.parse(rawRes) : rawRes;
        if (res.error) throw new Error(res.error);
        setStatus(`Captured timeline clip as [${res.presetName || s.activeFx}] in bin [${s.bin}]`, "ready");
      }));
    }
  }

  // 4. Interactive Quick Badges
  function setupBadges() {
    // Transition frames badge: cycle 8 -> 12 -> 16 -> 20 -> 24 -> 8
    const badgeTrans = $("badge-transition");
    if (badgeTrans) {
      badgeTrans.addEventListener("click", () => {
        const s = loadSettings();
        const sequence = [8, 12, 16, 20, 24];
        let idx = sequence.indexOf(s.frames);
        idx = (idx + 1) % sequence.length;
        s.frames = sequence[idx];
        saveSettings(s);
        setStatus(`Transition duration set to ${s.frames} frames (50/50)`, "ready");
      });
    }

    // Active FX badge: cycle through presets
    const badgeFx = $("badge-active-fx");
    if (badgeFx) {
      badgeFx.addEventListener("click", () => {
        const s = loadSettings();
        const list = s.fxList || DEFAULT_SETTINGS.fxList;
        let idx = list.indexOf(s.activeFx);
        idx = (idx + 1) % list.length;
        s.activeFx = list[idx];
        saveSettings(s);
        setStatus(`Active FX preset switched to: ${s.activeFx}`, "ready");
      });
    }
  }

  // 5. Button 1: Adjustment Layer (`#btn-adj`)
  function setupAdjustmentLayerButton() {
    const btn = $("btn-adj");
    if (!btn) return;

    btn.addEventListener("click", (e) => act(async () => {
      const s = loadSettings();
      const isCtrl = e.ctrlKey || e.metaKey;
      const isShift = e.shiftKey;

      const mode = isShift ? "transition" : "span";
      const effectName = isCtrl ? s.activeFx : "";

      const payload = JSON.stringify({
        mode: mode,
        binName: s.bin,
        labelColor: s.color,
        transitionFrames: s.frames,
        clampShortClips: s.clamp,
        effectName: effectName
      });

      setStatus(
        mode === "transition"
          ? `Creating 50/50 cut transition (${s.frames}f)…`
          : "Fitting Adjustment Layer over selected clips…",
        "busy"
      );

      const rawRes = await evalScript("placeAdjustmentLayers(" + JSON.stringify(payload) + ")");
      const res = typeof rawRes === "string" ? JSON.parse(rawRes) : rawRes;
      if (res.error) throw new Error(res.error);

      let msg = mode === "transition"
        ? `Added ${res.placedCount} transition AL (${s.frames}f 50/50)`
        : `Spanned ${res.placedCount} clip(s) with Adjustment Layer`;
      if (effectName) {
        msg += ` + ${effectName}`;
      }
      msg += ` in [${res.bin}]`;
      setStatus(msg, "ready");
    }));
  }

  // 6. Button 2: Effect Preset (`#btn-fx`)
  function setupEffectButton() {
    const btn = $("btn-fx");
    if (!btn) return;

    btn.addEventListener("click", (e) => act(async () => {
      const s = loadSettings();

      // Alt + Click: Capture selected timeline AL as preset
      if (e.altKey) {
        const safeName = JSON.stringify(s.activeFx);
        const rawRes = await evalScript("captureSelectedClipAsPreset(" + safeName + ")");
        const res = typeof rawRes === "string" ? JSON.parse(rawRes) : rawRes;
        if (res.error) throw new Error(res.error);
        setStatus(`Captured timeline clip as [${res.presetName || s.activeFx}] in bin [${s.bin}]`, "ready");
        return;
      }

      // Shift + Click: Cycle to next preset
      if (e.shiftKey) {
        const list = s.fxList || DEFAULT_SETTINGS.fxList;
        let idx = list.indexOf(s.activeFx);
        idx = (idx + 1) % list.length;
        s.activeFx = list[idx];
        saveSettings(s);
        setStatus(`Active FX preset set to: ${s.activeFx}`, "ready");
        return;
      }

      // Normal Click: Apply active preset over selection
      const payload = JSON.stringify({
        mode: "span",
        binName: s.bin,
        labelColor: s.color,
        transitionFrames: s.frames,
        clampShortClips: s.clamp,
        effectName: s.activeFx
      });

      setStatus(`Applying preset [${s.activeFx}] to selection…`, "busy");
      const rawRes = await evalScript("placeAdjustmentLayers(" + JSON.stringify(payload) + ")");
      const res = typeof rawRes === "string" ? JSON.parse(rawRes) : rawRes;
      if (res.error) throw new Error(res.error);

      setStatus(`Applied [${s.activeFx}] to ${res.placedCount} clip(s) in [${res.bin}]`, "ready");
    }));
  }

  // Sequence Card Click -> Refresh
  if ($("seq-card")) {
    $("seq-card").addEventListener("click", () => act(async () => {
      await refresh();
      setStatus("Timeline range updated.", "ready");
    }));
  }

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

  // Initialize UI components
  setupTabs();
  setupPresets();
  setupSettingsDrawer();
  setupBadges();
  setupAdjustmentLayerButton();
  setupEffectButton();

  // Load and apply persistent settings
  const initialSettings = loadSettings();
  updateUIFromSettings(initialSettings);

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
      setStatus("Ready. Choose Cut & Sync or Adjustment & FX.", "ready");
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
