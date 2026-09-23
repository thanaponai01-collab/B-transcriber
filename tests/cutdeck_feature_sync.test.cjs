const test = require("node:test");
const assert = require("node:assert/strict");
const { createSyncFeature } = require("../uxp/cutdeck/features/sync.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");
const nativeSync = require("../uxp/cutdeck/timeline/nativeSync.js");

test("sync.onSync: blocks when unresumed job exists", async () => {
  const ctl = createController({ render: () => {} });
  const sync = createSyncFeature({
    ppro: {},
    ctl,
    rpc: async () => {},
    ensureHelper: async () => {},
    lastJob: () => ({ job_id: "prev-job" }),
  });

  await sync.onSync();
  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /Resume or dismiss the previous job/);
});

test("sync.onSync: executes syncSequence and reports ready on success", async () => {
  const ctl = createController({ render: () => {} });
  const origSync = nativeSync.syncSequence;
  let syncCalled = false;

  nativeSync.syncSequence = async (ppro, opts) => {
    syncCalled = true;
    opts.onStatus("Aligning audio…");
    return {
      text: "Synced 4 clips on V2_Synced",
      problems: [],
    };
  };

  try {
    const sync = createSyncFeature({
      ppro: {},
      ctl,
      rpc: async () => {},
      ensureHelper: async () => {},
      lastJob: () => null,
    });

    await sync.onSync();
    assert.equal(syncCalled, true);
    assert.equal(ctl.state.status.level, "ready");
    assert.equal(ctl.state.status.text, "Synced 4 clips on V2_Synced");
  } finally {
    nativeSync.syncSequence = origSync;
  }
});

test("sync.onSync: reports error when problems are returned", async () => {
  const ctl = createController({ render: () => {} });
  const origSync = nativeSync.syncSequence;

  nativeSync.syncSequence = async () => ({
    text: "1 clip could not be matched by audio",
    problems: ["Clip B no match"],
  });

  try {
    const sync = createSyncFeature({
      ppro: {},
      ctl,
      rpc: async () => {},
      ensureHelper: async () => {},
      lastJob: () => null,
    });

    await sync.onSync();
    assert.equal(ctl.state.status.level, "error");
    assert.equal(ctl.state.status.text, "1 clip could not be matched by audio");
  } finally {
    nativeSync.syncSequence = origSync;
  }
});
