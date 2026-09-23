/* Quick-effect presets as a real JSON file in a folder the user picks (e.g. a OneDrive or
   Dropbox folder), instead of only in UXP localStorage.

   localStorage is per plugin install: reinstalling the .ccx, switching between source-load and
   the packaged plugin, or moving to another machine all start from an empty preset list. A file
   in a synced folder survives all three and can be backed up or handed to someone else.

   localStorage stays as a cache: the panel still works with no folder linked (exactly the old
   behavior), and if the linked folder is unreachable at startup the cached list is shown with
   a warning rather than an empty grid.

   Every edit is a read-modify-write against the FILE, never a blind write of the in-memory
   list. Two machines share one file; if machine B wrote its stale in-memory list back, it
   would silently delete whatever machine A captured since B last loaded. Re-reading first
   means an edit only ever changes the one preset it is about.

   A file that exists but is not valid CutDeck preset JSON is never overwritten — it may be the
   user's only copy, hand-edited or half-synced. The error is surfaced and nothing is written.

   File API references (UXP Persistent File Storage): FileSystemProvider.getFolder /
   createPersistentToken / getEntryForPersistentToken / getEntryWithUrl, Folder.getEntries /
   createFile({overwrite}) / renameEntry({overwrite}), File.read / write. Adobe documents that
   a persistent token "is not guaranteed to last forever", so the folder's native path is kept
   too and tried as a fallback (this plugin declares localFileSystem: fullAccess). */

const PRESET_FILE_NAME = "cutdeck-presets.json";
const FILE_FORMAT = "cutdeck-fx-presets";
const FILE_VERSION = 1;
const CACHE_KEY = "cutdeck.fx.presets";
const LINK_KEY = "cutdeck.fx.presetFolder";

function isValidPreset(p) {
  return !!p && typeof p.id === "string" && p.id !== "" && typeof p.name === "string"
    && Array.isArray(p.components);
}

/* Throws on anything that is not a CutDeck preset file; callers must then leave it untouched.
   Individual malformed presets inside an otherwise valid file are dropped, not fatal. */
function parsePresetFile(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (error) {
    throw new Error(`${PRESET_FILE_NAME} is not valid JSON (${error.message}) — fix or move it; CutDeck will not overwrite it.`);
  }
  if (!data || data.format !== FILE_FORMAT || !Array.isArray(data.presets)) {
    throw new Error(`${PRESET_FILE_NAME} is not a CutDeck preset file — CutDeck will not overwrite it.`);
  }
  if (typeof data.version === "number" && data.version > FILE_VERSION) {
    throw new Error(`${PRESET_FILE_NAME} was written by a newer CutDeck (format v${data.version}) — update this plugin before editing presets.`);
  }
  return data.presets.filter(isValidPreset);
}

function serializePresets(presets) {
  return JSON.stringify({ format: FILE_FORMAT, version: FILE_VERSION, presets }, null, 2) + "\n";
}

/* Used once, when a folder is first linked: keep everything in the file, then append local
   presets the file doesn't have. On an id clash the file wins — it is the shared copy. */
function mergePresets(filePresets, localPresets) {
  const ids = new Set(filePresets.map((p) => p.id));
  return [...filePresets, ...localPresets.filter((p) => !ids.has(p.id))];
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

  /* null when the file doesn't exist yet; throws when it exists but can't be read or parsed. */
  async function readFile(dir) {
    const entries = await dir.getEntries();
    const entry = entries.find((e) => e.name === PRESET_FILE_NAME && e.isFile);
    if (!entry) return null;
    return parsePresetFile(await entry.read());
  }

  /* Write to a temp file, then rename over the real one, so a crash or a sync client reading
     mid-write never sees a half-written preset file. */
  async function writeFile(dir, list) {
    const tmpName = PRESET_FILE_NAME + ".tmp";
    const tmp = await dir.createFile(tmpName, { overwrite: true });
    await tmp.write(serializePresets(list));
    await dir.renameEntry(tmp, PRESET_FILE_NAME, { overwrite: true });
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

  /* Returns { presets, path, error }. Never throws: an unreachable or unreadable file falls
     back to the cached list with `error` set, so the panel still opens with its buttons. */
  async function load() {
    const cached = readCache();
    const link = readLink();
    if (!link) return { presets: cached, path: null, error: null };
    folderPath = link.path || null;
    try {
      folder = await resolveLinkedFolder(link);
      const fromFile = await readFile(folder);
      if (fromFile === null) {
        // Linked folder, file gone (deleted, or not synced down yet): recreate it from cache.
        await writeFile(folder, cached);
        return { presets: cached, path: folderPath, error: null };
      }
      writeCache(fromFile);
      return { presets: fromFile, path: folderPath, error: null };
    } catch (error) {
      folder = null;
      return { presets: cached, path: folderPath, error: error.message || String(error) };
    }
  }

  /* Opens the folder picker. Returns null if the user cancelled, else { presets, path }.
     Throws (and links nothing) if that folder already holds an unreadable preset file. */
  async function chooseFolder() {
    const picked = await fs.getFolder();
    if (!picked) return null;
    const fromFile = await readFile(picked);
    const merged = fromFile === null ? readCache() : mergePresets(fromFile, readCache());
    await writeFile(picked, merged);
    let token = null;
    try { token = await fs.createPersistentToken(picked); } catch (_) { /* path fallback only */ }
    folder = picked;
    folderPath = picked.nativePath || null;
    storage.setItem(LINK_KEY, JSON.stringify({ token, path: folderPath }));
    writeCache(merged);
    return { presets: merged, path: folderPath };
  }

  /* Applies `edit(list) -> list` to the freshest copy and saves it. With a folder linked that
     is the file on disk (see header); otherwise the localStorage cache. Returns the new list. */
  async function update(edit) {
    const link = readLink();
    // Linked but unreachable at startup: retry now, and refuse the edit if it still fails.
    // Saving to the cache alone would be silently discarded the next time the file loads.
    if (link && !folder) folder = await resolveLinkedFolder(link);
    if (!folder) {
      const next = edit(readCache());
      writeCache(next);
      return next;
    }
    const fromFile = await readFile(folder);
    const next = edit(fromFile === null ? readCache() : fromFile);
    await writeFile(folder, next);
    writeCache(next);
    return next;
  }

  return { load, chooseFolder, update, get path() { return folderPath; } };
}

module.exports = {
  createPresetStore, parsePresetFile, serializePresets, mergePresets,
  PRESET_FILE_NAME, CACHE_KEY, LINK_KEY,
};
