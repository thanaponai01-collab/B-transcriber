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

test("roughCut.follow: a ready job from the retired XML route is cleared with a clear message", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({ [KEY]: JSON.stringify({ job_id: "job-1", state: "running" }) });
  const roughCut = createRoughCutFeature({ ppro: {}, ctl, rpc: async () => {}, storage });
  await assert.rejects(roughCut.follow({ job_id: "job-1", state: "ready", output_path: "/tmp/cuts.xml" }),
    /old XML Rough Cut, which is retired/);
  assert.equal(storage.getItem(KEY), null);
});

test("roughCut.follow: a native job for a sequence that isn't open cuts nothing and stays resumable", async () => {
  const ctl = createController({ render: () => {} });
  const job = { job_id: "job-9", state: "ready", output: "native", cuts: { cuts_frames: [[1, 2]], ticks_per_frame: "1" },
    context: { sequence_id: "seq-1", sequence_name: "Shoot" } };
  const storage = createMockStorage({ [KEY]: JSON.stringify(job) });
  const other = { guid: { toString: () => "other" } };
  const ppro = { Project: { getActiveProject: async () => ({ getActiveSequence: async () => other }) } };
  const roughCut = createRoughCutFeature({ ppro, ctl, rpc: async () => {}, storage });
  await assert.rejects(roughCut.follow({ ...job }), /Open "Shoot" to cut it/);
  assert.notEqual(storage.getItem(KEY), null);
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

test("roughCut.onCut: a pending job is resumed, not replaced by a new one", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({
    [KEY]: JSON.stringify({ job_id: "job-4", state: "running" }),
  });
  const calls = [];
  const roughCut = createRoughCutFeature({
    ppro: {},
    ctl,
    rpc: async (req) => { calls.push(req.type); return req.type === "status" ? { job_id: "job-4", state: "no_cuts" } : {}; },
    storage,
  });

  await roughCut.onCut();
  assert.deepEqual(calls, ["hello", "status"], "must resume job-4, never prepare a new job");
  assert.equal(storage.getItem(KEY), null);
  assert.match(ctl.state.status.text, /No cuts found/);
});

test("a running job is followed by pushed events, not status polling", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({ [KEY]: JSON.stringify({ job_id: "job-5", state: "running" }) });
  const calls = [];
  const rpc = async (req) => { calls.push(req.type); return req.type === "status" ? { job_id: "job-5", state: "running", progress: { pct: 5, stage: "Detecting speech" } } : {}; };
  const seen = [];
  rpc.watch = async (jobId, onUpdate) => {
    calls.push("watch");
    onUpdate({ job_id: jobId, state: "running", progress: { pct: 50, stage: "Transcribing speech" } });
    seen.push(ctl.state.status.text);
    return { job_id: jobId, state: "no_cuts" };
  };
  const roughCut = createRoughCutFeature({ ppro: {}, ctl, rpc, storage, progressText: (job) => job.progress.stage });
  await roughCut.onResumeJob();
  assert.deepEqual(calls, ["hello", "status", "watch"]);
  assert.deepEqual(seen, ["Transcribing speech"]);
  assert.match(ctl.state.status.text, /No cuts found/);
});

test("a job the helper lost in a restart is cleared with its message", async () => {
  const ctl = createController({ render: () => {} });
  const storage = createMockStorage({ [KEY]: JSON.stringify({ job_id: "job-6", state: "running" }) });
  const rpc = async (req) => (req.type === "status"
    ? { job_id: "job-6", state: "interrupted", message: "The CutDeck helper restarted while this job ran; start it again" } : {});
  const roughCut = createRoughCutFeature({ ppro: {}, ctl, rpc, storage });
  await roughCut.onResumeJob();
  assert.equal(storage.getItem(KEY), null);
  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /restarted while this job ran/);
});
