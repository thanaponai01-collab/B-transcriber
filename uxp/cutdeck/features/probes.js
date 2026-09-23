// Owns diagnostic probe dispatch for the main panel diagnostics drawer.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const capability = require("../capabilityProbe.js");
const syncProbe = require("../syncProbe.js");
const probe = require("../probe.js");

function createProbesFeature({
  ppro,
  ctl,
  clipboard = typeof navigator !== "undefined" && navigator.clipboard ? navigator.clipboard : null,
  uxp = null,
  onCapturePreset = null,
}) {
  async function handleProbe(name, payload) {
    if (name === "timing") {
      ctl.setStatus("Reading this build's marks and timebase…", "busy");
      const report = await capability.probeMarksAndTiming(ppro);
      console.log("CutDeck capability probe", JSON.stringify(report, null, 2));
      ctl.setStatus(capability.formatReport(report), "ready");
      return;
    }
    if (name === "motion") {
      ctl.setStatus("Reading the Adjustment Layer's live Motion component on this sequence…", "busy");
      const report = await capability.probeAdjustmentLayerMotion(ppro);
      console.log("CutDeck AL motion probe", JSON.stringify(report, null, 2));
      ctl.setStatus(capability.formatMotionReport(report), "ready");
      return;
    }
    if (name === "effect") {
      ctl.setStatus("Reading the selected item's real effect chain…", "busy");
      const report = await capability.probeEffectChain(ppro);
      console.log("CutDeck effect chain probe", JSON.stringify(report, null, 2));
      ctl.setStatus(capability.formatEffectChainReport(report), "ready");
      return;
    }
    if (name === "keyframe") {
      ctl.setStatus("Reading the selected clip's keyframes against the playhead…", "busy");
      const report = await capability.probeKeyframeTiming(ppro);
      console.log("CutDeck keyframe timing probe", JSON.stringify(report, null, 2));
      ctl.setStatus(capability.formatKeyframeReport(report), "ready");
      return;
    }
    if (name === "alcreate") {
      ctl.setStatus("Generating an Adjustment Layer at this sequence's size and importing it…", "busy");
      const report = await capability.probeCreateAdjustmentLayer(ppro);
      console.log("CutDeck AL creation probe", JSON.stringify(report, null, 2));
      ctl.setStatus(capability.formatCreateAdjustmentLayerReport(report), "ready");
      return;
    }
    if (name === "syncmoves") {
      ctl.setStatus("Copying this sequence, then testing clip moves on the copy…", "busy");
      const report = await syncProbe.probeSyncMoves(ppro);
      console.log("CutDeck sync moves probe", JSON.stringify(report, (k, v) => (typeof v === "bigint" ? v.toString() : v), 2));
      ctl.setStatus(syncProbe.formatSyncMovesReport(report), "ready");
      return;
    }
    if (name === "transform") {
      ctl.setStatus("Reading the selected clip's real Motion/Transform params, units and source dimensions…", "busy");
      const report = await capability.probeTransformParams(ppro);
      console.log("CutDeck transform params probe", JSON.stringify(report, null, 2));
      ctl.setStatus(capability.formatTransformReport(report), "ready");
      return;
    }
    if (name === "socket") {
      ctl.setStatus("Probing which socket URLs this Premiere build permits…", "busy");
      const { report, written } = await probe.run();
      ctl.setStatus([`Socket permission probe:`, ...report.results.map((r) => `${r.url} -> ${r.outcome}`),
        ``, `written: ${written}`].join(`\n`), "ready");
      return;
    }
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
  }

  return {
    onProbe: (name, payload) => ctl.act(() => handleProbe(name, payload)),
    handleProbe,
  };
}

module.exports = {
  createProbesFeature,
};
