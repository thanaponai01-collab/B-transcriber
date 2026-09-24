// transform/frameBounds.js — where a clip is actually DRAWN, in sequence pixels, measured from
// pixels. Premiere gives plugins no size for a Graphic's text (PREMIERE_FACTS "Graphic Text
// layer"), so: save the frame under the playhead with the clip on, again with it off, and ask
// the CutDeck helper (cutdeck/frame_bounds.py, request `frame_bounds`) for the box where the two
// differ. Proven live 2026-09-24 on a text Graphic: 418 x 87 px, exactly the text's pixels.
//
// APIs (reference/adobe/api/premierepro.txt): Exporter.exportSequenceFrame (:333),
// Sequence.getPlayerPosition (:575), VideoClipTrackItem.createSetDisabledAction (:711),
// getStartTime / getEndTime (:728, :719); uxp.storage getTemporaryFolder, Folder.getEntry,
// Entry.getMetadata().size, nativePath (api/uxp.txt). Call shape as Adobe's own sample
// (samples/sample-panels/premiere-api/src/export.ts:25): bare file name + folder path, PNG.
//
// exportSequenceFrame RESOLVES BEFORE THE FRAME IS DRAWN and draws the timeline as it is when it
// renders (PREMIERE_FACTS, live 2026-09-24: switching the clip straight after swapped the two
// frames). So each save waits for its file to exist and stop growing before anything changes.
//
// Switching the clip off and back on is two undo steps. It is switched back on in a `finally`,
// and never switched off at all unless the first frame was fully written.

const { toTicks } = require("../host/ticks.js");
const { runTransaction } = require("../host/project.js");

async function fileSize(folder, name) {
  try {
    const entry = await folder.getEntry(name);
    if (!entry) return null;
    const meta = await entry.getMetadata();
    return meta && typeof meta.size === "number" ? meta.size : null;
  } catch (_) {
    return null;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Waits until `name` exists with the same non-zero size on two polls in a row, or throws.
async function waitForFile(folder, name, { timeoutMs = 10000, intervalMs = 20 } = {}) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeoutMs) {
    const size = await fileSize(folder, name);
    if (size && size === last) return size;
    last = size;
    await sleep(intervalMs);
  }
  throw new Error("Premiere did not finish saving the frame in time.");
}

function joinPath(folderPath, name) {
  const sep = folderPath.includes("\\") ? "\\" : "/";
  return folderPath.endsWith(sep) ? folderPath + name : folderPath + sep + name;
}

// Checks whether there are active (unmuted, enabled) video clips underneath `item` at `time`.
// When false, the background behind the Graphic is empty/black, so we only need to export ONE
// frame and NEVER disable the clip — completely eliminating screen flicker and undo steps.
async function hasClipsUnderneath(seq, item, time) {
  if (!seq || !item || typeof item.getTrackIndex !== "function") return true;
  try {
    const itemTrackIndex = await item.getTrackIndex();
    if (itemTrackIndex <= 0) return false;
    const atTicks = toTicks(time, "playhead");
    const trackCount = typeof seq.getVideoTrackCount === "function" ? await seq.getVideoTrackCount() : itemTrackIndex;
    const limit = Math.min(itemTrackIndex, trackCount);
    for (let t = 0; t < limit; t++) {
      const track = await seq.getVideoTrack(t);
      if (!track) continue;
      if (typeof track.isMuted === "function" && (await track.isMuted())) continue;
      if (typeof track.getTrackItems === "function") {
        const trackItems = await track.getTrackItems();
        for (const other of trackItems) {
          if (typeof other.isDisabled === "function" && (await other.isDisabled())) continue;
          const start = toTicks(await other.getStartTime(), "track item start");
          const end = toTicks(await other.getEndTime(), "track item end");
          if (atTicks >= start && atTicks < end) {
            return true;
          }
        }
      }
    }
    return false;
  } catch (_) {
    return true;
  }
}

async function deleteEntry(folder, name) {
  try {
    const entry = await folder.getEntry(name);
    if (entry && typeof entry.delete === "function") await entry.delete();
  } catch (_) {}
}

// The clip's drawn box at the playhead, `{left, top, right, bottom}` in sequence pixels (right
// and bottom exclusive), or null when it draws nothing there. Throws, with a sentence the
// status bar can show, when the playhead is not over the clip or a frame can't be saved.
async function measureDrawnBounds({ ppro, project, seq, item, frame, rpc, uxp, wait, keepDisabled = false }) {
  const time = await seq.getPlayerPosition();
  const at = toTicks(time, "playhead");
  const start = toTicks(await item.getStartTime(), "clip start");
  const end = toTicks(await item.getEndTime(), "clip end");
  if (at < start || at >= end) throw new Error("Move the playhead over it first.");
  // A clip that is already off would measure as "draws nothing", and the `finally` below would
  // switch it ON: never change a clip's on/off state the user set (isDisabled, api :732).
  if (await item.isDisabled()) throw new Error("it is switched off on the timeline (Ctrl+Z past an Align can do that). Switch it on first.");

  const folder = await uxp.storage.localFileSystem.getTemporaryFolder();
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const onName = `cutdeck-bounds-${stamp}-on.png`;
  const offName = `cutdeck-bounds-${stamp}-off.png`;
  const save = async (name) => {
    await ppro.Exporter.exportSequenceFrame(seq, time, name, folder.nativePath, frame.width, frame.height);
    await waitForFile(folder, name, wait);
  };

  const hasUnderneath = await hasClipsUnderneath(seq, item, time);
  let unhideAction = null;

  try {
    await save(onName);

    if (hasUnderneath) {
      runTransaction(project, "CutDeck: measure (hide clip)", (compound) => {
        compound.addAction(item.createSetDisabledAction(true));
      });
      let offSaved = false;
      try {
        await save(offName);
        offSaved = true;
      } finally {
        if (!offSaved || !keepDisabled) {
          runTransaction(project, "CutDeck: measure (show clip)", (compound) => {
            compound.addAction(item.createSetDisabledAction(false));
          });
        } else {
          unhideAction = (compound) => compound.addAction(item.createSetDisabledAction(false));
        }
      }
    }

    const payload = {
      type: "frame_bounds",
      on: joinPath(folder.nativePath, onName),
    };
    if (hasUnderneath) {
      payload.off = joinPath(folder.nativePath, offName);
    }

    const reply = await rpc(payload);
    console.log("CutDeck measured bounds", JSON.stringify({ at: String(at), folder: folder.nativePath, bounds: reply && reply.bounds, singleFrame: !hasUnderneath }));
    const bounds = reply ? reply.bounds : null;
    if (keepDisabled) {
      return { bounds, unhideAction };
    }
    return bounds;
  } finally {
    deleteEntry(folder, onName);
    if (hasUnderneath) deleteEntry(folder, offName);
  }
}

// In-memory bounds cache: prevents repeating the slow frame export + clip disable/enable on
// every subsequent alignment or anchor action. Dual WeakMap (object-reference) and bounded Map
// (track:start key) ensures 100% cache hits across UXP proxy wrapper instances with capped memory.
let boundsCache = new WeakMap();
const boundedCache = new Map();
const MAX_BOUNDED_ENTRIES = 50;

function getCachedBounds(item, scale = 100, rotation = 0, key = null, position = null) {
  let entry = null;
  if (item && typeof item === "object") entry = boundsCache.get(item);
  if (!entry && key && boundedCache.has(key)) {
    entry = boundedCache.get(key);
    if (entry && item && typeof item === "object") boundsCache.set(item, entry);
  }
  if (!entry) return null;
  if (Math.abs(scale - entry.scale) > 0.1 || Math.abs(rotation - entry.rotation) > 0.1) {
    if (item && typeof item === "object") boundsCache.delete(item);
    if (key) boundedCache.delete(key);
    return null;
  }
  if (position && entry.posX !== null && entry.posY !== null) {
    if (Math.abs(position.x - entry.posX) > 1e-4 || Math.abs(position.y - entry.posY) > 1e-4) {
      if (item && typeof item === "object") boundsCache.delete(item);
      if (key) boundedCache.delete(key);
      return null;
    }
  }
  return { left: entry.left, top: entry.top, right: entry.right, bottom: entry.bottom };
}

function setCachedBounds(item, bounds, scale = 100, rotation = 0, key = null, position = null) {
  if (!bounds) return;
  const entry = {
    left: Number(bounds.left),
    top: Number(bounds.top),
    right: Number(bounds.right),
    bottom: Number(bounds.bottom),
    scale: scale || 100,
    rotation: rotation || 0,
    posX: position && typeof position.x === "number" ? position.x : null,
    posY: position && typeof position.y === "number" ? position.y : null,
  };
  if (item && typeof item === "object") boundsCache.set(item, entry);
  if (key) {
    if (boundedCache.size >= MAX_BOUNDED_ENTRIES) {
      const oldest = boundedCache.keys().next().value;
      boundedCache.delete(oldest);
    }
    boundedCache.set(key, entry);
  }
}

function updateCachedBounds(item, dx = 0, dy = 0, key = null, newPos = null) {
  let entry = item && typeof item === "object" ? boundsCache.get(item) : null;
  if (!entry && key && boundedCache.has(key)) entry = boundedCache.get(key);
  if (!entry) return;
  entry.left += dx;
  entry.right += dx;
  entry.top += dy;
  entry.bottom += dy;
  if (newPos && typeof newPos.x === "number" && typeof newPos.y === "number") {
    entry.posX = newPos.x;
    entry.posY = newPos.y;
  }
}

function invalidateBounds(item, key = null) {
  if (item && typeof item === "object") boundsCache.delete(item);
  if (key) boundedCache.delete(key);
}

function clearBoundsCache() {
  boundsCache = new WeakMap();
  boundedCache.clear();
}

module.exports = {
  hasClipsUnderneath,
  measureDrawnBounds,
  waitForFile,
  getCachedBounds,
  setCachedBounds,
  updateCachedBounds,
  invalidateBounds,
  clearBoundsCache,
};

