const test = require("node:test");
const assert = require("node:assert/strict");
const { capture, prepare } = require("../uxp/cutdeck/workflow.js");
const { getOrCreateBin } = require("../uxp/cutdeck/host/project.js");
const getOrCreateCutDeckBin = (project) => getOrCreateBin(project, ["CutDeck"]);

function fixture() {
  const source = { guid: { toString: () => "source" }, name: "Interview",
    getInPoint: async () => ({seconds: 2, ticks: "200"}),
    getOutPoint: async () => ({seconds: 4, ticks: "400"}),
    getEndTime: async () => ({seconds: 10, ticks: "1000"}),
    getTimebase: async () => "10", getAudioTrackCount: async () => 2 };
  const result = { guid: { toString: () => "result" }, name: "Interview — CutDeck 123" };
  let sequences = [source], imports = 0;
  let rootItems = [];
  let binsCreated = 0;
  const importTargets = [];
  const makeBin = (name, items) => ({ name,
    getItems: async () => items,
    createBinAction: (child, makeUnique) => ({ __createBin: true, name: child, makeUnique, into: items }),
  });
  const root = makeBin(undefined, rootItems);
  const project = { guid: {toString: () => "project"},
    getActiveSequence: async () => source, getSequences: async () => sequences,
    getRootItem: async () => root,
    executeTransaction: (callback) => {
      const compound = {
        addAction: (action) => {
          if (action && action.__createBin) {
            binsCreated++;
            action.into.push(makeBin(action.name, []));
            return true;
          }
          return false;
        },
      };
      callback(compound);
      return true;
    },
    importFiles: async (paths, suppressUI, targetBin) => {
      imports++; importTargets.push(targetBin); sequences.push(result); return true;
    },
    openSequence: async () => true, setActiveSequence: async () => true };
  const ppro = { Project: { getActiveProject: async () => project },
    ProjectConverter: { exportAsFinalCutProXML: async () => true } };
  const job = { context: {project_id: "project", sequence_id: "source"},
    result_name: result.name, output_path: "result.xml", source_path: "source.xml", job_id: "123" };
  return { source, project, ppro, job, imports: () => imports,
    binsCreated: () => binsCreated, importTargets, rootItems: () => rootItems };
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
test("a second call reuses the existing CutDeck bin instead of creating another", async () => {
  const f = fixture();
  const first = await getOrCreateCutDeckBin(f.project);
  const second = await getOrCreateCutDeckBin(f.project);
  assert.equal(f.binsCreated(), 1);
  assert.deepEqual(first, second);
});
test("bin creation runs through project.lockedAccess when the host provides it", async () => {
  const f = fixture();
  let lockedAccessCalls = 0;
  f.project.lockedAccess = (run) => { lockedAccessCalls++; run(); };
  await getOrCreateCutDeckBin(f.project);
  assert.equal(lockedAccessCalls, 1);
  assert.equal(f.binsCreated(), 1);
});
test("bin creation still works when the host has no lockedAccess", async () => {
  const f = fixture();
  assert.equal(typeof f.project.lockedAccess, "undefined");
  const bin = await getOrCreateCutDeckBin(f.project);
  assert.equal(bin.name, "CutDeck");
});
