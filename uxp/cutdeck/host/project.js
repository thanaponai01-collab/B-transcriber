/* CutDeck host operations: active project, sequence, transactions, and bins.
   Single owner for Project.executeTransaction and Project.lockedAccess in the CutDeck panel.
   Layer: L4 (Host). Nothing here imports upward into features, UI, or composition. */

const CUTDECK_BIN_NAME = "CutDeck";
const ROUGH_CUTS_BIN_NAME = "Rough Cuts";
const SYNCED_BIN_NAME = "Synced";

const { toTicks } = require("./ticks.js");

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

/* Live 2026-11-26 (PREMIERE_FACTS "Panel writes right after another command's commits"): a sequence
   or bin fetched about 150 ms after build_sequence committed threw "The script object is no longer
   valid." making its action. Nothing was committed, and a later fetch went through. `attempt` fetches
   its own handles and runs one transaction; on that error alone it runs again, later each time. */
const STALE_RETRIES = 3;
async function withFreshHandles(attempt) {
  for (let n = 1; ; n++) {
    try {
      return await attempt();
    } catch (e) {
      if (!/no longer valid/.test(String(e && e.message))) throw e;
      if (n > STALE_RETRIES) throw new Error(`${e.message} (in ${n} fresh fetches; nothing was changed by this step)`);
      console.log(`CutDeck: a handle went stale (${e.message}); fresh fetch ${n} of ${STALE_RETRIES}`);
      await new Promise((resolve) => setTimeout(resolve, 250 * n));
    }
  }
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

// The active project, or "Open a Premiere project first." (Project.getActiveProject, premierepro.txt:496).
async function activeProject(ppro) {
  const project = ppro && ppro.Project ? await ppro.Project.getActiveProject() : null;
  if (!project) throw new Error("Open a Premiere project first.");
  return project;
}

/* Every sequence of the project (Project.getSequences :503). Live 2026-11-26 a read held a null
   entry, as getTrackItems reads do (PREMIERE_FACTS "getTrackItems(...) null entries"): such a read is
   read again, and the last read's nulls are dropped. */
async function allSequences(project) {
  let list = [];
  for (let read = 1; read <= STALE_RETRIES + 1; read++) {
    if (read > 1) await new Promise((resolve) => setTimeout(resolve, 250 * (read - 1)));
    list = await project.getSequences();
    if (!list.includes(null)) return list;
  }
  return list.filter(Boolean);
}

// Every sequence whose name is exactly `name` (Sequence.name :612).
async function sequencesNamed(project, name) {
  return (await allSequences(project)).filter((s) => s.name === name);
}

// The one sequence named `name`; with no name, the active sequence (Project.getActiveSequence :497).
async function sequenceNamed(project, name) {
  if (!name) {
    const active = await project.getActiveSequence();
    if (!active) throw new Error("Open a sequence in Premiere first, or name one.");
    return active;
  }
  const found = await sequencesNamed(project, name);
  if (found.length !== 1) throw new Error(found.length ? `${found.length} sequences are named "${name}".` : `No sequence named "${name}".`);
  return found[0];
}

/* The sequence named `name` when a day template left empty copies of it beside the user's: the
   only one with that name, else the one with content (Sequence.getEndTime :596 past 0, as
   export_sequence picks). Anything else refuses: same-named sequences with content are told
   apart by nothing a caller can send. */
async function sequenceWithContent(project, name) {
  const named = await sequencesNamed(project, name);
  if (named.length === 1) return named[0];
  const full = [];
  for (const s of named) if (toTicks(await s.getEndTime()) > 0n) full.push(s);
  if (full.length !== 1) {
    throw new Error(named.length
      ? `${full.length} of the ${named.length} sequences named "${name}" have content; need exactly 1.`
      : `No sequence named "${name}".`);
  }
  return full[0];
}

// The first empty sequence named `name` (a day template's blank reel), or a refusal.
async function emptySequenceNamed(project, name) {
  const named = await sequencesNamed(project, name);
  for (const s of named) if (toTicks(await s.getEndTime()) === 0n) return s;
  throw new Error(`None of the ${named.length} sequences named "${name}" is empty.`);
}

async function projectAndSequenceNamed(ppro, name) {
  const project = await activeProject(ppro);
  return { project, sequence: await sequenceNamed(project, name) };
}

// Copies `source` in its own transaction `label` (Sequence.createCloneAction :586) and returns
// every sequence that was not there before, found by guid (Sequence.guid :610): the clone action
// hands back no handle to the copy. The caller decides how many copies it accepts.
async function cloneSequence(project, source, label) {
  const before = new Set((await allSequences(project)).map((s) => s.guid.toString()));
  runTransaction(project, label, (compound) => {
    if (!compound.addAction(source.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
  });
  return (await allSequences(project)).filter((s) => !before.has(s.guid.toString()));
}

// Opens `sequence` in the Timeline panel and makes it the active one (Project.openSequence :513,
// Project.setActiveSequence :518), returning what each call reported.
async function openAndActivate(project, sequence) {
  const opened = await project.openSequence(sequence);
  const activated = await project.setActiveSequence(sequence);
  return { opened, activated };
}

module.exports = {
  CUTDECK_BIN_NAME,
  ROUGH_CUTS_BIN_NAME,
  SYNCED_BIN_NAME,
  asBinLike,
  asBinLike,
  runTransaction,
  withFreshHandles,
  allSequences,
  getOrCreateBin,
  activeProjectAndSequence,
  activeProject,
  sequencesNamed,
  sequenceNamed,
  sequenceWithContent,
  emptySequenceNamed,
  projectAndSequenceNamed,
  cloneSequence,
  openAndActivate,
};
