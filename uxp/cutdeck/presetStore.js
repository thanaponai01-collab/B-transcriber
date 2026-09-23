/* Quick-effect presets as real files in a folder the user picks (e.g. a OneDrive or Dropbox
   folder), instead of only in UXP localStorage. One file per preset, named after it —
   "Zoom In.json" — so the folder reads like a preset library: browse it, copy one preset to
   someone, delete one by hand.

   localStorage is per plugin install: reinstalling the .ccx, switching between source-load and
   the packaged plugin, or moving to another machine all start from an empty preset list. Files
   in a synced folder survive all three.

   localStorage stays as a cache: the panel still works with no folder linked (exactly the old
   behavior), and if the linked folder is unreachable at startup the cached list is shown with
   a warning rather than an empty grid.

   Every edit touches only its own preset's file and re-scans the folder first, so two machines
   sharing a folder can never erase each other's presets by writing back a stale list. Removing
   a preset moves its file into a "Removed" subfolder rather than deleting it — the panel's ×
   has no confirmation, so a mis-click must stay recoverable.

   A .json file in the folder that isn't a CutDeck preset is left alone and skipped; one that
   claims to be a CutDeck preset but can't be read is skipped and reported, never overwritten.

   v1 of this module kept every preset in one "cutdeck-presets.json". Finding that file on load
   splits it into per-preset files and renames it to "cutdeck-presets.json.migrated".

   File API references (UXP Persistent File Storage): FileSystemProvider.getFolder /
   createPersistentToken / getEntryForPersistentToken / getEntryWithUrl, Folder.getEntries /
   createFile({overwrite}) / createFolder / renameEntry({overwrite}), Entry.moveTo({overwrite,
   newName}) / delete, File.read / write. Adobe documents that a persistent token "is not
   guaranteed to last forever", so the folder's native path is kept too and tried as a fallback
   (this plugin declares localFileSystem: fullAccess). */

const FILE_FORMAT = "cutdeck-fx-preset";
const FILE_VERSION = 2;
const LEGACY_FILE_NAME = "cutdeck-presets.json";
const LEGACY_FORMAT = "cutdeck-fx-presets";
const REMOVED_FOLDER = "Removed";
const CACHE_KEY = "cutdeck.fx.presets";
const LINK_KEY = "cutdeck.fx.presetFolder";

function isValidPreset(p) {
  return !!p && typeof p.id === "string" && p.id !== "" && typeof p.name === "string"
    && Array.isArray(p.components);
}

/* A preset name as a Windows/macOS-safe file name. Thai and other scripts pass through. */
function fileNameFor(name) {
  const base = String(name || "")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/[. ]+$/, "")
    .trim()
    .slice(0, 120);
  return (base || "Preset") + ".json";
}

function serializePreset(preset) {
  return JSON.stringify({ format: FILE_FORMAT, version: FILE_VERSION, preset }, null, 2) + "\n";
}

/* Classifies one .json file's text. `foreign` files are silently ignored; `error` ones are
   CutDeck files that can't be used, and are reported. */
function parsePresetFile(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (error) {
    return { kind: "foreign" };
  }
  if (data && data.format === LEGACY_FORMAT && Array.isArray(data.presets)) {
    return { kind: "legacy", presets: data.presets.filter(isValidPreset) };
  }
  if (!data || data.format !== FILE_FORMAT) return { kind: "foreign" };
  if (typeof data.version === "number" && data.version > FILE_VERSION) {
    return { kind: "error", message: `written by a newer CutDeck (format v${data.version}) — update this plugin` };
  }
  if (!isValidPreset(data.preset)) return { kind: "error", message: "not a complete preset" };
  return { kind: "preset", preset: data.preset };
}

function byId(a, b) {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function createPresetStore(options) {
  const opts = options || {};
  const fs = opts.localFileSystem;
  const storage = opts.storage;

  let folder = null;
  let folderPath = null;

  function readCache() {
    try {
      const saved = JSON.parse(storage.getItem(CACHE_KEY) || "null");
      return Array.isArray(saved) ? saved.filter(isValidPreset) : [];
    } catch (_) {
      return [];
    }
  }
  function writeCache(list) {
    try { storage.setItem(CACHE_KEY, JSON.stringify(list)); } catch (_) { /* cache only */ }
  }
  function readLink() {
    try { return JSON.parse(storage.getItem(LINK_KEY) || "null"); } catch (_) { return null; }
  }

  /* Reads every preset file in `dir`. Returns { entries: Map(id -> {entry, preset}),
     legacy: {entry, presets} | null, warnings: [] }. Duplicate ids keep the first file. */
  async function scan(dir) {
    const entries = new Map();
    const warnings = [];
    let legacy = null;
    for (const entry of await dir.getEntries()) {
      if (!entry.isFile || !/\.json$/i.test(entry.name)) continue;
      let parsed;
      try {
        parsed = parsePresetFile(await entry.read());
      } catch (error) {
        warnings.push(`${entry.name}: could not be read (${error.message || error})`);
        continue;
      }
      if (parsed.kind === "legacy" && entry.name === LEGACY_FILE_NAME) legacy = { entry, presets: parsed.presets };
      else if (parsed.kind === "error") warnings.push(`${entry.name}: ${parsed.message} — skipped`);
      else if (parsed.kind === "preset" && !entries.has(parsed.preset.id)) {
        entries.set(parsed.preset.id, { entry, preset: parsed.preset });
      }
    }
    return { entries, legacy, warnings };
  }

  /* Writes to a temp name, then renames over the target, so a crash or a sync client reading
     mid-write never sees a half-written preset. The temp name doesn't end in .json, so a scan
     never mistakes it for a preset. */
  async function writePresetFile(dir, fileName, preset) {
    const tmp = await dir.createFile(fileName + ".tmp", { overwrite: true });
    await tmp.write(serializePreset(preset));
    await dir.renameEntry(tmp, fileName, { overwrite: true });
  }

  /* A file name for `preset` that no OTHER preset's file already uses. */
  function freeFileName(entries, preset) {
    const taken = new Set();
    for (const [id, { entry }] of entries) if (id !== preset.id) taken.add(entry.name.toLowerCase());
    const first = fileNameFor(preset.name);
    if (!taken.has(first.toLowerCase())) return first;
    const stem = first.slice(0, -".json".length);
    for (let n = 2; ; n++) {
      const candidate = `${stem} (${n}).json`;
      if (!taken.has(candidate.toLowerCase())) return candidate;
    }
  }

  async function removedFolder(dir) {
    const existing = (await dir.getEntries()).find((e) => e.isFolder && e.name === REMOVED_FOLDER);
    return existing || dir.createFolder(REMOVED_FOLDER);
  }

  /* Splits a v1 cutdeck-presets.json into per-preset files (skipping ids already on disk),
     then renames it out of the way. */
  async function migrateLegacy(dir, state) {
    if (!state.legacy) return;
    for (const preset of state.legacy.presets) {
      if (state.entries.has(preset.id)) continue;
      const name = freeFileName(state.entries, preset);
      await writePresetFile(dir, name, preset);
      state.entries.set(preset.id, { entry: { name }, preset });
    }
    await dir.renameEntry(state.legacy.entry, LEGACY_FILE_NAME + ".migrated", { overwrite: true });
    state.legacy = null;
  }

  function listOf(state) {
    return [...state.entries.values()].map((e) => e.preset).sort(byId);
  }

  async function resolveLinkedFolder(link) {
    if (link.token) {
      try {
        const entry = await fs.getEntryForPersistentToken(link.token);
        if (entry && entry.isFolder) return entry;
      } catch (_) { /* stale token — try the path below */ }
    }
    if (link.path && typeof fs.getEntryWithUrl === "function") {
      const entry = await fs.getEntryWithUrl("file:/" + link.path.replace(/\\/g, "/").replace(/^\/+/, ""));
      if (entry && entry.isFolder) return entry;
    }
    throw new Error(`Preset folder is unreachable: ${link.path || "(unknown path)"}. Reconnect the drive, or choose the folder again in Settings.`);
  }

  /* Folder to edit in, or null when none is linked. Linked but unreachable at startup: retry
     now, and refuse the edit if it still fails — an edit saved to the cache alone would be
     silently discarded the next time the folder loads. */
  async function editableFolder() {
    const link = readLink();
    if (link && !folder) folder = await resolveLinkedFolder(link);
    return folder;
  }

  /* Returns { presets, path, error }. Never throws: an unreachable folder falls back to the
     cached list with `error` set, so the panel still opens with its buttons. Unreadable
     preset files are skipped and named in `error`. */
  async function load() {
    const cached = readCache();
    const link = readLink();
    if (!link) return { presets: cached, path: null, error: null };
    folderPath = link.path || null;
    try {
      folder = await resolveLinkedFolder(link);
      const state = await scan(folder);
      await migrateLegacy(folder, state);
      const presets = listOf(state);
      writeCache(presets);
      return { presets, path: folderPath, error: state.warnings.length ? state.warnings.join("; ") : null };
    } catch (error) {
      folder = null;
      return { presets: cached, path: folderPath, error: error.message || String(error) };
    }
  }

  /* Opens the folder picker. Returns null if the user cancelled, else { presets, path }.
     This machine's presets that the folder doesn't have yet are written into it. */
  async function chooseFolder() {
    const picked = await fs.getFolder();
    if (!picked) return null;
    const state = await scan(picked);
    await migrateLegacy(picked, state);
    for (const preset of readCache()) {
      if (state.entries.has(preset.id)) continue;
      const name = freeFileName(state.entries, preset);
      await writePresetFile(picked, name, preset);
      state.entries.set(preset.id, { entry: { name }, preset });
    }
    let token = null;
    try { token = await fs.createPersistentToken(picked); } catch (_) { /* path fallback only */ }
    folder = picked;
    folderPath = picked.nativePath || null;
    storage.setItem(LINK_KEY, JSON.stringify({ token, path: folderPath }));
    const presets = listOf(state);
    writeCache(presets);
    return { presets, path: folderPath };
  }

  async function add(preset) {
    const dir = await editableFolder();
    if (!dir) {
      const next = [...readCache(), preset];
      writeCache(next);
      return next;
    }
    const state = await scan(dir);
    const name = freeFileName(state.entries, preset);
    await writePresetFile(dir, name, preset);
    state.entries.set(preset.id, { entry: { name }, preset });
    const next = listOf(state);
    writeCache(next);
    return next;
  }

  async function rename(id, name) {
    const dir = await editableFolder();
    if (!dir) {
      const next = readCache().map((p) => (p.id === id ? { ...p, name } : p));
      writeCache(next);
      return next;
    }
    const state = await scan(dir);
    const found = state.entries.get(id);
    if (!found) throw new Error("That preset's file is no longer in the preset folder — it may have been removed on another machine.");
    const renamed = { ...found.preset, name };
    const newFileName = freeFileName(state.entries, renamed);
    // New file first, old one second: a failure in between leaves a duplicate, never a loss.
    await writePresetFile(dir, newFileName, renamed);
    if (found.entry.name.toLowerCase() !== newFileName.toLowerCase()) await found.entry.delete();
    state.entries.set(id, { entry: { name: newFileName }, preset: renamed });
    const next = listOf(state);
    writeCache(next);
    return next;
  }

  async function remove(id) {
    const dir = await editableFolder();
    if (!dir) {
      const next = readCache().filter((p) => p.id !== id);
      writeCache(next);
      return next;
    }
    const state = await scan(dir);
    const found = state.entries.get(id);
    if (found) {
      const bin = await removedFolder(dir);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      await found.entry.moveTo(bin, { newName: `${stamp} ${found.entry.name}`, overwrite: true });
      state.entries.delete(id);
    }
    const next = listOf(state);
    writeCache(next);
    return next;
  }

  return { load, chooseFolder, add, rename, remove, get path() { return folderPath; } };
}

module.exports = {
  createPresetStore, parsePresetFile, serializePreset, fileNameFor,
  LEGACY_FILE_NAME, REMOVED_FOLDER, CACHE_KEY, LINK_KEY,
};
