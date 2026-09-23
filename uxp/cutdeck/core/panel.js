/* The UXP panel's UI seam. This is the only file in the panel allowed to call
   getElementById, classList, textContent or addEventListener — see
   docs/arch-design-panel-ui.md and issue #45.

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
  // Up to this many captured presets get their own quick-effect button below the Adjustment
  // Layer card, laid out as a 3-column grid. Bump this if more room is wanted later — nothing
  // else assumes exactly 9.
  const MAX_QUICK_PRESETS = 9;

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

    document.querySelectorAll(".pill-mini").forEach((p) => {
      const f = parseInt(p.getAttribute("data-frames"), 10);
      setActive(p, f === settings.frames);
    });
  }

  // One quick-effect button per captured preset (capped at MAX_QUICK_PRESETS), below the
  // Adjustment Layer card — same dynamic-content diff discipline as renderAudioOptions above,
  // rebuilt only when the underlying preset list actually changed. Always renders exactly
  // MAX_QUICK_PRESETS tiles (a full 3x3 grid), not just as many as are captured — an unfilled
  // slot is its own empty-tile button (click opens Settings to Capture one).
  function renderPresetButtons(customPresets) {
    const container = $("fx-preset-buttons");
    if (!container) return;
    const presets = customPresets || [];
    const desired = [];
    for (let i = 0; i < MAX_QUICK_PRESETS; i++) {
      desired.push(presets[i] ? { id: presets[i].id, name: presets[i].name } : null);
    }

    const existing = Array.prototype.slice.call(container.children || []);
    const same =
      existing.length === desired.length &&
      existing.every((el, i) => {
        const d = desired[i];
        return d
          ? el.getAttribute("data-preset-id") === d.id && el.textContent === d.name
          : el.classList.contains("fx-preset-empty-slot");
      });
    if (same) return;

    container.innerHTML = "";
    desired.forEach((d) => {
      const btn = document.createElement("div");
      btn.setAttribute("role", "button");
      if (d) {
        btn.className = "fx-preset-btn";
        btn.setAttribute("data-act", "fx-preset-btn");
        btn.setAttribute("data-preset-id", d.id);
        btn.title = `${d.name} (Click: Span | Ctrl: Each Clip | Shift: Every Cut)`;
        btn.textContent = d.name;
      } else {
        btn.className = "fx-preset-btn fx-preset-empty-slot";
        btn.setAttribute("data-act", "fx-preset-empty-slot");
        btn.title = "Capture a preset in Settings to fill this slot";
        // SVG plus, not a "+" glyph: keeps the icon the same crisp size/weight in every
        // slot regardless of font metrics, matching the icon language used elsewhere in
        // the panel (header icon-btns, action-card).
        btn.innerHTML =
          '<svg viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round">' +
          '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
      }
      container.appendChild(btn);
    });
  }

  // Rename/remove rows for captured presets, in Settings below the Capture row. Rebuilt only
  // when the id list itself changes (add/remove/reorder) — same diff discipline as
  // renderPresetButtons — so a rename input's live edit and focus survive the renders that
  // happen constantly while busy (setStatus re-renders on every progress tick).
  function renderPresetManageList(customPresets) {
    const container = $("fx-preset-manage-list");
    if (!container) return;
    const presets = customPresets || [];

    const existing = Array.prototype.slice.call(container.children || []);
    const same =
      existing.length === presets.length &&
      existing.every((row, i) => row.getAttribute("data-preset-id") === presets[i].id);
    if (same) {
      existing.forEach((row, i) => {
        const input = row.querySelector(".fx-preset-manage-name");
        if (input && document.activeElement !== input) setValue(input, presets[i].name);
      });
      return;
    }

    container.innerHTML = "";
    presets.forEach((p) => {
      const row = document.createElement("div");
      row.className = "fx-preset-manage-row";
      row.setAttribute("data-preset-id", p.id);

      const input = document.createElement("input");
      input.type = "text";
      input.className = "setting-input fx-preset-manage-name";
      input.value = p.name;
      input.setAttribute("data-act", "fx-preset-rename");
      input.setAttribute("data-preset-id", p.id);

      const del = document.createElement("div");
      del.className = "fx-preset-manage-remove";
      del.setAttribute("role", "button");
      del.setAttribute("data-act", "fx-preset-remove");
      del.setAttribute("data-preset-id", p.id);
      del.title = `Remove "${p.name}"`;
      del.textContent = "×";

      row.appendChild(input);
      row.appendChild(del);
      container.appendChild(row);
    });
  }

  function renderJobBanner(job) {
    const banner = $("job-banner");
    if (banner) banner.classList.toggle("show", !!job);
    setHidden($("resume"), !job);
    setHidden($("dismiss"), !job);
  }

  // Where presets are saved (Settings > Presets): the linked folder, or this machine only.
  function renderPresetFile(presetFile) {
    const info = presetFile || {};
    const el = $("fx-preset-folder-path");
    setText(el, info.path
      ? (info.error ? `Unreachable: ${info.path}` : info.path)
      : "This machine only — choose a synced folder to back up and share presets.");
    if (el) el.classList.toggle("error", !!info.error);
    setText($("btn-preset-folder"), info.path ? "Change…" : "Choose folder…");
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
    renderPresetButtons(state.customPresets);
    renderPresetManageList(state.customPresets);
    renderPresetFile(state.presetFile);
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
    ["socketprobe", "copystatus", "timingprobe", "motionprobe", "effectprobe", "transformprobe", "keyframeprobe", "alcreateprobe", "syncmovesprobe"].forEach((id) => {
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
  }

  // Event delegation on the quick-effect button row: reads which preset and which modifier
  // keys, same gesture set as bindAdjustmentButtons' btn-adj below (Click: span | Ctrl: per
  // clip | Shift: every cut) — each click both places the AL that way AND applies that
  // preset's real effect to it (see main.js's doApplyPreset).
  function bindPresetButtons(intents) {
    const container = $("fx-preset-buttons");
    if (!container) return;
    container.addEventListener("click", (e) => {
      const btn = e.target.closest ? e.target.closest(".fx-preset-btn") : null;
      if (!btn) return;
      const presetId = btn.getAttribute("data-preset-id");
      if (!presetId) {
        // Empty slot — jump straight to where a preset actually gets captured, same
        // presentational exception as the overflow menu / settings modal noted up top.
        const settingsModal = $("settings-modal");
        if (settingsModal) settingsModal.classList.add("open");
        const nameInput = $("fx-capture-name");
        if (nameInput) nameInput.focus();
        return;
      }
      let mode = "span";
      if (e.shiftKey) mode = "transition";
      else if (e.ctrlKey || e.metaKey) mode = "per_clip";
      intents.onApplyPreset(presetId, mode);
    });
  }

  // The rename/remove list in Settings: delegated the same way as bindPresetButtons above.
  // Rename fires on "change" (blur / Enter), not every keystroke, so it composes cleanly with
  // renderPresetManageList's own-input-has-focus guard.
  function bindPresetManage(intents) {
    const container = $("fx-preset-manage-list");
    if (!container) return;
    container.addEventListener("click", (e) => {
      const del = e.target.closest ? e.target.closest("[data-act='fx-preset-remove']") : null;
      if (!del) return;
      const presetId = del.getAttribute("data-preset-id");
      if (presetId) intents.onRemovePreset(presetId);
    });
    container.addEventListener("change", (e) => {
      const input = e.target.closest ? e.target.closest("[data-act='fx-preset-rename']") : null;
      if (!input) return;
      const presetId = input.getAttribute("data-preset-id");
      const name = input.value.trim();
      if (presetId && name) intents.onRenamePreset(presetId, name);
    });
  }

  function bindCapturePreset(intents) {
    const btn = $("btn-capture-preset");
    const nameInput = $("fx-capture-name");
    if (btn) {
      btn.addEventListener("click", () => {
        const name = nameInput ? nameInput.value.trim() : "";
        intents.onProbe("capture-preset", { name });
      });
    }
  }

  function bindPresetFolder(intents) {
    const btn = $("btn-preset-folder");
    if (btn) btn.addEventListener("click", () => intents.onChoosePresetFolder());
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
  }

  function bindProbes(intents) {
    const timing = $("timingprobe");
    if (timing) timing.addEventListener("click", () => intents.onProbe("timing"));
    const socket = $("socketprobe");
    if (socket) socket.addEventListener("click", () => intents.onProbe("socket"));
    const copy = $("copystatus");
    if (copy) copy.addEventListener("click", () => intents.onProbe("copystatus"));
    const motion = $("motionprobe");
    if (motion) motion.addEventListener("click", () => intents.onProbe("motion"));
    const effectChain = $("effectprobe");
    if (effectChain) effectChain.addEventListener("click", () => intents.onProbe("effect"));
    const transform = $("transformprobe");
    if (transform) transform.addEventListener("click", () => intents.onProbe("transform"));
    const keyframe = $("keyframeprobe");
    if (keyframe) keyframe.addEventListener("click", () => intents.onProbe("keyframe"));
    const alCreate = $("alcreateprobe");
    if (alCreate) alCreate.addEventListener("click", () => intents.onProbe("alcreate"));
    const syncMoves = $("syncmovesprobe");
    if (syncMoves) syncMoves.addEventListener("click", () => intents.onProbe("syncmoves"));
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
    bindPresetButtons(intents);
    bindPresetManage(intents);
    bindCapturePreset(intents);
    bindPresetFolder(intents);
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
