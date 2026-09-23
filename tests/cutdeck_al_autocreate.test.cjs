/* alLibrary.js createAdjustmentLayerForSequence: the Place AL fallback when no AL exists.
   Off-host it proves the wiring: a gzip .prproj of the right size is written, imported into
   ADJ & FX with suppressUI, and the item is found whether it lands directly or one bin down —
   and a failed import says so instead of pretending. Real Premiere behaviour is not provable here. */
const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");
const zlib = require("node:zlib");

const written = [];
const stubs = {
  uxp: {
    storage: {
      formats: { binary: "binary" },
      localFileSystem: {
        getTemporaryFolder: async () => ({
          createFile: async (name) => ({
            nativePath: `C:\\tmp\\${name}`,
            write: async (buffer, opts) => { written.push({ name, bytes: new Uint8Array(buffer), opts }); },
          }),
        }),
      },
    },
  },
};
const realLoad = Module._load;
Module._load = function (request, ...rest) {
  if (Object.prototype.hasOwnProperty.call(stubs, request)) return stubs[request];
  return realLoad.call(this, request, ...rest);
};
const al = require("../uxp/cutdeck/timeline/alLibrary.js");
// "uxp" is required lazily at call time, so the stub stays until this file's tests finish.
test.after(() => { Module._load = realLoad; });

// Bins whose move/remove actions really run when the transaction executes, so tests see
// where items end up. `failMove` makes every move action refuse, like a host that rejects it.
function bin(name, items = [], opts = {}) {
  const self = {
    name, type: 2, items,
    getItems: async () => self.items.slice(),
    createBinAction: () => () => true,
    createMoveItemAction: (item, dest) => () => {
      if (opts.failMove) return false;
      self.items = self.items.filter((i) => i !== item);
      dest.items.push(item);
      return true;
    },
    createRemoveItemAction: (item) => () => { self.items = self.items.filter((i) => i !== item); return true; },
  };
  return self;
}

function transactional(project) {
  project.transactions = [];
  project.executeTransaction = (build, label) => {
    project.transactions.push(label);
    let ok = true;
    try { build({ addAction: (action) => action() }); } catch (_) { ok = false; }
    return ok;
  };
  return project;
}

function fakeProject(landing, opts = {}) {
  const adjBin = bin("ADJ & FX");
  const root = bin("Root", [bin("CutDeck", [adjBin])]);
  const calls = [];
  return transactional({
    calls,
    adjBin,
    getRootItem: async () => root,
    importFiles: async (paths, suppressUI, target, stills) => {
      calls.push({ paths, suppressUI, target, stills });
      const item = { name: "Adjustment Layer 1080x1920", type: 1 };
      if (landing === "direct") target.items.push(item);
      if (landing === "nested") target.items.push(bin("CutDeck 1080x1920.prproj", [item], opts));
      return landing !== "none";
    },
  });
}

test("imports a gzip .prproj at the sequence size into ADJ & FX and returns the AL", async () => {
  written.length = 0;
  const project = fakeProject("direct");
  const item = await al.createAdjustmentLayerForSequence(project, 1080, 1920, 8475667200);
  assert.equal(item.name, "Adjustment Layer 1080x1920");
  assert.equal(project.calls[0].suppressUI, true);
  assert.equal(project.calls[0].target.name, "ADJ & FX");
  assert.deepEqual(project.calls[0].paths, ["C:\\tmp\\CutDeck 1080x1920.prproj"]);
  const xml = zlib.gunzipSync(Buffer.from(written[0].bytes)).toString("utf8");
  assert.match(xml, /<FrameRect>0,0,1080,1920<\/FrameRect>/);
  assert.match(xml, /<MediaFrameRate>8475667200<\/MediaFrameRate>/);
  assert.equal(written[0].opts.format, "binary");
});

test("moves the AL out of Premiere's import folder and removes the emptied folder", async () => {
  const project = fakeProject("nested");
  const item = await al.createAdjustmentLayerForSequence(project, 1080, 1920, null);
  assert.equal(item.name, "Adjustment Layer 1080x1920");
  assert.deepEqual(project.adjBin.items.map((i) => i.name), ["Adjustment Layer 1080x1920"]);
  assert.equal(project.transactions.length, 2, "move and remove are separate steps");
});

test("if the move fails, the folder (and the AL in it) is left alone and still used", async () => {
  const project = fakeProject("nested", { failMove: true });
  const item = await al.createAdjustmentLayerForSequence(project, 1080, 1920, null);
  assert.equal(item.name, "Adjustment Layer 1080x1920");
  assert.deepEqual(project.adjBin.items.map((i) => i.name), ["CutDeck 1080x1920.prproj"]);
  assert.equal(project.adjBin.items[0].items.length, 1, "AL not deleted");
});

test("flattening never touches folders CutDeck didn't make", async () => {
  const al1 = { name: "Adjustment Layer 1920x1080", type: 1 };
  const mine = bin("My ALs", [al1]);
  const two = bin("CutDeck 1920x1080.prproj", [{ name: "a", type: 1 }, { name: "b", type: 1 }]);
  const adjBin = bin("ADJ & FX", [mine, two]);
  const project = transactional({});
  assert.equal(await al.flattenImportWrappers(project, adjBin), 0);
  assert.deepEqual(adjBin.items, [mine, two]);
  assert.equal(project.transactions.length, 0);
});

test("flattens wrappers left by earlier runs, several at once", async () => {
  const a = { name: "Adjustment Layer 1080x1920", type: 1 };
  const b = { name: "Adjustment Layer 3840x2160", type: 1 };
  const adjBin = bin("ADJ & FX", [bin("CutDeck 1080x1920.prproj", [a]), bin("CutDeck 3840x2160.prproj", [b])]);
  const project = transactional({});
  assert.equal(await al.flattenImportWrappers(project, adjBin), 2);
  assert.deepEqual(adjBin.items, [a, b]);
});

test("says so when nothing arrives", async () => {
  await assert.rejects(al.createAdjustmentLayerForSequence(fakeProject("none"), 1080, 1920, null),
    /did not appear in CutDeck > ADJ & FX[\s\S]*1080x1920/);
});

// The 2026-09-23 bug: a 1920x1080 sequence reused the 1080x1920 AL instead of creating its own.
test("pickBestCandidate never hands back another size's AL when the size is known", async () => {
  const vertical = { name: "Adjustment Layer 1080x1920", type: 1 };
  const seq = { name: "Sequence 02" };
  assert.equal(await al.pickBestCandidate([vertical], 1920, 1080, seq), null);
  assert.equal(await al.pickBestCandidate([vertical], 1080, 1920, seq), vertical);
  const wide = { name: "1920x1080", type: 1 };
  assert.equal(await al.pickBestCandidate([vertical, wide], 1920, 1080, seq), wide);
  // Size unreadable: creation is impossible, so the old best-effort fallback still applies.
  assert.equal(await al.pickBestCandidate([vertical], null, null, seq), vertical);
});
