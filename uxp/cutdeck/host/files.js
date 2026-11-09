// host/files.js — waiting for a file Premiere writes asynchronously.
//
// Exporter.exportSequenceFrame resolves BEFORE the frame is on disk (PREMIERE_FACTS
// "exportSequenceFrame", live 2026-09-24), so callers poll the file until its size stops changing.
// APIs (reference/adobe/api/uxp.txt): uxp.storage.Folder.getEntry (:3034),
// Entry.getMetadata (:2989), EntryMetadata.size (:3004).

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

// Waits until `name` exists with the same non-zero size on `stablePolls` polls in a row and
// returns that size. Throws if that does not happen within `timeoutMs`.
async function waitForFile(folder, name, { timeoutMs = 10000, intervalMs = 20, stablePolls = 2 } = {}) {
  const t0 = Date.now();
  let last = null;
  let same = 0;
  while (Date.now() - t0 < timeoutMs) {
    const size = await fileSize(folder, name);
    same = size !== null && size === last ? same + 1 : 1;
    if (size !== null && same >= stablePolls) return size;
    last = size;
    await sleep(intervalMs);
  }
  throw new Error(`Premiere did not finish saving "${name}" in time.`);
}

module.exports = { fileSize, sleep, waitForFile };
