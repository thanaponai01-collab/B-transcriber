// host/files.js — waiting for a file Premiere writes asynchronously.
//
// Exporter.exportSequenceFrame resolves BEFORE the frame is on disk (PREMIERE_FACTS
// "exportSequenceFrame", live 2026-09-24), so callers poll the file until its size stops changing.
// APIs (reference/adobe/api/uxp.txt): uxp.storage.Folder.getEntry (:3034),
// Entry.getMetadata (:2989), EntryMetadata.size (:3004), require('fs') open / read / close (:462-468).

// Size in bytes of `name` in `folder`, or null while it is missing or still empty.
async function fileSize(folder, name) {
  try {
    if (!folder || typeof folder.getEntry !== "function") return null;
    const entry = await folder.getEntry(name);
    if (!entry) return null;
    const meta = await entry.getMetadata();
    return meta && typeof meta.size === "number" && meta.size > 0 ? meta.size : null;
  } catch (_) {
    return null; // getEntry throws while the file does not exist yet
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// A PNG ends with an empty IEND chunk: "IEND" and its CRC. Premiere writes a frame over ~0.1 s, so
// these bytes, not a size that held for a few polls, say the file is complete.
const PNG_END = [0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82];

// True once the `size`-byte file at `path` ends with PNG_END. Reads only those 8 bytes; a read
// that throws counts as not yet.
async function pngWritten(path, size) {
  const fs = require("fs");
  let fd = null;
  try {
    fd = await fs.open(path, "r");
    const buffer = new ArrayBuffer(8);
    const { bytesRead } = await fs.read(fd, buffer, 0, 8, size - 8);
    const tail = new Uint8Array(buffer);
    return bytesRead === 8 && PNG_END.every((b, i) => tail[i] === b);
  } catch (_) {
    return false;
  } finally {
    if (fd !== null) {
      try { await fs.close(fd); } catch (_) { /* the answer is already known */ }
    }
  }
}

// Waits until `name` exists with the same non-zero size on `stablePolls` polls in a row, and
// `done(size)` holds when given, and returns that size. Throws if that does not happen within
// `timeoutMs`.
async function waitForFile(folder, name, { timeoutMs = 10000, intervalMs = 20, stablePolls = 2, done = null } = {}) {
  const t0 = Date.now();
  let last = null;
  let same = 0;
  while (Date.now() - t0 < timeoutMs) {
    const size = await fileSize(folder, name);
    same = size !== null && size === last ? same + 1 : 1;
    if (size !== null && same >= stablePolls && (!done || (await done(size)))) return size;
    last = size;
    await sleep(intervalMs);
  }
  throw new Error(`Premiere did not finish saving "${name}" in time.`);
}

module.exports = { fileSize, pngWritten, sleep, waitForFile };
