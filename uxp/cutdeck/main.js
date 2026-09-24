// Composition root: creates controllers, instantiates features, binds UI seams,
// registers UXP entrypoints, and coordinates panel startup.
// Must not know: Premiere mutation details, status wording, or feature logic.

const ppro = require("premierepro");
const uxp = require("uxp");
const workflow = require("./workflow.js");
const helperStart = require("./helperStart.js");
const { createRpc } = require("./core/rpc.js");
const { progressText } = require("./core/progressText.js");
const panel = require("./core/panel.js");
const alignPanel = require("./core/alignPanel.js");
const { createPresetStore } = require("./presetStore.js");
const { createController } = require("./features/controller.js");
const { createRoughCutFeature, lastJob } = require("./features/roughCut.js");
const { createSyncFeature } = require("./features/sync.js");
const { createAdjustFeature, loadSettings } = require("./features/adjust.js");
const { createPresetsFeature, loadCustomPresets } = require("./features/presets.js");
const { createAlignFeature } = require("./features/align.js");
const { createProbesFeature } = require("./features/probes.js");

const storage = typeof localStorage !== "undefined" ? localStorage : null;

// The controllers: hold state, serialize actions (act), and notify panel renders.
const mainCtl = createController({
  render: panel.render,
  initialState: {
    sequence: null, tab: "adj", cutMode: "protected", audioTrack: null,
    settings: loadSettings(storage), customPresets: loadCustomPresets(storage),
    presetFile: { path: null, error: null }, job: null,
  },
});

const alignCtl = createController({
  render: alignPanel.render,
  initialState: { sequence: null, transform: null },
});

const presetStore = createPresetStore({
  localFileSystem: uxp && uxp.storage ? uxp.storage.localFileSystem : null,
  storage,
});

// Helper RPC and lifecycle
const rpc = createRpc({
  onRetry: (attempt, total) => mainCtl.setStatus(`Connecting to helper… attempt ${attempt} of ${total}.`, "busy"),
});
const quietRpc = createRpc({});
let helperRestart = Promise.resolve();

function restartHelperOnStart() {
  if (lastJob(storage)) return;
  helperRestart = helperStart.restartHelper({ rpc: quietRpc, version: workflow.VERSION })
    .then((outcome) => console.log("CutDeck helper on panel start:", outcome))
    .catch((error) => mainCtl.setStatus(error.message, "error"));
}

async function ensureHelper() {
  await helperRestart;
  return helperStart.ensureHelperRunning({
    rpc,
    version: workflow.VERSION,
    onStatus: (msg) => mainCtl.setStatus(msg, "busy"),
  });
}

// Features
const roughCut = createRoughCutFeature({ ppro, ctl: mainCtl, rpc, ensureHelper, storage, progressText });
const sync = createSyncFeature({ ppro, ctl: mainCtl, rpc, ensureHelper, lastJob: roughCut.lastJob });
const adjust = createAdjustFeature({ ppro, ctl: mainCtl, storage });
const presets = createPresetsFeature({ ppro, ctl: mainCtl, presetStore, storage });
const probes = createProbesFeature({
  ppro,
  ctl: mainCtl,
  clipboard: typeof navigator !== "undefined" ? navigator.clipboard : null,
  uxp,
  onCapturePreset: presets.onCapturePreset,
});
const align = createAlignFeature({ ppro, ctl: alignCtl });

// Main panel binding
panel.bind({
  onRefresh: roughCut.onRefresh,
  onCut: roughCut.onCut,
  onSync: sync.onSync,
  onResumeJob: roughCut.onResumeJob,
  onDismissJob: roughCut.onDismissJob,
  onTab: (name) => { mainCtl.state.tab = name; mainCtl.render(); },
  onCutMode: roughCut.onCutMode,
  onAdjust: adjust.onAdjust,
  onApplyPreset: adjust.onApplyPreset,
  onRemovePreset: presets.onRemovePreset,
  onRenamePreset: presets.onRenamePreset,
  onChoosePresetFolder: presets.onChoosePresetFolder,
  onCapturePreset: presets.onCapturePreset,
  onSettingChange: adjust.onSettingChange,
  onProbe: probes.onProbe,
});

// Align panel binding
alignPanel.bind({
  onRefresh: align.onRefresh,
  onProbe: align.onProbe,
});

// Register panels with UXP entrypoints
try {
  const { entrypoints } = uxp;
  entrypoints.setup({
    panels: {
      "cutdeck.panel": { show() {} },
      "cutdeck.align.panel": {
        show(rootNode) {
          if (!alignPanel.mount(rootNode)) {
            console.error("CutDeck: could not mount #view-transform into the transform panel root.");
            return;
          }
          alignCtl.render();
          align.refresh().catch((error) => {
            alignCtl.setStatus(error.message || String(error), "error");
          });
          align.startPolling();
        },
      },
    },
  });
} catch (error) {
  console.error("CutDeck: entrypoints.setup() failed; the Transform panel will not open.", error);
}

// Startup
const savedJob = roughCut.lastJob();
mainCtl.state.job = savedJob ? { id: savedJob.job_id, state: savedJob.state } : null;
mainCtl.render();
restartHelperOnStart();

setTimeout(async () => {
  await presets.loadPresets();
  try {
    await roughCut.refresh();
  } catch (_) { /* no sequence open yet — the refresh icon retries */ }
  if (mainCtl.state.presetFile.error) mainCtl.setStatus(`Presets: ${mainCtl.state.presetFile.error}`, "error");
  else mainCtl.setStatus("Ready", "ready");
  // The sequence card follows a sequence switch: global SequenceEvent.ACTIVATED fires on switch
  // (PREMIERE_FACTS.md, live 2026-09-24). In/Out changes fire nothing, so the refresh icon stays.
  try {
    ppro.EventManager.addGlobalEventListener(ppro.Constants.SequenceEvent.ACTIVATED, () => {
      roughCut.refresh().catch(() => { /* no sequence — the refresh icon retries */ });
    });
  } catch (error) {
    console.error("CutDeck: sequence switch listener failed; use the refresh icon", error);
  }
}, 50);
