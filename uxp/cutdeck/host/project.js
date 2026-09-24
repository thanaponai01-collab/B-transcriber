/* CutDeck host operations: active project, sequence, transactions, and bins.
   Single owner for Project.executeTransaction and Project.lockedAccess in the CutDeck panel.
   Layer: L4 (Host). Nothing here imports upward into features, UI, or composition. */

const CUTDECK_BIN_NAME = "CutDeck";
const ROUGH_CUTS_BIN_NAME = "Rough Cuts";
const SYNCED_BIN_NAME = "Synced";

// Resolves a folder-like item's createBinAction/getItems, casting to FolderItem when
// the plain methods aren't directly present.
function asBinLike(item) {
  if (!item) return null;
  if (typeof item.createBinAction === "function" && typeof item.getItems === "function") return item;
  try {
    const ppro = require("premierepro");
    if (ppro && ppro.FolderItem && typeof ppro.FolderItem.cast === "function") {
      const cast = ppro.FolderItem.cast(item);
      if (cast) return cast;
    }
  } catch (_) {}
  return item;
}

// Single owner for executeTransaction (issue #18 / move 4).
// Runs `build` inside project.executeTransaction, wrapped in project.lockedAccess
// when the host provides it, and throws whatever executeTransaction threw (or a generic
// error) when it reports failure.
function runTransaction(project, label, build) {
  if (!project) throw new Error("Open a Premiere project first.");
  let ok = false;
  let thrown = null;
  // Live 2026-09-24: identical transactions took 1 ms on one run and 28 s on another, cause not
  // yet caught. Any transaction over 0.5 s logs where its time went: lock wait / until our
  // callback runs / our callback / commit.
  const t0 = Date.now();
  let t1 = t0, t2 = t0, t3 = t0;
  const timedBuild = (compound) => {
    t2 = Date.now();
    try { return build(compound); } finally { t3 = Date.now(); }
  };
  const run = () => {
    t1 = Date.now();
    try {
      ok = project.executeTransaction(timedBuild, label);
    } catch (e) {
      thrown = e;
    }
  };
  if (typeof project.lockedAccess === "function") {
    project.lockedAccess(run);
  } else {
    run();
  }
  const t4 = Date.now();
  if (t4 - t0 > 500) {
    console.log(`CutDeck slow transaction "${label}" ${t4 - t0} ms: lock wait ${t1 - t0}, ` +
      `until callback ${(t2 > t1 ? t2 : t1) - t1}, callback ${t3 - t2}, commit ${t4 - (t3 > t1 ? t3 : t1)}`);
  }
  if (!ok) throw thrown || new Error(`Could not complete "${label}".`);
}

// Finds (or creates once via transaction) a named child bin directly under `parent`.
async function getOrCreateChildBin(project, parent, name) {
  const parentBin = asBinLike(parent);
  if (!parentBin || typeof parentBin.getItems !== "function") {
    throw new Error(`Cannot get items of parent bin to create "${name}".`);
  }
  const existingItems = (await parentBin.getItems()) || [];
  const existing = existingItems.find((item) => item.name === name);
  if (existing) return existing;

  try {
    runTransaction(project, `Create ${name} bin`, (compound) => {
      if (typeof parentBin.createBinAction !== "function") {
        throw new Error("createBinAction is not a function");
      }
      const action = parentBin.createBinAction(name, false);
      if (!action || !compound.addAction(action)) {
        throw new Error("addAction(createBin) returned false");
      }
    });
  } catch (err) {
    throw new Error(`Could not create the "${name}" bin in this project.`);
  }

  const afterItems = (await parentBin.getItems()) || [];
  const created = afterItems.find((item) => item.name === name);
  if (!created) {
    throw new Error(`"${name}" bin was created but could not be found afterward.`);
  }
  return created;
}

// Traverses or creates a hierarchy of bins from rootItem along pathArray (e.g. ["CutDeck", "ADJ & FX"]).
async function getOrCreateBin(project, pathArray) {
  if (!project) throw new Error("Open a Premiere project first.");
  if (!Array.isArray(pathArray)) {
    throw new Error("getOrCreateBin: pathArray must be an array of bin names");
  }
  let current = await project.getRootItem();
  for (const name of pathArray) {
    current = await getOrCreateChildBin(project, current, name);
  }
  return current;
}

// Canonical "Open a Premiere project first." / "Open a sequence first." resolution.
async function activeProjectAndSequence(ppro, { requireSequence = true, requireProject = true, sequenceErrorMessage } = {}) {
  const project = ppro && ppro.Project ? await ppro.Project.getActiveProject() : null;
  if (!project) {
    if (requireProject) throw new Error("Open a Premiere project first.");
    return { project: null, sequence: null };
  }
  const sequence = await project.getActiveSequence();
  if (!sequence && requireSequence) {
    throw new Error(sequenceErrorMessage || "Open a sequence first.");
  }
  return { project, sequence: sequence || null };
}

module.exports = {
  CUTDECK_BIN_NAME,
  ROUGH_CUTS_BIN_NAME,
  SYNCED_BIN_NAME,
  asBinLike,
  asBinLike,
  runTransaction,
  getOrCreateBin,
  activeProjectAndSequence,
};
