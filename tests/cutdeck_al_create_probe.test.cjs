/* capabilityProbe.js probeCreateAdjustmentLayer asks real Premiere whether a generated one-AL
   .prproj imports. Provable off-host: given a host that behaves a certain way (item lands in
   ADJ & FX / lands in a sub-bin / nothing arrives), the probe reports that and verdicts only
   on the good case. What real Premiere does is the point of running it, not provable here. */
const test = require("node:test");
const assert = require("node:assert/strict");

const { probeCreateAdjustmentLayer, formatCreateAdjustmentLayerReport, newItemsByName } =
  require("../uxp/cutdeck/capabilityProbe.js");
const alProject = require("../uxp/cutdeck/timeline/alProject.js");

const bin = (name, items = []) => ({ name, type: 2, items, getItems: async () => bin.snapshot(items) });
bin.snapshot = (items) => items.slice();
const clip = (name, videoInfo) => ({ name, type: 1, videoInfo });

function fakeHost({ landing = "adj", width = 1080, height = 1920, pickGenerated = true }) {
  const adjBin = bin("ADJ & FX", [clip("Adjustment Layer 1920x1080", { width: 1920, height: 1080 })]);
  const root = bin("Root", [bin("CutDeck", [adjBin])]);
  const imported = [];
  const project = {
    getActiveSequence: async () => seq,
    getRootItem: async () => root,
    importFiles: async (paths, suppressUI, target) => {
      imported.push({ paths, suppressUI, target });
      const name = alProject.adjustmentLayerName(width, height);
      const item = clip(name, { width, height });
      if (landing === "adj") target.items.push(item);
      else if (landing === "subbin") target.items.push(bin("CutDeck 1080x1920", [item]));
      return true;
    },
  };
  const seq = {
    name: "Short 01",
    getSettings: async () => ({
      getVideoFrameRect: async () => ({ width, height }),
      getVideoFrameRate: () => ({ ticksPerFrame: 10160640000 }),
      getVideoPixelAspectRatio: async () => "1:1",
    }),
  };
  const al = {
    ADJ_BIN_NAME: "ADJ & FX",
    getOrCreateAdjBin: async () => adjBin,
    detectResolutionFromMetadata: async (it) => it.videoInfo || null,
    findAdjustmentLayerItem: async () => {
      const want = alProject.adjustmentLayerName(width, height);
      const found = adjBin.items.find((i) => i.name === want);
      return pickGenerated && found ? found : adjBin.items[0];
    },
  };
  const written = [];
  const deps = { al, writeFile: async (name, bytes) => { written.push({ name, bytes }); return `C:\\tmp\\${name}`; } };
  return { ppro: { Project: { getActiveProject: async () => project } }, deps, imported, written };
}

test("verdict 'works' when the AL lands in ADJ & FX at the right size and would be picked", async () => {
  const h = fakeHost({});
  const report = await probeCreateAdjustmentLayer(h.ppro, h.deps);
  assert.equal(report.verdict, "works");
  assert.equal(h.written[0].name, "CutDeck 1080x1920.prproj");
  assert.ok(h.written[0].bytes[0] === 0x1f && h.written[0].bytes[1] === 0x8b, "gzip bytes written");
  assert.deepEqual(h.imported[0].paths, ["C:\\tmp\\CutDeck 1080x1920.prproj"]);
  assert.equal(h.imported[0].suppressUI, true);
  assert.match(formatCreateAdjustmentLayerReport(report), /CutDeck can create "Adjustment Layer 1080x1920"/);
});

test("reports a sub-bin landing instead of claiming success", async () => {
  const h = fakeHost({ landing: "subbin" });
  const report = await probeCreateAdjustmentLayer(h.ppro, h.deps);
  assert.equal(report.verdict, "lands-in-subbin");
  const landing = report.findings.find((f) => f.id === "landing");
  assert.match(landing.answer, /\(a bin\)/);
});

test("no verdict when nothing arrives", async () => {
  const h = fakeHost({ landing: "none" });
  const report = await probeCreateAdjustmentLayer(h.ppro, h.deps);
  assert.equal(report.verdict, null);
  assert.match(report.findings.find((f) => f.id === "landing").answer, /nowhere visible/);
  assert.match(formatCreateAdjustmentLayerReport(report), /No verdict/);
});

test("no verdict when CutDeck would still pick a different AL", async () => {
  const h = fakeHost({ pickGenerated: false });
  const report = await probeCreateAdjustmentLayer(h.ppro, h.deps);
  assert.equal(report.verdict, null);
  assert.match(report.findings.find((f) => f.id === "pick").answer, /no — it picks "Adjustment Layer 1920x1080"/);
});

test("stops before writing anything when no sequence is open", async () => {
  const h = fakeHost({});
  const project = await h.ppro.Project.getActiveProject();
  project.getActiveSequence = async () => null;
  const report = await probeCreateAdjustmentLayer(h.ppro, h.deps);
  assert.equal(report.complete, false);
  assert.equal(h.written.length, 0);
  assert.equal(h.imported.length, 0);
});

test("newItemsByName counts duplicates", () => {
  const before = [{ name: "A" }, { name: "B" }];
  const after = [{ name: "A" }, { name: "B" }, { name: "A" }];
  assert.deepEqual(newItemsByName(before, after).map((i) => i.name), ["A"]);
});
