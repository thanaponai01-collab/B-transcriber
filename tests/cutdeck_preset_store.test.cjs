const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const store = require(path.join(__dirname, "..", "uxp", "cutdeck", "presetStore.js"));
const { createPresetStore, parsePresetFile, serializePresets, mergePresets, PRESET_FILE_NAME, CACHE_KEY, LINK_KEY } = store;

/* In-memory stand-ins for UXP's localStorage and localFileSystem — only the calls presetStore uses. */
function fakeStorage(initial) {
  const map = new Map(Object.entries(initial || {}));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    map,
  };
}
function fakeFolder(nativePath, files) {
  const disk = new Map(Object.entries(files || {}));
  const fileEntry = (name) => ({
    name, isFile: true, isFolder: false,
    read: async () => disk.get(name),
    write: async (text) => { disk.set(name, text); return text.length; },
  });
  return {
    nativePath, isFolder: true, isFile: false, disk,
    getEntries: async () => [...disk.keys()].map(fileEntry),
    createFile: async (name) => fileEntry(name),
    renameEntry: async (entry, newName) => {
      disk.set(newName, disk.get(entry.name));
      disk.delete(entry.name);
    },
  };
}
function fakeFs(folder, opts) {
  const o = opts || {};
  return {
    getFolder: async () => (o.cancel ? null : folder),
    createPersistentToken: async () => "tok-1",
    getEntryForPersistentToken: async () => {
      if (o.tokenBroken) throw new Error("stale token");
      return folder;
    },
    getEntryWithUrl: async () => {
      if (o.unreachable) throw new Error("no such path");
      return folder;
    },
  };
}
const preset = (id, name) => ({ id, name: name || id, components: [{ matchName: "AE.ADBE Gaussian Blur 2", params: [] }] });
const fileText = (presets) => serializePresets(presets);
const onDisk = (folder) => JSON.parse(folder.disk.get(PRESET_FILE_NAME)).presets.map((p) => p.id);

test("parsePresetFile refuses non-JSON and foreign JSON, drops malformed presets", () => {
  assert.throws(() => parsePresetFile("{nope"), /not valid JSON/);
  assert.throws(() => parsePresetFile(JSON.stringify([preset("a")])), /not a CutDeck preset file/);
  assert.throws(() => parsePresetFile(JSON.stringify({ format: "cutdeck-fx-presets", version: 99, presets: [] })), /newer CutDeck/);
  const parsed = parsePresetFile(JSON.stringify({ format: "cutdeck-fx-presets", version: 1, presets: [preset("a"), { id: "b" }] }));
  assert.deepEqual(parsed.map((p) => p.id), ["a"]);
});

test("mergePresets keeps file order, appends local-only presets, file wins on id clash", () => {
  const merged = mergePresets([preset("a", "file A"), preset("b")], [preset("a", "local A"), preset("c")]);
  assert.deepEqual(merged.map((p) => p.id), ["a", "b", "c"]);
  assert.equal(merged[0].name, "file A");
});

test("no folder linked: behaves exactly like the old localStorage-only store", async () => {
  const storage = fakeStorage({ [CACHE_KEY]: JSON.stringify([preset("a")]) });
  const s = createPresetStore({ localFileSystem: fakeFs(null), storage });
  const loaded = await s.load();
  assert.deepEqual(loaded, { presets: [preset("a")], path: null, error: null });
  const next = await s.update((list) => [...list, preset("b")]);
  assert.deepEqual(next.map((p) => p.id), ["a", "b"]);
  assert.deepEqual(JSON.parse(storage.getItem(CACHE_KEY)).map((p) => p.id), ["a", "b"]);
});

test("choosing a folder with no preset file writes the local presets there and links it", async () => {
  const folder = fakeFolder("D:\\Sync\\CutDeck");
  const storage = fakeStorage({ [CACHE_KEY]: JSON.stringify([preset("a")]) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage });
  const res = await s.chooseFolder();
  assert.equal(res.path, "D:\\Sync\\CutDeck");
  assert.deepEqual(onDisk(folder), ["a"]);
  assert.ok(!folder.disk.has(PRESET_FILE_NAME + ".tmp"), "temp file must be renamed away");
  assert.deepEqual(JSON.parse(storage.getItem(LINK_KEY)), { token: "tok-1", path: "D:\\Sync\\CutDeck" });
});

test("choosing a folder that already has presets (second machine) merges both lists", async () => {
  const folder = fakeFolder("D:\\Sync", { [PRESET_FILE_NAME]: fileText([preset("fromA")]) });
  const storage = fakeStorage({ [CACHE_KEY]: JSON.stringify([preset("localB")]) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage });
  const res = await s.chooseFolder();
  assert.deepEqual(res.presets.map((p) => p.id), ["fromA", "localB"]);
  assert.deepEqual(onDisk(folder), ["fromA", "localB"]);
});

test("cancelling the picker changes nothing", async () => {
  const storage = fakeStorage();
  const s = createPresetStore({ localFileSystem: fakeFs(null, { cancel: true }), storage });
  assert.equal(await s.chooseFolder(), null);
  assert.equal(storage.getItem(LINK_KEY), null);
});

test("a corrupt preset file is never overwritten, on link or on edit", async () => {
  const folder = fakeFolder("D:\\Sync", { [PRESET_FILE_NAME]: "{ half-synced" });
  const storage = fakeStorage({ [CACHE_KEY]: JSON.stringify([preset("a")]) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage });
  await assert.rejects(s.chooseFolder(), /not valid JSON/);
  assert.equal(folder.disk.get(PRESET_FILE_NAME), "{ half-synced");
  assert.equal(storage.getItem(LINK_KEY), null, "must not link a folder it refused");

  // Already linked, file corrupted later: load reports it, edits refuse to write.
  storage.setItem(LINK_KEY, JSON.stringify({ token: "tok-1", path: "D:\\Sync" }));
  const loaded = await s.load();
  assert.match(loaded.error, /not valid JSON/);
  assert.deepEqual(loaded.presets.map((p) => p.id), ["a"], "falls back to cache");
  await assert.rejects(s.update((list) => [...list, preset("b")]), /not valid JSON/);
  assert.equal(folder.disk.get(PRESET_FILE_NAME), "{ half-synced");
});

test("an edit re-reads the file first, so a stale machine cannot delete another machine's preset", async () => {
  const folder = fakeFolder("D:\\Sync", { [PRESET_FILE_NAME]: fileText([preset("a")]) });
  const storage = fakeStorage({ [LINK_KEY]: JSON.stringify({ token: "tok-1", path: "D:\\Sync" }) });
  const s = createPresetStore({ localFileSystem: fakeFs(folder), storage });
  await s.load();
  // Another machine captures "fromOther" after this one loaded.
  folder.disk.set(PRESET_FILE_NAME, fileText([preset("a"), preset("fromOther")]));
  await s.update((list) => [...list, preset("mine")]);
  assert.deepEqual(onDisk(folder), ["a", "fromOther", "mine"]);
});

test("load: linked file wins over the cache and refreshes it", async () => {
  const folder = fakeFolder("D:\\Sync", { [PRESET_FILE_NAME]: fileText([preset("file")]) });
  const storage = fakeStorage({
    [CACHE_KEY]: JSON.stringify([preset("stale")]),
    [LINK_KEY]: JSON.stringify({ token: "tok-1", path: "D:\\Sync" }),
  });
  const loaded = await createPresetStore({ localFileSystem: fakeFs(folder), storage }).load();
  assert.deepEqual(loaded.presets.map((p) => p.id), ["file"]);
  assert.deepEqual(JSON.parse(storage.getItem(CACHE_KEY)).map((p) => p.id), ["file"]);
});

test("load: a missing file in a linked folder is recreated from the cache", async () => {
  const folder = fakeFolder("D:\\Sync");
  const storage = fakeStorage({
    [CACHE_KEY]: JSON.stringify([preset("a")]),
    [LINK_KEY]: JSON.stringify({ token: "tok-1", path: "D:\\Sync" }),
  });
  await createPresetStore({ localFileSystem: fakeFs(folder), storage }).load();
  assert.deepEqual(onDisk(folder), ["a"]);
});

test("load: a stale token falls back to the saved path", async () => {
  const folder = fakeFolder("D:\\Sync", { [PRESET_FILE_NAME]: fileText([preset("a")]) });
  const storage = fakeStorage({ [LINK_KEY]: JSON.stringify({ token: "old", path: "D:\\Sync" }) });
  const loaded = await createPresetStore({ localFileSystem: fakeFs(folder, { tokenBroken: true }), storage }).load();
  assert.equal(loaded.error, null);
  assert.deepEqual(loaded.presets.map((p) => p.id), ["a"]);
});

test("unreachable folder: load shows cached presets with an error, and edits are refused", async () => {
  const storage = fakeStorage({
    [CACHE_KEY]: JSON.stringify([preset("a")]),
    [LINK_KEY]: JSON.stringify({ token: "old", path: "E:\\Unplugged" }),
  });
  const s = createPresetStore({ localFileSystem: fakeFs(null, { tokenBroken: true, unreachable: true }), storage });
  const loaded = await s.load();
  assert.deepEqual(loaded.presets.map((p) => p.id), ["a"]);
  assert.equal(loaded.path, "E:\\Unplugged");
  assert.ok(loaded.error);
  await assert.rejects(s.update((list) => [...list, preset("b")]));
  assert.deepEqual(JSON.parse(storage.getItem(CACHE_KEY)).map((p) => p.id), ["a"], "cache must not diverge from the file");
});
