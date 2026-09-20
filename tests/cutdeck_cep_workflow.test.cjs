const test = require("node:test");
const assert = require("node:assert/strict");
const { VERSION, createWorkflow } = require("../cep/cutdeck/client/workflow.js");

function createMockHost() {
  let projectOpen = true;
  let hasSequence = true;
  let inSec = 2.0;
  let outSec = 4.0;
  let exportSuccess = true;
  let importSuccess = true;
  let imports = 0;
  let activeSeqName = "Interview";

  async function mockEvalScript(script) {
    if (script.startsWith("getActiveSequenceInfo(")) {
      if (!projectOpen) return JSON.stringify({ error: "Open a Premiere project first." });
      if (!hasSequence) return JSON.stringify({ error: "Open a sequence and set timeline In/Out marks." });
      if (inSec < 0 || outSec <= inSec) return JSON.stringify({ error: "Set valid timeline In/Out marks inside the sequence." });

      const timebase = "8475200800"; // e.g. ticks per frame
      const inTicks = (BigInt(Math.round(inSec * 30)) * BigInt(timebase)).toString();
      const outTicks = (BigInt(Math.round(outSec * 30)) * BigInt(timebase)).toString();
      const endTicks = (BigInt(300) * BigInt(timebase)).toString();

      return JSON.stringify({
        project_id: "mock_proj_guid",
        sequence_id: "mock_seq_guid",
        sequence_name: activeSeqName,
        in_seconds: inSec,
        out_seconds: outSec,
        end_seconds: 10.0,
        in_ticks_raw: inTicks,
        out_ticks_raw: outTicks,
        end_ticks_raw: endTicks,
        ticks_per_frame: timebase,
        audio_track_count: 2,
      });
    }

    if (script.startsWith("exportSequenceXML(")) {
      if (!exportSuccess) return JSON.stringify({ error: "Export failed in Premiere" });
      return JSON.stringify({ success: true });
    }

    if (script.startsWith("importResultXML(")) {
      if (!importSuccess) return JSON.stringify({ error: "Import rejected by Premiere" });
      imports++;
      return JSON.stringify({ success: true, sequenceID: "mock_result_guid", name: "Interview — CutDeck 123" });
    }

    if (script.startsWith("setActiveSequenceByName(")) {
      return JSON.stringify({ success: true, sequenceID: "mock_result_guid", name: "Interview — CutDeck 123" });
    }

    throw new Error("Unhandled mock evalScript: " + script);
  }

  return {
    evalScript: mockEvalScript,
    setProjectOpen: (val) => { projectOpen = val; },
    setHasSequence: (val) => { hasSequence = val; },
    setMarks: (i, o) => { inSec = i; outSec = o; },
    setExportSuccess: (val) => { exportSuccess = val; },
    setImportSuccess: (val) => { importSuccess = val; },
    getImports: () => imports,
  };
}

test("captures exact aligned ticks and rejects missing marks", async () => {
  const host = createMockHost();
  const wf = createWorkflow(host.evalScript);
  const snap = await wf.capture();

  assert.equal(snap.context.sequence_name, "Interview");
  assert.equal(snap.context.ticks_per_frame, "8475200800");
  assert.ok(snap.context.in_ticks.length > 5);

  host.setMarks(5, 2); // Invalid: out <= in
  await assert.rejects(wf.capture(), /valid timeline/);
});

test("failed export halts and does not start helper processing", async () => {
  const host = createMockHost();
  host.setExportSuccess(false);
  const wf = createWorkflow(host.evalScript);

  const calls = [];
  const mockRpc = async (req) => {
    calls.push(req.type);
    if (req.type === "prepare") return { job_id: "test_job_1", source_path: "C:\\tmp\\test.xml" };
    return { ok: true };
  };

  const snap = await wf.capture();
  await assert.rejects(
    wf.prepare(mockRpc, snap, {}, () => {}),
    /could not export/
  );

  assert.deepEqual(calls, ["hello", "prepare"]);
});

test("successful prepare triggers hello, prepare, and start in order", async () => {
  const host = createMockHost();
  const wf = createWorkflow(host.evalScript);

  const calls = [];
  const mockRpc = async (req) => {
    calls.push(req.type);
    if (req.type === "prepare") return { job_id: "job_xyz", source_path: "C:\\tmp\\src.xml" };
    if (req.type === "start") return { job_id: "job_xyz", state: "running" };
    return { ok: true };
  };

  const snap = await wf.capture();
  const saved = [];
  const result = await wf.prepare(mockRpc, snap, {}, (j) => saved.push({ ...j }));

  assert.deepEqual(calls, ["hello", "prepare", "start"]);
  assert.equal(result.state, "running");
  assert.equal(saved.length, 3);
  assert.equal(saved[0].exported, undefined);
  assert.equal(saved[1].exported, true);
  assert.equal(saved[2].state, "running");
});

test("importResult imports and activates sequence", async () => {
  const host = createMockHost();
  const wf = createWorkflow(host.evalScript);

  let marked = false;
  const job = { output_path: "C:\\tmp\\rough_cut.xml", result_name: "Interview — CutDeck 123" };
  const res = await wf.importResult(job, false, () => { marked = true; });

  assert.ok(marked);
  assert.equal(res.success, true);
  assert.equal(host.getImports(), 1);
});

test("resume opens existing sequence without re-importing", async () => {
  const host = createMockHost();
  const wf = createWorkflow(host.evalScript);

  const job = { output_path: "C:\\tmp\\rough_cut.xml", result_name: "Interview — CutDeck 123" };
  const res = await wf.importResult(job, true, () => {});

  assert.equal(res.success, true);
  assert.equal(host.getImports(), 0); // No import was called, only setActiveSequenceByName
});

test("helper_manager skips spawning if helper already running", async () => {
  const { ensureHelperRunning, findPython, getRepoRoot } = require("../cep/cutdeck/client/helper_manager.js");
  const mockRpc = async () => ({ version: "cutdeck-xml-1" });

  const result = await ensureHelperRunning({
    rpc: mockRpc,
    version: "cutdeck-xml-1",
  });

  assert.equal(result.alreadyRunning, true);
  assert.equal(result.started, false);
  assert.equal(findPython("."), "python");
});

