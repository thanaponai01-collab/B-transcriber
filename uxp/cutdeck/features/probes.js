// Owns diagnostic probe dispatch for the main panel diagnostics drawer.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const capability = require("../capabilityProbe.js");
const syncProbe = require("../syncProbe.js");
const probe = require("../probe.js");

const PROBES = [
  {
    id: "socket",
    startText: "Probing which socket URLs this Premiere build permits…",
    run: async () => probe.run(),
    format: ({ report, written }) => [
      "Socket permission probe:",
      ...report.results.map((r) => `${r.url} -> ${r.outcome}`),
      "",
      `written: ${written}`,
    ].join("\n"),
    logLabel: "CutDeck socket probe",
  },
  {
    id: "copystatus",
    special: true,
  },
  {
    id: "timing",
    startText: "Reading this build's marks and timebase…",
    run: (ppro) => capability.probeMarksAndTiming(ppro),
    format: (report) => capability.formatReport(report),
    logLabel: "CutDeck capability probe",
  },
  {
    id: "motion",
    startText: "Reading the Adjustment Layer's live Motion component on this sequence…",
    run: (ppro) => capability.probeAdjustmentLayerMotion(ppro),
    format: (report) => capability.formatMotionReport(report),
    logLabel: "CutDeck AL motion probe",
  },
  {
    id: "effect",
    startText: "Reading the selected item's real effect chain…",
    run: (ppro) => capability.probeEffectChain(ppro),
    format: (report) => capability.formatEffectChainReport(report),
    logLabel: "CutDeck effect chain probe",
  },
  {
    id: "transform",
    startText: "Reading the selected clip's real Motion/Transform params, units and source dimensions…",
    run: (ppro) => capability.probeTransformParams(ppro),
    format: (report) => capability.formatTransformReport(report),
    logLabel: "CutDeck transform params probe",
  },
  {
    id: "keyframe",
    startText: "Reading the selected clip's keyframes against the playhead…",
    run: (ppro) => capability.probeKeyframeTiming(ppro),
    format: (report) => capability.formatKeyframeReport(report),
    logLabel: "CutDeck keyframe timing probe",
  },
  {
    id: "alcreate",
    startText: "Generating an Adjustment Layer at this sequence's size and importing it…",
    run: (ppro) => capability.probeCreateAdjustmentLayer(ppro),
    format: (report) => capability.formatCreateAdjustmentLayerReport(report),
    logLabel: "CutDeck AL creation probe",
  },
  {
    id: "syncmoves",
    startText: "Copying this sequence, then testing clip moves on the copy…",
    run: (ppro) => syncProbe.probeSyncMoves(ppro),
    format: (report) => syncProbe.formatSyncMovesReport(report),
    logReplacer: (k, v) => (typeof v === "bigint" ? v.toString() : v),
    logLabel: "CutDeck sync moves probe",
  },
];

async function runProbe(probeEntry, ppro, ctl) {
  ctl.setStatus(probeEntry.startText, "busy");
  const report = await probeEntry.run(ppro);
  if (probeEntry.logReplacer) {
    console.log(probeEntry.logLabel || `CutDeck ${probeEntry.id} probe`, JSON.stringify(report, probeEntry.logReplacer, 2));
  } else {
    console.log(probeEntry.logLabel || `CutDeck ${probeEntry.id} probe`, JSON.stringify(report, null, 2));
  }
  ctl.setStatus(probeEntry.format(report), "ready");
  return report;
}

function createProbesFeature({
  ppro,
  ctl,
  clipboard = typeof navigator !== "undefined" && navigator.clipboard ? navigator.clipboard : null,
  uxp = null,
  onCapturePreset = null,
}) {
  async function handleProbe(name, payload) {
    if (name === "copystatus") {
      const text = (ctl.state.lastStatus && ctl.state.lastStatus.text) || ctl.state.status.text;
      if (clipboard && clipboard.writeText) {
        await clipboard.writeText(text);
      } else if (uxp && uxp.clipboard) {
        uxp.clipboard.copyText(text);
      } else {
        throw new Error("No clipboard API on this build. The full report is in the UXP Developer Tool console as JSON.");
      }
      ctl.setStatus(text + "\n\n--- copied to clipboard ---", "ready");
      return;
    }
    if (name === "capture-preset") {
      if (onCapturePreset) {
        return onCapturePreset(payload);
      }
      throw new Error("Preset capture is handled by the presets feature.");
    }

    const entry = PROBES.find((p) => p.id === name);
    if (!entry) {
      throw new Error(`Unknown probe: ${name}`);
    }
    return runProbe(entry, ppro, ctl);
  }

  return {
    onProbe: (name, payload) => ctl.act(() => handleProbe(name, payload)),
    handleProbe,
  };
}

module.exports = {
  createProbesFeature,
  PROBES,
  runProbe,
};
