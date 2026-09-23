// Owns native multi-cam Sync orchestration and reporting.
// Must not know: the DOM, UI panels, Rough Cut job storage.

const nativeSync = require("../timeline/nativeSync.js");

function createSyncFeature({
  ppro,
  ctl,
  rpc,
  ensureHelper,
  lastJob,
}) {
  async function doSync() {
    if (lastJob && lastJob()) {
      throw new Error("Resume or dismiss the previous job before starting another operation.");
    }
    const result = await nativeSync.syncSequence(ppro, {
      rpc,
      ensureHelper,
      onStatus: (text) => ctl.setStatus(text, "busy"),
    });
    ctl.setStatus(result.text, result.problems && result.problems.length ? "error" : "ready");
  }

  return {
    onSync: () => ctl.act(doSync),
    doSync,
  };
}

module.exports = {
  createSyncFeature,
};
