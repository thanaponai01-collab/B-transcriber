/* The UXP panel's UI seam (source of truth: panel/core/panel.js; run scripts/sync_panel_core.py
   after editing). This is the only file in the panel allowed to call getElementById, classList,
   textContent or addEventListener — see docs/arch-design-panel-ui.md and issue #45.

   Two exports only:
     render(state)  — state -> screen. A pure sink: writes the DOM, never reads it back, and is
                       idempotent (calling it twice with the same state mutates nothing further).
     bind(intents)  — attaches every listener once at init. Handlers receive intent data
                       (a mode, a patch, a name), never raw DOM events.

   Menu/settings-modal open-close and the assemble-probe arm/disarm countdown are the one
   exception: they are purely presentational, never persisted and never read by the controller,
   so they stay local state inside this module rather than round-tripping through main.js. */
(function (global) {
  function $(id) {
    return document.getElementById(id);
  }

  let current = null;

  function setText(el, value) {
    if (el && el.textContent !== value) el.textContent = value;
  }
  function setValue(el, value) {
    if (el && String(el.value) !== String(value)) el.value = value;
  }
  function setChecked(el, value) {
    if (el && el.checked !== value) el.checked = value;
  }
  function setActive(el, active) {
    if (!el) return;
    if (active) el.classList.add("active");
    else el.classList.remove("active");
  }
  function setHidden(el, hidden) {
    if (el && el.hidden !== hidden) el.hidden = hidden;
  }
  function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
  }

  // --- render: state -> screen -------------------------------------------------------------

  function renderStatus(status) {
    if (!status) return;
    setText($("status"), status.text);
    const dot = $("dot");
    if (dot) {
      dot.classList.toggle("busy", status.level === "busy");
      dot.classList.toggle("error", status.level === "error");
    }
    const icon = $("status-icon");
    if (icon) {
      icon.classList.toggle("busy", status.level === "busy");
      icon.classList.toggle("error", status.level === "error");
    }
  }

  function renderSequence(sequence) {
    setText($("sequence"), sequence ? sequence.name : "No sequence open");
    setText(
      $("range"),
      sequence ? `${formatTime(sequence.inSeconds)} → ${formatTime(sequence.outSeconds)}` : "--:--"
    );
  }

  function renderAudioOptions(sequence, audioTrack) {
    const select = $("audio");
    if (!select) return;
    const count = sequence ? sequence.audioTrackCount : 0;
    const desired = [{ value: "", label: "Auto" }];
    for (let i = 0; i < count; i++) desired.push({ value: String(i), label: `Track A${i + 1}` });

    const existing = Array.prototype.slice.call(select.children || []);
    const same =
      existing.length === desired.length &&
      existing.every((opt, i) => opt.value === desired[i].value && opt.textContent === desired[i].label);
    if (!same) {
      select.innerHTML = "";
      desired.forEach((d) => {
        const option = document.createElement("option");
        option.value = d.value;
        option.setAttribute("value", d.value);
        option.textContent = d.label;
        select.appendChild(option);
      });
    }
    const desiredValue = audioTrack === null || audioTrack === undefined ? "" : String(audioTrack);
    setValue(select, desiredValue);
  }

  function renderTabs(tab) {
    setActive($("tab-edit"), tab === "edit");
    setActive($("tab-adj"), tab === "adj");
    setActive($("view-edit"), tab === "edit");
    setActive($("view-adj"), tab === "adj");
  }

  function renderCutMode(cutMode) {
    setActive($("pill-speech"), cutMode === "protected");
    setActive($("pill-silence"), cutMode === "silence");
    setValue($("mode"), cutMode);
  }

  function renderSettings(settings) {
    if (!settings) return;
    setValue($("setting-frames"), settings.frames);
    setValue($("setting-bin"), settings.bin);
    setValue($("setting-color"), settings.color);
    setChecked($("setting-clamp"), !!settings.clamp);
    setValue($("setting-active-fx"), settings.activeFx);

    document.querySelectorAll(".pill-mini").forEach((p) => {
      const f = parseInt(p.getAttribute("data-frames"), 10);
      setActive(p, f === settings.frames);
    });

    setText($("badge-transition-text"), `${settings.frames}f (50/50)`);
    setText($("badge-active-fx-text"), settings.activeFx);
  }

  function renderJobBanner(job) {
    const banner = $("job-banner");
    if (banner) banner.classList.toggle("show", !!job);
    setHidden($("resume"), !job);
    setHidden($("dismiss"), !job);
  }

  function renderBusy(busy) {
    document.querySelectorAll("[data-act]").forEach((el) => {
      if (busy) {
        el.disabled = true;
        el.setAttribute("disabled", "true");
        el.classList.add("disabled");
      } else {
        el.disabled = false;
        el.removeAttribute("disabled");
        el.classList.remove("disabled");
      }
    });
  }

  function render(state) {
    if (!state) return;
    current = state;
    renderStatus(state.status);
    renderSequence(state.sequence);
    renderAudioOptions(state.sequence, state.audioTrack);
    renderTabs(state.tab);
    renderCutMode(state.cutMode);
    renderSettings(state.settings);
    renderJobBanner(state.job);
    renderBusy(state.busy);
  }

  // --- bind: DOM events -> intents -----------------------------------------------------------

  function bindTabs(intents) {
    const tabEdit = $("tab-edit");
    const tabAdj = $("tab-adj");
    if (tabEdit) tabEdit.addEventListener("click", () => intents.onTab("edit"));
    if (tabAdj) tabAdj.addEventListener("click", () => intents.onTab("adj"));
  }

  function bindCutModePills(intents) {
    const pillSpeech = $("pill-speech");
    const pillSilence = $("pill-silence");
    if (pillSpeech) pillSpeech.addEventListener("click", () => intents.onCutMode("protected"));
    if (pillSilence) pillSilence.addEventListener("click", () => intents.onCutMode("silence"));
  }

  function bindAudioSelect(intents) {
    const audio = $("audio");
    if (!audio) return;
    audio.addEventListener("change", (e) => {
      const v = e.target.value;
      intents.onSettingChange({ audioTrack: v === "" ? null : Number(v) });
    });
  }

  function bindPrimaryActions(intents) {
    const seqCard = $("seq-card");
    if (seqCard) seqCard.addEventListener("click", () => intents.onRefresh());
    const refresh = $("refresh");
    if (refresh) refresh.addEventListener("click", () => intents.onRefresh());
    const cut = $("cut");
    if (cut) cut.addEventListener("click", () => intents.onCut());
    const sync = $("sync");
    if (sync) sync.addEventListener("click", () => intents.onSync());
  }

  function bindJobRecovery(intents) {
    const resume = $("resume");
    if (resume) resume.addEventListener("click", () => intents.onResumeJob());
    const dismiss = $("dismiss");
    if (dismiss) dismiss.addEventListener("click", () => intents.onDismissJob());
  }

  function bindOverflowMenuAndSettings(intents) {
    const toggleBtn = $("tools-toggle");
    const overflowMenu = $("overflow-menu");
    const settingsModal = $("settings-modal");
    const closeBtn = $("close-settings");
    const settingsMenuItem = $("menu-item-settings");
    const reloadMenuItem = $("menu-item-reload");

    if (toggleBtn && overflowMenu) {
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        overflowMenu.classList.toggle("open");
      });
    }
    if (settingsMenuItem && settingsModal) {
      settingsMenuItem.addEventListener("click", (e) => {
        e.stopPropagation();
        if (overflowMenu) overflowMenu.classList.remove("open");
        settingsModal.classList.add("open");
      });
    }
    if (closeBtn && settingsModal) {
      closeBtn.addEventListener("click", () => settingsModal.classList.remove("open"));
    }
    document.addEventListener("click", (e) => {
      if (overflowMenu && overflowMenu.classList.contains("open")) {
        if (!overflowMenu.contains(e.target) && !(toggleBtn && toggleBtn.contains(e.target))) {
          overflowMenu.classList.remove("open");
        }
      }
    });
    if (settingsModal) {
      settingsModal.addEventListener("click", (e) => {
        if (e.target === settingsModal) settingsModal.classList.remove("open");
      });
    }
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (overflowMenu && overflowMenu.classList.contains("open")) overflowMenu.classList.remove("open");
        if (settingsModal && settingsModal.classList.contains("open")) settingsModal.classList.remove("open");
      }
    });
    if (reloadMenuItem) {
      reloadMenuItem.addEventListener("click", () => {
        if (overflowMenu) overflowMenu.classList.remove("open");
        window.location.reload();
      });
    }
    ["socketprobe", "copystatus", "timingprobe"].forEach((id) => {
      const el = $(id);
      if (el && overflowMenu) {
        el.addEventListener("click", () => overflowMenu.classList.remove("open"));
      }
    });
  }

  function bindMiniPills(intents) {
    document.querySelectorAll(".pill-mini").forEach((p) => {
      p.addEventListener("click", () => {
        const frames = parseInt(p.getAttribute("data-frames"), 10);
        if (frames > 0) intents.onSettingChange({ frames });
      });
    });
  }

  function currentFrames() {
    return current && current.settings ? current.settings.frames : 16;
  }
  function currentFxList() {
    const settings = current && current.settings;
    return settings ? { list: settings.fxList || [], activeFx: settings.activeFx } : { list: [], activeFx: null };
  }

  function bindFrameStepper(intents) {
    const dec = $("frame-dec");
    if (dec) {
      dec.addEventListener("click", () => {
        const frames = currentFrames();
        if (frames > 2) intents.onSettingChange({ frames: frames - 2 });
      });
    }
    const inc = $("frame-inc");
    if (inc) {
      inc.addEventListener("click", () => {
        const frames = currentFrames();
        if (frames < 240) intents.onSettingChange({ frames: frames + 2 });
      });
    }
  }

  function bindSettingInputs(intents) {
    const framesInput = $("setting-frames");
    if (framesInput) {
      framesInput.addEventListener("change", (e) => {
        const val = parseInt(e.target.value, 10);
        if (!isNaN(val) && val >= 2 && val <= 240) intents.onSettingChange({ frames: val });
      });
    }
    const binInput = $("setting-bin");
    if (binInput) {
      binInput.addEventListener("change", (e) => {
        intents.onSettingChange({ bin: e.target.value.trim() || "CutDeck AL/FX" });
      });
    }
    const colorInput = $("setting-color");
    if (colorInput) {
      colorInput.addEventListener("change", (e) => intents.onSettingChange({ color: e.target.value }));
    }
    const clampInput = $("setting-clamp");
    if (clampInput) {
      clampInput.addEventListener("change", (e) => intents.onSettingChange({ clamp: e.target.checked }));
    }
    const fxInput = $("setting-active-fx");
    if (fxInput) {
      fxInput.addEventListener("change", (e) => intents.onSettingChange({ activeFx: e.target.value }));
    }
  }

  function bindCapturePreset(intents) {
    const btn = $("btn-capture-preset");
    if (btn) btn.addEventListener("click", () => intents.onProbe("capture-preset"));
  }

  const FRAME_CYCLE = [8, 12, 16, 20, 24];

  function bindBadges(intents) {
    const badgeTrans = $("badge-transition");
    if (badgeTrans) {
      badgeTrans.addEventListener("click", () => {
        const frames = currentFrames();
        let idx = FRAME_CYCLE.indexOf(frames);
        idx = (idx + 1) % FRAME_CYCLE.length;
        const next = FRAME_CYCLE[idx];
        intents.onSettingChange({ frames: next, statusText: `Transition duration set to ${next} frames (50/50)` });
      });
    }
    const badgeFx = $("badge-active-fx");
    if (badgeFx) {
      badgeFx.addEventListener("click", () => {
        const { list, activeFx } = currentFxList();
        if (!list.length) return;
        let idx = list.indexOf(activeFx);
        idx = (idx + 1) % list.length;
        const next = list[idx];
        intents.onSettingChange({ activeFx: next, statusText: `Active preset switched to: ${next}` });
      });
    }
  }

  function bindAdjustmentButtons(intents) {
    const adjBtn = $("btn-adj");
    if (adjBtn) {
      adjBtn.addEventListener("click", (e) => {
        let mode = "span";
        if (e.shiftKey) mode = "transition";
        else if (e.ctrlKey || e.metaKey) mode = "per_clip";
        intents.onAdjust(mode);
      });
    }
    const fxBtn = $("btn-fx");
    if (fxBtn) {
      fxBtn.addEventListener("click", (e) => {
        if (e.shiftKey) {
          const { list, activeFx } = currentFxList();
          if (!list.length) return;
          let idx = list.indexOf(activeFx);
          idx = (idx + 1) % list.length;
          const next = list[idx];
          intents.onSettingChange({ activeFx: next, statusText: `Preset switched to: ${next}` });
          return;
        }
        const mode = e.ctrlKey || e.metaKey ? "per_clip" : "span";
        intents.onEffect(mode);
      });
    }
  }

  function bindProbes(intents) {
    const timing = $("timingprobe");
    if (timing) timing.addEventListener("click", () => intents.onProbe("timing"));
    const socket = $("socketprobe");
    if (socket) socket.addEventListener("click", () => intents.onProbe("socket"));
    const copy = $("copystatus");
    if (copy) copy.addEventListener("click", () => intents.onProbe("copystatus"));
  }

  function bind(intents) {
    bindTabs(intents);
    bindCutModePills(intents);
    bindAudioSelect(intents);
    bindPrimaryActions(intents);
    bindJobRecovery(intents);
    bindOverflowMenuAndSettings(intents);
    bindMiniPills(intents);
    bindFrameStepper(intents);
    bindSettingInputs(intents);
    bindCapturePreset(intents);
    bindBadges(intents);
    bindAdjustmentButtons(intents);
    bindProbes(intents);
  }

  const exportObj = { render, bind };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckPanel = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
