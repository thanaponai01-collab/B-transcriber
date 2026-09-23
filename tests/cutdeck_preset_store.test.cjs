const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const {
  createPresetStore, parsePresetFile, serializePreset, fileNameFor,
  LEGACY_FILE_NAME, REMOVED_FOLDER, CACHE_KEY, LINK_KEY,
} = require(path.join(__dirname, "..", "uxp", "cutdeck", "presetStore.js"));

/* In-memory stand-ins for UXP's localStorage and localFileSystem — only the calls presetStore uses. */
function fakeStorage(initial) {
  const map = new Map(Object.entries(initial || {}));
  return { getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, String(v)) };
}
function fakeFolder(nativePath, files) {
  const disk = new Map(Object.entries(files || {}));
  const sub = new Map();
  const folder = {
    nativePath, name: nativePath, isFolder: true, isFile: false, disk, sub,
    getEntries: async () => [
      ...[...disk.keys()].map(fileEntry),
      ...[...sub.values()],
    ],
    createFile: async (name) => fileEntry(name),
    createFolder: async (name) => { const f = fakeFolder(name); sub.set(name, f); return f; },
    renameEntry: async (entry, newName) => {
      disk.set(newName, disk.get(entry.name));
      disk.delete(entry.name);
    },
  };
  function fileEntry(name) {
    return {
      name, isFile: true, isFolder: false,
      read: async () => disk.get(name),
      write: async (text) => { disk.set(name, text); return text.length; },
      delete: async () => { disk.delete(name); return 0; },
      moveTo: async (target, opts) => { target.disk.set(opts.newName || name, disk.get(name)); disk.delete(name); },
    };
  }
  return folder;
}
function fakeFs(folder, opts) {
  const o = opts || {};
  return {
    getFolder: async () => (o.cancel ? null : folder),
    createPersistentToken: async () => "tok-1",
    getEntryForPersistentToken: async () => { if (o.tokenBroken) throw new Error("stale token"); return folder; },
    getEntryWithUrl: async () => { if (o.unreachable) throw new Error("no such path"); return folder; },
  };
}
const preset = (id, name) => ({ id, name: name || id, components: [{ matchName: "AE.ADBE Geometry2", params: [] }] });
const linked = (extra) => fakeStorage({ [LINK_KEY]: JSON.stringify({ token: "tok-1", path: "F:\\Presets" }), ...extra });
const names = (folder) => [...folder.disk.keys()].sort();

test("fileNameFor keeps readable names (incl. Thai) and strips characters Windows rejects", () => {
  assert.equal(fileNameFor("Zoom In"), "Zoom In.json");
  assert.equal(fileNameFor("ซูมเข้า"), "ซูมเข้า.json");
  assert.equal(fileNameFor('a/b:c*?"<>|'), "a_b_c______.json");
  assert.equal(fileNameFor("trailing. "), "trailing.json");
  assert.equal(fileNameFor("  "), "Preset.json");
});

test("parsePresetFile: foreign JSON is ignored, broken CutDeck files are errors", () => {
  assert.equal(parsePresetFile("{nope").kind, "foreign");
  assert.equal(parsePresetFile(JSON.stringify({ some: "other tool" })).kind, "foreign");
  assert.equal(parsePresetFile(serializePreset(preset("a"))).kind, "preset");
  assert.equal(parsePresetFile(JSON.stringify({ format: "cutdeck-fx-preset", version: 99, preset: preset("a") })).kind, "error");
  assert.equal(parsePresetFile(JSON.stringify({ format: "cutdeck-fx-preset", version: 2, preset: { id: "a" } })).kind, "error");
});

test("no folder linked: add / rename / remove work on localStorage exactly as before", async () => {
  const storage = fakeStorage({ [CACHE_KEY]: JSON.stringify([preset("a")]) });
  const s = createPresetStore({ localFileSystem: fakeFs(null), storage });
  assert.deepEqual(await s.load(), { presets: [preset("a")], path: null, error: null });
  await s.add(preset("b"));
  await s.rename("a", "Renamed");
  const next = await s.remove("b");
  assert.deepEqual(next.map((p) => [p.id, p.name]), [["a", "Renamed"]]);
});

test("choosing a folder writes one file per preset, named after it", async () => {
  const folder = fakeFolder("F:\\Presets");
  const storage = fakeStorage({ [CACHE_KEY]: JSON.stringify([preset("fx-1", "Zoom In"), preset("fx-2", "Shake")]) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage });
  const res = await s.chooseFolder();
  assert.equal(res.path, "F:\\Presets");
  assert.deepEqual(names(folder), ["Shake.json", "Zoom In.json"]);
  assert.deepEqual(JSON.parse(storage.getItem(LINK_KEY)), { token: "tok-1", path: "F:\\Presets" });
});

test("two presets with the same name get distinct files", async () => {
  const folder = fakeFolder("F:\\Presets");
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage: linked() });
  await s.load();
  await s.add(preset("fx-1", "Zoom"));
  await s.add(preset("fx-2", "Zoom"));
  assert.deepEqual(names(folder), ["Zoom (2).json", "Zoom.json"]);
});

test("a v1 cutdeck-presets.json is split into per-preset files and set aside", async () => {
  const legacy = JSON.stringify({ format: "cutdeck-fx-presets", version: 1, presets: [preset("fx-1", "Transform"), preset("fx-2", "Blur")] });
  const folder = fakeFolder("F:\\Presets", { [LEGACY_FILE_NAME]: legacy });
  const loaded = await createPresetStore({ localFileSystem: fakeFs(folder), storage: linked() }).load();
  assert.deepEqual(loaded.presets.map((p) => p.name), ["Transform", "Blur"]);
  assert.deepEqual(names(folder), ["Blur.json", "Transform.json", LEGACY_FILE_NAME + ".migrated"]);
});

test("rename writes the new file and drops the old one", async () => {
  const folder = fakeFolder("F:\\Presets", { "Old.json": serializePreset(preset("fx-1", "Old")) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage: linked() });
  await s.load();
  await s.rename("fx-1", "New");
  assert.deepEqual(names(folder), ["New.json"]);
  assert.equal(parsePresetFile(folder.disk.get("New.json")).preset.id, "fx-1");
});

test("remove moves the file into Removed/, never deletes it", async () => {
  const folder = fakeFolder("F:\\Presets", { "Zoom.json": serializePreset(preset("fx-1", "Zoom")) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage: linked() });
  await s.load();
  assert.deepEqual(await s.remove("fx-1"), []);
  assert.deepEqual(names(folder), []);
  const bin = folder.sub.get(REMOVED_FOLDER);
  assert.equal([...bin.disk.keys()].length, 1);
  assert.match([...bin.disk.keys()][0], / Zoom\.json$/);
});

test("edits re-scan the folder, so another machine's new preset survives", async () => {
  const folder = fakeFolder("F:\\Presets", { "A.json": serializePreset(preset("fx-1", "A")) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage: linked() });
  await s.load();
  folder.disk.set("FromOther.json", serializePreset(preset("fx-2", "FromOther")));
  const next = await s.add(preset("fx-3", "Mine"));
  assert.deepEqual(next.map((p) => p.name), ["A", "FromOther", "Mine"]);
});

test("unreadable CutDeck files are skipped and reported; foreign JSON is ignored silently", async () => {
  const folder = fakeFolder("F:\\Presets", {
    "Good.json": serializePreset(preset("fx-1", "Good")),
    "Future.json": JSON.stringify({ format: "cutdeck-fx-preset", version: 9, preset: preset("fx-2") }),
    "other-tool.json": "{\"x\":1}",
  });
  const loaded = await createPresetStore({ localFileSystem: fakeFs(folder), storage: linked() }).load();
  assert.deepEqual(loaded.presets.map((p) => p.name), ["Good"]);
  assert.match(loaded.error, /Future\.json/);
  assert.doesNotMatch(loaded.error, /other-tool/);
  assert.equal(folder.disk.get("Future.json").includes("\"version\":9"), true, "never rewritten");
});

test("a stale token falls back to the saved path", async () => {
  const folder = fakeFolder("F:\\Presets", { "A.json": serializePreset(preset("fx-1", "A")) });
  const loaded = await createPresetStore({ localFileSystem: fakeFs(folder, { tokenBroken: true }), storage: linked() }).load();
  assert.equal(loaded.error, null);
  assert.deepEqual(loaded.presets.map((p) => p.name), ["A"]);
});

test("unreachable folder: cached presets shown with an error, and edits are refused", async () => {
  const storage = linked({ [CACHE_KEY]: JSON.stringify([preset("fx-1", "A")]) });
  const s = createPresetStore({ localFileSystem: fakeFs(null, { tokenBroken: true, unreachable: true }), storage });
  const loaded = await s.load();
  assert.deepEqual(loaded.presets.map((p) => p.name), ["A"]);
  assert.ok(loaded.error);
  await assert.rejects(s.add(preset("fx-2", "B")));
  assert.deepEqual(JSON.parse(storage.getItem(CACHE_KEY)).map((p) => p.name), ["A"], "cache must not diverge from the folder");
});
