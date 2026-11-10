const test = require("node:test");
const assert = require("node:assert/strict");
const { createTranscriptFeature } = require("../uxp/cutdeck/features/transcript.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

// A fake with only what the feature calls; shapes follow reference/adobe/api/premierepro.txt.
function fakePpro({ selected, hasTranscript }) {
  const calls = { imported: null, actionFor: null, labels: [] };
  const project = {
    lockedAccess: (fn) => fn(),
    executeTransaction(build, label) {
      calls.labels.push(label);
      build({ addAction: (action) => { calls.added = action; return true; } });
      return true;
    },
  };
  const ppro = {
    Project: { getActiveProject: async () => project },
    ProjectUtils: { getSelection: async () => ({ getItems: async () => selected }) },
    ClipProjectItem: { cast: (item) => (item.clip ? item : null) },
    Transcript: {
      importFromJSON: (json) => { calls.imported = json; return { segments: "ts" }; },
      createImportTextSegmentsAction: (segments, clip) => { calls.actionFor = clip; return { action: segments }; },
    },
  };
  if (hasTranscript !== undefined) ppro.Transcript.hasTranscript = () => hasTranscript;
  return { ppro, calls };
}

const clip = (name, isSeq = false) => ({
  clip: true, name, isSequence: async () => isSeq, getMediaFilePath: async () => `C:/media/${name}.mp4`,
});

function helperRpc(requests) {
  const rpc = async (req) => {
    requests.push(req);
    if (req.type === "submit_transcribe") return { job_id: "j1", state: "running" };
    if (req.type === "premiere_transcript") return { transcript: '{"language":"th-th"}', segments: 3, words: 12 };
    throw new Error(`unexpected ${req.type}`);
  };
  rpc.watch = async (jobId) => ({ job_id: jobId, state: "ready" });
  return rpc;
}

test("imports the helper's JSON onto the one selected clip in a transaction", async () => {
  const { ppro, calls } = fakePpro({ selected: [{ name: "bin" }, clip("seq", true), clip("interview")] });
  const requests = [];
  const ctl = createController({ render: () => {} });
  const feature = createTranscriptFeature({ ppro, ctl, rpc: helperRpc(requests), ensureHelper: async () => {} });
  await feature.onImportTranscript();

  assert.deepEqual(requests.map((r) => r.type), ["submit_transcribe", "premiere_transcript"]);
  assert.equal(requests[0].media_path, "C:/media/interview.mp4");
  assert.equal(calls.imported, '{"language":"th-th"}');
  assert.equal(calls.actionFor.name, "interview");
  assert.deepEqual(calls.added, { action: { segments: "ts" } });
  assert.deepEqual(calls.labels, ["Import Thai Transcript"]);
  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /interview: 3 segments, 12 words/);
});

test("refuses unless exactly one non-sequence clip is selected", async () => {
  const { ppro, calls } = fakePpro({ selected: [clip("a"), clip("b")] });
  const ctl = createController({ render: () => {} });
  await createTranscriptFeature({ ppro, ctl, rpc: helperRpc([]), ensureHelper: async () => {} }).onImportTranscript();
  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /Select one clip/);
  assert.equal(calls.imported, null);
});

test("a failed transcription imports nothing", async () => {
  const { ppro, calls } = fakePpro({ selected: [clip("a")] });
  const rpc = helperRpc([]);
  rpc.watch = async () => ({ state: "failed", message: "Transcription failed (exit 1)" });
  const ctl = createController({ render: () => {} });
  await createTranscriptFeature({ ppro, ctl, rpc, ensureHelper: async () => {} }).onImportTranscript();
  assert.match(ctl.state.status.text, /exit 1/);
  assert.equal(calls.imported, null);
});

test("hasTranscript is used only where Premiere has it (absent at 26.2)", async () => {
  for (const [has, re] of [[true, /replaced its earlier transcript/], [undefined, /^Thai transcript on a: /]]) {
    const { ppro } = fakePpro({ selected: [clip("a")], hasTranscript: has });
    const ctl = createController({ render: () => {} });
    await createTranscriptFeature({ ppro, ctl, rpc: helperRpc([]), ensureHelper: async () => {} }).onImportTranscript();
    assert.equal(ctl.state.status.level, "ready");
    assert.match(ctl.state.status.text, re);
  }
});
