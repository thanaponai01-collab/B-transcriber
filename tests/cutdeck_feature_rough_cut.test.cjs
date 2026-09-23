const test = require("node:test");
const assert = require("node:assert/strict");
const { createRoughCutFeature, KEY } = require("../uxp/cutdeck/features/roughCut.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

function createMockStorage(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
}

test("roughCut.follow: running -> ready invokes importResult and clears job", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({
    [KEY]: JSON.stringify({ job_id: "job-1", state: "running" }),
  });

  let importCalled = false;
  const fakePpro = {};
  const fakeWorkflow = require("../uxp/cutdeck/workflow.js");
  const origImportResult = fakeWorkflow.importResult;
  fakeWorkflow.importResult = async (ppro, job, attempted, onAttempt) => {
    importCalled = true;
    onAttempt();
  };

  try {
    let pollCount = 0;
    const fakeRpc = async (req) => {
      if (req.type === "status") {
        pollCount++;
        if (pollCount === 1) return { job_id: "job-1", state: "running", progress: 0.5 };
        return {
          job_id: "job-1",
          state: "ready",
          report: { cuts_applied: 5, removed_ms: 3200 },
          result_name: "CutDeck_RoughCut",
          output_path: "/tmp/cuts.xml",
        };
      }
      throw new Error(`Unexpected rpc: ${req.type}`);
    };

    const roughCut = createRoughCutFeature({
      ppro: fakePpro,
      ctl,
      rpc: fakeRpc,
      storage,
      pollDelay: 0,
    });

    await roughCut.follow({ job_id: "job-1", state: "running" });

    assert.equal(importCalled, true);
    assert.equal(storage.getItem(KEY), null, "Job should be cleared from storage on success");
    assert.equal(ctl.state.job, null);
    assert.equal(ctl.state.status.level, "ready");
    assert.match(ctl.state.status.text, /5 cuts · 3\.2 seconds removed/);
  } finally {
    fakeWorkflow.importResult = origImportResult;
  }
});

test("roughCut.follow: no_cuts clears job without importing", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({
    [KEY]: JSON.stringify({ job_id: "job-2", state: "running" }),
  });

  const roughCut = createRoughCutFeature({
    ppro: {},
    ctl,
    rpc: async () => {},
    storage,
  });

  await roughCut.follow({ job_id: "job-2", state: "no_cuts" });

  assert.equal(storage.getItem(KEY), null);
  assert.equal(ctl.state.job, null);
  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /No cuts found/);
});

test("roughCut.follow: failed clears job and throws", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({
    [KEY]: JSON.stringify({ job_id: "job-3", state: "running" }),
  });

  const roughCut = createRoughCutFeature({
    ppro: {},
    ctl,
    rpc: async () => {},
    storage,
  });

  await assert.rejects(
    () => roughCut.follow({ job_id: "job-3", state: "failed", message: "Transcription timeout" }),
    /Transcription timeout/
  );

  assert.equal(storage.getItem(KEY), null);
  assert.equal(ctl.state.status.level, "error");
});

test("roughCut.onCut: blocks when unresumed job is in storage", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({
    [KEY]: JSON.stringify({ job_id: "job-4", state: "prepared" }),
  });

  const roughCut = createRoughCutFeature({
    ppro: {},
    ctl,
    rpc: async () => {},
    storage,
  });

  await roughCut.onCut();
  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /Resume the previous job/);
});
