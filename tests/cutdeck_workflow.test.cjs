const test = require("node:test");
const assert = require("node:assert/strict");
const { capture, prepare, importResult } = require("../uxp/cutdeck/workflow.js");

function fixture() {
  const source = { guid: { toString: () => "source" }, name: "Interview",
    getInPoint: async () => ({seconds: 2, ticks: "200"}),
    getOutPoint: async () => ({seconds: 4, ticks: "400"}),
    getEndTime: async () => ({seconds: 10, ticks: "1000"}),
    getTimebase: async () => "10", getAudioTrackCount: async () => 2 };
  const result = { guid: { toString: () => "result" }, name: "Interview — CutDeck 123" };
  let sequences = [source], imports = 0;
  const project = { guid: {toString: () => "project"},
    getActiveSequence: async () => source, getSequences: async () => sequences,
    getRootItem: async () => ({}),
    importFiles: async () => { imports++; sequences.push(result); return true; },
    openSequence: async () => true, setActiveSequence: async () => true };
  const ppro = { Project: { getActiveProject: async () => project },
    ProjectConverter: { exportAsFinalCutProXML: async () => true } };
  const job = { context: {project_id: "project", sequence_id: "source"},
    result_name: result.name, output_path: "result.xml", source_path: "source.xml", job_id: "123" };
  return { source, project, ppro, job, imports: () => imports };
}
test("captures exact tick strings and rejects missing marks", async () => {
  const f = fixture();
  assert.equal((await capture(f.ppro)).context.in_ticks, "200");
  f.source.getOutPoint = async () => ({seconds: -1});
  await assert.rejects(capture(f.ppro), /valid timeline/);
});
test("failed export never starts processing", async () => {
  const f = fixture(); const calls = [];
  f.ppro.ProjectConverter.exportAsFinalCutProXML = async () => false;
  await assert.rejects(prepare(f.ppro, async (r) => { calls.push(r.type); return f.job; },
    await capture(f.ppro), {}, () => {}), /could not export/);
  assert.deepEqual(calls, ["hello", "prepare"]);
});
test("switching projects prevents import", async () => {
  const f = fixture(); f.project.guid.toString = () => "other";
  await assert.rejects(importResult(f.ppro, f.job, false, () => {}), /original project/);
  assert.equal(f.imports(), 0);
});
test("resume opens an already imported result without duplicating it", async () => {
  const f = fixture(); let marked = false;
  await importResult(f.ppro, f.job, false, () => { marked = true; });
  assert.ok(marked);
  await importResult(f.ppro, f.job, true, () => {});
  assert.equal(f.imports(), 1);
});
test("unconfirmed earlier import cannot silently import twice", async () => {
  const f = fixture();
  await assert.rejects(importResult(f.ppro, f.job, true, () => {}), /previous import/);
  assert.equal(f.imports(), 0);
});
