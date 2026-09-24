// Adjustment Layer bin and asset management — Project panel operations, no DOM.
// Owned by uxp/cutdeck/timeline/adjustmentLayer.js and probes/capabilityProbe.js.
// See docs/arch-design-cutdeck-panel.md Move 9 (issue #56).

const {
  CUTDECK_BIN_NAME,
  asBinLike,
  runTransaction,
  getOrCreateBin,
} = require("../host/project.js");
const alProject = require("./alProject.js");

// Same top-level CutDeck bin rough cuts are filed under (CutDeck > Rough Cuts) for Cut/Sync
// results — deliberately the SAME name, so this is one shared folder tree in the Project
// panel, not a second one. ADJ_BIN_NAME is the canonical, unambiguous home for the
// Adjustment Layer: dropping it there means CutDeck finds it instantly on any sequence,
// with no name-guessing required.
const ADJ_BIN_NAME = "ADJ & FX";

// Finds (or creates once) Project panel > CutDeck > ADJ & FX.
async function getOrCreateAdjBin(project) {
  return getOrCreateBin(project, [CUTDECK_BIN_NAME, ADJ_BIN_NAME]);
}

// Importing a generated "CutDeck <W>x<H>.prproj" makes Premiere wrap its item in a bin named
// after the file (seen 2026-09-23). This moves each such AL up into ADJ & FX, then removes the
// wrapper only once a fresh read shows it EMPTY — two transactions, deliberately: removing a
// bin that still held the AL would delete the AL and every placement of it on the timeline.
// Only bins with exactly that name holding exactly one non-bin item are touched, so nothing
// the user made is ever moved or removed. Failure is logged, never thrown: the AL still works
// from inside the wrapper.
const IMPORT_WRAPPER_NAME = /^CutDeck (?:Color Matte )?\d+x\d+\.prproj$/;

async function listWrappers(bin) {
  const found = [];
  for (const it of (await bin.getItems()) || []) {
    if (it.type !== 2 || !IMPORT_WRAPPER_NAME.test(it.name || "")) continue;
    const wrapper = asBinLike(it);
    found.push({ item: it, wrapper, children: (await wrapper.getItems()) || [] });
  }
  return found;
}

async function flattenImportWrappers(project, adjBin) {
  const bin = asBinLike(adjBin);
  try {
    const toMove = (await listWrappers(bin))
      .filter((w) => w.children.length === 1 && w.children[0].type !== 2);
    if (!toMove.length) return 0;
    runTransaction(project, "CutDeck: move Adjustment Layers into ADJ & FX", (compound) => {
      for (const { wrapper, children } of toMove) {
        if (!compound.addAction(wrapper.createMoveItemAction(children[0], bin))) throw new Error("addAction(move) returned false");
      }
    });
    const empty = (await listWrappers(bin)).filter((w) => w.children.length === 0);
    if (empty.length) {
      runTransaction(project, "CutDeck: remove empty import folders", (compound) => {
        for (const { item } of empty) {
          if (!compound.addAction(bin.createRemoveItemAction(item))) throw new Error("addAction(remove) returned false");
        }
      });
    }
    return toMove.length;
  } catch (err) {
    console.log("CutDeck AL tidy: could not flatten import folders:", err);
    return 0;
  }
}

// Best-effort resolution auto-detection, tried before any naming convention. Premiere
// stores an item's own computed frame size in its internal "Column.Intrinsic.VideoInfo"
// project metadata field — the same data behind the Project panel's "Video Info" column, so
// it should exist even for a synthetic item like an Adjustment Layer, not just real media.
// Adobe's own community documents this field as unreliable ("works only half the time" —
// not every item populates it), so this is strictly a bonus: any failure (missing field,
// parse error, a build without ppro.Metadata or require("uxp").xmp) returns null and the
// caller falls through to name matching, unchanged.
async function detectResolutionFromMetadata(projectItem, ppro) {
  try {
    if (!projectItem || !ppro || !ppro.Metadata || typeof ppro.Metadata.getProjectMetadata !== "function") return null;
    const xmpStr = await ppro.Metadata.getProjectMetadata(projectItem);
    if (!xmpStr) return null;
    const uxpXmp = require("uxp").xmp;
    if (!uxpXmp || typeof uxpXmp.XMPMeta !== "function") return null;
    const xmp = new uxpXmp.XMPMeta(xmpStr);
    const prop = xmp.getProperty(
      "http://ns.adobe.com/premierePrivateProjectMetaData/1.0/",
      "Column.Intrinsic.VideoInfo"
    );
    const raw = prop && prop.value ? String(prop.value) : "";
    if (!raw) return null;
    // Observed format is space-separated with the numbers at either end (e.g.
    // "1920 x 1080" per the field's own documented example) — pull every number out and
    // take the first/last rather than assume exact token positions.
    const numbers = raw.match(/\d+/g);
    if (!numbers || numbers.length < 2) return null;
    const width = parseInt(numbers[0], 10);
    const height = parseInt(numbers[numbers.length - 1], 10);
    if (!width || !height) return null;
    return { width, height };
  } catch (_) {
    return null;
  }
}

// Picks the right Adjustment Layer when more than one sits in the same folder. Tries
// Premiere's own metadata first (exact match, no naming needed when it works); falls back to
// matching by name (e.g. "1920x1080", "AL 1080x1920") when metadata isn't available — so a
// same-size placement needs no scaling at all either way, Scale stays the proven-working 100%.
async function pickBestCandidate(candidates, targetWidth, targetHeight, seq, ppro) {
  if (!candidates || candidates.length === 0) return null;
  if (targetWidth && targetHeight) {
    for (const cand of candidates) {
      const detected = await detectResolutionFromMetadata(cand, ppro);
      if (detected && detected.width === targetWidth && detected.height === targetHeight) {
        return cand;
      }
    }
    // Width must appear BEFORE height with a short separator ("x", "×", "-", " ", or
    // nothing) between them — a plain "does this substring appear anywhere" check (the
    // original version of this) matched "1920x1080" against a 1080x1920 target too, since
    // both numbers are present, just transposed. Order matters.
    const pattern = new RegExp(`${targetWidth}\\D{0,3}${targetHeight}`);
    for (const cand of candidates) {
      if (pattern.test(cand.name || "")) return cand;
    }
    // Size known but nothing matches: return none, so placement creates a correctly sized AL
    // (createAdjustmentLayerForSequence) instead of reusing another size's. Proven needed
    // 2026-09-23: a 1920x1080 sequence got the 1080x1920 AL from the fallbacks below.
    return null;
  }
  if (seq && seq.name) {
    const sName = seq.name.toLowerCase();
    for (const cand of candidates) {
      if ((cand.name || "").toLowerCase().indexOf(sName) !== -1) return cand;
    }
  }
  return candidates[0];
}

// Find adjustment layer in project panel or active timeline, matching active sequence dimensions and fps
async function findAdjustmentLayerItem(project, seq, ppro) {
  if (!project || typeof project.getRootItem !== "function") return null;
  const root = await project.getRootItem();
  if (!root) return null;

  let targetWidth = null;
  let targetHeight = null;
  try {
    if (seq && typeof seq.getSettings === "function") {
      // SequenceSettings has no plain videoFrameWidth/videoFrameHeight fields (confirmed
      // against the official class reference) — it's getVideoFrameRect(): RectF, and RectF
      // is the plain {width, height} struct.
      const st = await seq.getSettings();
      const rect = st && typeof st.getVideoFrameRect === "function" ? await st.getVideoFrameRect() : null;
      if (rect && rect.width && rect.height) {
        targetWidth = rect.width;
        targetHeight = rect.height;
      }
    }
  } catch (_) {}

  // Canonical home: Project panel > CutDeck > ADJ & FX. Ensured to exist (created if
  // missing) so there is always one unambiguous, always-findable place for the Adjustment
  // Layer(s) — no depending on it already being on some other sequence's timeline. One AL in
  // here just works. Several (one per resolution you actually use — e.g. "1920x1080",
  // "1080x1920") get matched to the active sequence by name — see pickBestCandidate.
  try {
    const adjBin = await getOrCreateAdjBin(project);
    await flattenImportWrappers(project, adjBin);
    const items = (await asBinLike(adjBin).getItems()) || [];
    const candidates = items.filter((it) => it.type !== 2 && it.name);
    const picked = await pickBestCandidate(candidates, targetWidth, targetHeight, seq, ppro);
    if (picked) return picked;
  } catch (_) {}

  // Legacy fallback: search the whole project (an AL named/placed before ADJ & FX existed)
  async function getFolderChildren(folder) {
    if (typeof folder.getItems === "function") {
      try { return await folder.getItems(); } catch (_) {}
    }
    if (ppro && ppro.FolderItem && typeof ppro.FolderItem.cast === "function") {
      try {
        const bin = ppro.FolderItem.cast(folder);
        if (bin && typeof bin.getItems === "function") {
          return await bin.getItems();
        }
      } catch (_) {}
    }
    return [];
  }

  const allCandidates = [];

  async function search(folder) {
    const items = await getFolderChildren(folder);
    if (!items || !items.length) return;

    for (const it of items) {
      // In Premiere Pro UXP, it.type === 2 is a BIN (Folder)
      const isBin = it.type === 2 || typeof it.getItems === "function" ||
        (ppro && ppro.FolderItem && typeof ppro.FolderItem.cast === "function" && ppro.FolderItem.cast(it) !== null);

      if (isBin) {
        // Recurse into the bin (e.g. "07. Adjustment Layer") — NEVER return the bin itself!
        await search(it);
        continue;
      }

      // Must be a clip item (type !== 2) whose name contains adjustment
      if (it.type !== 2 && it.name) {
        const lower = it.name.toLowerCase();
        if (
          lower.indexOf("adjustment layer") !== -1 ||
          lower.indexOf("adjustment") !== -1 ||
          lower.indexOf("adj_") === 0 ||
          lower.indexOf("al_") === 0
        ) {
          allCandidates.push(it);
        }
      }
    }
  }

  await search(root);

  return await pickBestCandidate(allCandidates, targetWidth, targetHeight, seq, ppro);
}

// Writes bytes to the plugin's temporary folder and returns the native path.
async function writeTempFile(fileName, bytes) {
  const uxp = require("uxp");
  const folder = await uxp.storage.localFileSystem.getTemporaryFolder();
  const file = await folder.createFile(fileName, { overwrite: true });
  await file.write(bytes.buffer, { format: uxp.storage.formats.binary });
  return file.nativePath;
}

// The API has no createAdjustmentLayer, so this generates a one-AL .prproj at the sequence's
// exact size (timeline/alProject.js) and imports it into CutDeck > ADJ & FX. Returns the
// imported project item, or throws saying what went wrong. Premiere may wrap an imported
// project in a bin named after the file, so one level of sub-bins is searched too.
async function createAdjustmentLayerForSequence(project, width, height, ticksPerFrame) {
  const w = Math.round(Number(width));
  const h = Math.round(Number(height));
  const { bytes, name } = alProject.buildAdjustmentLayerPrproj({
    width: w,
    height: h,
    ticksPerFrame: Number.isSafeInteger(ticksPerFrame) ? ticksPerFrame : null,
  });
  const filePath = await writeTempFile(`CutDeck ${w}x${h}.prproj`, bytes);
  const adjBin = asBinLike(await getOrCreateAdjBin(project));
  const imported = await project.importFiles([filePath], true, adjBin, false);
  console.log(`CutDeck AL create: importFiles(${filePath}) returned`, imported);

  await flattenImportWrappers(project, adjBin);
  const items = (await adjBin.getItems()) || [];
  const direct = items.find((it) => it.type !== 2 && it.name === name);
  if (direct) return direct;
  for (const it of items) {
    if (it.type !== 2) continue;
    const children = (await asBinLike(it).getItems()) || [];
    const nested = children.find((c) => c.type !== 2 && c.name === name);
    if (nested) {
      console.log(`CutDeck AL create: "${name}" landed inside the "${it.name}" bin`);
      return nested;
    }
  }
  throw new Error(
    `Tried to create "${name}" automatically (import returned ${imported}), but it did not appear in ` +
    `CutDeck > ${ADJ_BIN_NAME}. Create one by hand instead: File > New Item > Adjustment Layer at ` +
    `${w}x${h}, name it "${w}x${h}", and drag it into that folder.`
  );
}

let cmProject;
function getCmProject() {
  if (!cmProject) cmProject = require("./cmProject.js");
  return cmProject;
}

// Find Color Matte in project panel or active timeline, matching active sequence dimensions
async function findColorMatteItem(project, seq, ppro) {
  if (!project || typeof project.getRootItem !== "function") return null;
  const root = await project.getRootItem();
  if (!root) return null;

  let targetWidth = null;
  let targetHeight = null;
  try {
    if (seq && typeof seq.getSettings === "function") {
      const st = await seq.getSettings();
      const rect = st && typeof st.getVideoFrameRect === "function" ? await st.getVideoFrameRect() : null;
      if (rect && rect.width && rect.height) {
        targetWidth = rect.width;
        targetHeight = rect.height;
      }
    }
  } catch (_) {}

  // 1. Canonical home: Project panel > CutDeck > ADJ & FX
  try {
    const adjBin = await getOrCreateAdjBin(project);
    await flattenImportWrappers(project, adjBin);
    const items = (await asBinLike(adjBin).getItems()) || [];
    const candidates = items.filter((it) => it.type !== 2 && it.name && (
      it.name.toLowerCase().includes("matte") || it.name.toLowerCase().includes("color")
    ));
    const picked = await pickBestCandidate(candidates, targetWidth, targetHeight, seq, ppro);
    if (picked) return picked;
  } catch (_) {}

  // 2. Fallback: search the whole project
  async function getFolderChildren(folder) {
    if (typeof folder.getItems === "function") {
      try { return await folder.getItems(); } catch (_) {}
    }
    if (ppro && ppro.FolderItem && typeof ppro.FolderItem.cast === "function") {
      try {
        const bin = ppro.FolderItem.cast(folder);
        if (bin && typeof bin.getItems === "function") {
          return await bin.getItems();
        }
      } catch (_) {}
    }
    return [];
  }

  const allCandidates = [];
  async function search(folder) {
    const items = await getFolderChildren(folder);
    if (!items || !items.length) return;

    for (const it of items) {
      const isBin = it.type === 2 || typeof it.getItems === "function" ||
        (ppro && ppro.FolderItem && typeof ppro.FolderItem.cast === "function" && ppro.FolderItem.cast(it) !== null);

      if (isBin) {
        await search(it);
        continue;
      }

      if (it.type !== 2 && it.name) {
        const lower = it.name.toLowerCase();
        if (
          lower.includes("color matte") ||
          lower.includes("matte") ||
          lower.startsWith("cm_") ||
          lower.startsWith("matte_")
        ) {
          allCandidates.push(it);
        }
      }
    }
  }

  await search(root);
  return await pickBestCandidate(allCandidates, targetWidth, targetHeight, seq, ppro);
}

// Automatically creates a Color Matte .prproj at the sequence's exact size and imports it into CutDeck > ADJ & FX
async function createColorMatteForSequence(project, width, height, ticksPerFrame) {
  const w = Math.round(Number(width));
  const h = Math.round(Number(height));
  const { bytes, name } = getCmProject().buildColorMattePrproj({
    width: w,
    height: h,
    ticksPerFrame: Number.isSafeInteger(ticksPerFrame) ? ticksPerFrame : null,
  });
  const filePath = await writeTempFile(`CutDeck Color Matte ${w}x${h}.prproj`, bytes);
  const adjBin = asBinLike(await getOrCreateAdjBin(project));
  const imported = await project.importFiles([filePath], true, adjBin, false);
  console.log(`CutDeck Color Matte create: importFiles(${filePath}) returned`, imported);

  await flattenImportWrappers(project, adjBin);
  const items = (await adjBin.getItems()) || [];
  const direct = items.find((it) => it.type !== 2 && it.name === name);
  if (direct) return direct;
  for (const it of items) {
    if (it.type !== 2) continue;
    const children = (await asBinLike(it).getItems()) || [];
    const nested = children.find((c) => c.type !== 2 && c.name === name);
    if (nested) {
      console.log(`CutDeck Color Matte create: "${name}" landed inside the "${it.name}" bin`);
      return nested;
    }
  }
  throw new Error(
    `Tried to create "${name}" automatically (import returned ${imported}), but it did not appear in ` +
    `CutDeck > ${ADJ_BIN_NAME}. Create one by hand instead: File > New Item > Color Matte at ` +
    `${w}x${h}, name it "${w}x${h}", and drag it into that folder.`
  );
}

module.exports = {
  ADJ_BIN_NAME,
  getOrCreateAdjBin,
  flattenImportWrappers,
  detectResolutionFromMetadata,
  pickBestCandidate,
  findAdjustmentLayerItem,
  findColorMatteItem,
  writeTempFile,
  createAdjustmentLayerForSequence,
  createColorMatteForSequence,
};
