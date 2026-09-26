// transform/params.js — HOST DISCOVERY ONLY for the Transform & Align panel (Phase 1 of
// docs/research/cutdeck-transform-panel-plan.md). Finds the Motion component on a track item
// and reads its four semantic fields (position, scale, rotation, anchor) by the param indices
// this build was PROVEN to use — Part 1a of the plan, live Premiere runs (26.5.1) matched
// against Effect Controls' own pixel readout to sub-pixel accuracy:
//
//   index 0 Position       array[2], normalized to the SEQUENCE frame, independently per axis
//   index 1 Scale          number (percent), the uniform scale value
//   index 3 Uniform Scale  boolean (this build's ZString gives it no displayName — index only)
//   index 4 Rotation       number (degrees)
//   index 5 Anchor Point   array[2], normalized to the clip's SOURCE frame — NOT Position's
//                          space. Proven on a 1280x720 clip in a 1920x1080 sequence with both
//                          set to 100,200: Position read [0.0521, 0.1852] (÷1920x1080),
//                          Anchor Point read [0.078125, 0.2778] (÷1280x720). The first run
//                          missed this because its clips' sources matched the sequence.
//
// Matched by matchName ("AE.ADBE Motion"), never displayName — displayName is localized
// (effects.js's FIXED_EFFECT_DISPLAY_NAMES warning applies here too). Never guesses: a build
// where the chain, the component or a param does not resolve returns null for that piece, not
// a zero — turning that into "unavailable" is the panel's job, not this module's.
//
// No geometry (normalized-to-pixel conversion lives in transform/geometry.js, which is pure
// and does not touch premierepro) and no DOM.

const { unwrapKeyframeValue } = require("../host/components.js");

const MOTION_MATCH_NAME = "AE.ADBE Motion";

const PARAM_INDEX = {
  position: 0,
  scale: 1,
  scaleWidth: 2,
  uniformScale: 3,
  rotation: 4,
  anchorPoint: 5,
  // 6 Anti-flicker, then Crop Left/Top/Right/Bottom in percent (PREMIERE_FACTS "Motion param
  // indices"). Phase 5's rendered bounds need the crop; nothing else here reads it.
  cropLeft: 7,
  cropTop: 8,
  cropRight: 9,
  cropBottom: 10,
};

// In-memory component inspection cache per item: avoids traversing the component chain
// multiple times per poll cycle (previously 4x per item per tick).
let itemComponentCache = new WeakMap();

async function inspectComponents(item) {
  if (!item || typeof item.getComponentChain !== "function") return null;
  if (typeof item === "object" && itemComponentCache.has(item)) {
    return itemComponentCache.get(item);
  }
  let chain;
  try {
    chain = await item.getComponentChain();
  } catch (_) {
    return null;
  }
  if (!chain || typeof chain.getComponentCount !== "function") return null;
  const count = typeof chain.getComponentCount === "function" ? chain.getComponentCount() : 0;
  const comps = [];
  for (let i = 0; i < count; i++) {
    let component;
    try {
      component = chain.getComponentAtIndex(i);
    } catch (_) {
      continue;
    }
    if (!component) continue;
    let matchName = null;
    try {
      matchName = typeof component.getMatchName === "function" ? await component.getMatchName() : null;
    } catch (_) {
      continue;
    }
    comps.push({ component, matchName, index: i });
  }
  if (typeof item === "object") {
    itemComponentCache.set(item, comps);
  }
  return comps;
}

function clearComponentCache(item = null) {
  if (item && typeof item === "object") itemComponentCache.delete(item);
  else itemComponentCache = new WeakMap();
}

// Searches the item's component chain for the real Motion component. Never throws: a missing
// chain, a component that won't report its match name, or a host with no getComponentChain at
// all are all "not found", same as capabilityProbe.js's looksLikeTransformComponent scan.
async function findMotionComponent(item) {
  const comps = await inspectComponents(item);
  if (!comps) return null;
  const entry = comps.find((c) => c.matchName === MOTION_MATCH_NAME);
  return entry ? entry.component : null;
}

// Reads one param by index off an already-found component. Returns null when the param itself
// does not resolve, so one bad field never hides the others readTransform() reads alongside it.
async function readParamField(component, index) {
  if (!component || typeof component.getParam !== "function") return null;
  let param;
  try {
    param = component.getParam(index);
  } catch (_) {
    return null;
  }
  if (!param) return null;

  let isTimeVarying = false;
  try {
    isTimeVarying = typeof param.isTimeVarying === "function" ? await param.isTimeVarying() : false;
  } catch (_) {
    isTimeVarying = false;
  }

  // getStartValue() takes no TickTime — it sidesteps the clip-relative-vs-sequence-relative
  // ambiguity that isn't documented anywhere in Adobe's reference (effects.js standardized on
  // the same call for the same reason). For an animated param this is only its value AT the
  // start keyframe, which is exactly why isTimeVarying is reported alongside it: the plan's
  // "skip animated params with a visible explanation" rule depends on the caller checking it
  // before trusting `value`.
  if (typeof param.getStartValue !== "function") return { isTimeVarying, value: null };
  try {
    const keyframe = await param.getStartValue();
    return { isTimeVarying, value: unwrapKeyframeValue(keyframe) };
  } catch (_) {
    return { isTimeVarying, value: null };
  }
}

// Reads the Motion component's four semantic fields for `item`. Returns null when the item has
// no readable Motion component at all — the panel's "unavailable" case, per Phase 1's
// definition of done. Each field is independently null-able so one bad param doesn't take the
// other three down with it.
async function readTransform(item) {
  const component = await findMotionComponent(item);
  if (!component) return null;
  const [position, scale, scaleWidth, uniformScale, rotation, anchorPoint, cropLeft, cropTop, cropRight, cropBottom] =
    await Promise.all([
      readParamField(component, PARAM_INDEX.position),
      readParamField(component, PARAM_INDEX.scale),
      readParamField(component, PARAM_INDEX.scaleWidth),
      readParamField(component, PARAM_INDEX.uniformScale),
      readParamField(component, PARAM_INDEX.rotation),
      readParamField(component, PARAM_INDEX.anchorPoint),
      readParamField(component, PARAM_INDEX.cropLeft),
      readParamField(component, PARAM_INDEX.cropTop),
      readParamField(component, PARAM_INDEX.cropRight),
      readParamField(component, PARAM_INDEX.cropBottom),
    ]);
  return { position, scale, scaleWidth, uniformScale, rotation, anchorPoint, cropLeft, cropTop, cropRight, cropBottom };
}

// The sequence's own frame size, read the same dual-route way capabilityProbe.js and
// adjustmentLayer.js already do (SequenceSettings has no plain width/height fields — confirmed
// against the official class reference — it's getVideoFrameRect(): RectF). Needed to convert
// Position's normalized value into the pixel numbers Effect Controls displays (Anchor Point is
// normalized to the SOURCE frame instead — see readSourceFrameSize below);
// the conversion itself is pure math and lives in transform/geometry.js, not here.
async function readSequenceFrameSize(seq) {
  if (!seq) return null;
  try {
    if (typeof seq.getSettings === "function") {
      const settings = await seq.getSettings();
      if (settings && typeof settings.getVideoFrameRect === "function") {
        const rect = await settings.getVideoFrameRect();
        if (rect && rect.width && rect.height) return { width: rect.width, height: rect.height };
      }
    }
  } catch (_) {}
  try {
    if (typeof seq.getFrameSize === "function") {
      const rect = await seq.getFrameSize();
      if (rect && rect.width && rect.height) return { width: rect.width, height: rect.height };
    }
  } catch (_) {}
  return null;
}

// The sequence's pixel aspect ratio as a number. getVideoPixelAspectRatio() returns a string
// ("1:1", PREMIERE_FACTS "Sequence"), so parse "a:b"; a plain number string is accepted too.
// Returns null when unreadable, never an assumed 1.
async function readSequencePixelAspect(seq) {
  if (!seq || typeof seq.getSettings !== "function") return null;
  try {
    const settings = await seq.getSettings();
    if (!settings || typeof settings.getVideoPixelAspectRatio !== "function") return null;
    const text = String(await settings.getVideoPixelAspectRatio());
    const ratio = /^\s*([\d.]+)\s*:\s*([\d.]+)\s*$/.exec(text);
    const value = ratio ? Number(ratio[1]) / Number(ratio[2]) : Number(text);
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch (_) {
    return null;
  }
}

// Parses the Project panel's Video Info text — "1280 x 720 (1.0)" for video,
// "1920 x 1080 (1.0), Straight Alpha" for a PNG (Part 1a) — into the source frame size and its
// pixel aspect ratio. Trailing text after the "(par)" group is tolerated, not required. Returns
// null for anything that doesn't carry "W x H", never a guessed size. `pixelAspect` is null
// when the "(par)" group is missing, so a caller can refuse rather than assume square pixels.
function parseVideoInfoSize(text) {
  const match = /(\d+)\s*[x×]\s*(\d+)(?:\s*\(\s*([\d.]+)\s*\))?/.exec(String(text || ""));
  if (!match) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!width || !height) return null;
  const pixelAspect = match[3] === undefined ? null : Number(match[3]);
  return { width, height, pixelAspect: Number.isFinite(pixelAspect) ? pixelAspect : null };
}

const VIDEO_INFO_COLUMN_ID = "Column.Intrinsic.VideoInfo";

// The selected item's SOURCE frame size, which Anchor Point is normalized to. UXP has no
// width/height on ProjectItem, ClipProjectItem or FootageInterpretation; the only read path is
// Metadata.getProjectColumnsMetadata()'s Video Info column (Part 1a, proven on video and PNG).
// Open question the plan still carries: whether hiding that column in the Project panel
// removes it from this dump. If it does, this returns null and the panel shows Anchor Point
// as unavailable — the right failure, never a sequence-sized fallback. Never throws.
async function readSourceFrameSize(ppro, item) {
  if (!ppro || !ppro.Metadata || typeof ppro.Metadata.getProjectColumnsMetadata !== "function") return null;
  if (!item || typeof item.getProjectItem !== "function") return null;
  try {
    const projectItem = await item.getProjectItem();
    if (!projectItem) return null;
    const raw = await ppro.Metadata.getProjectColumnsMetadata(projectItem);
    const parsed = JSON.parse(typeof raw === "string" ? raw : String(raw));
    const columns = Array.isArray(parsed) ? parsed : (parsed && Array.isArray(parsed.columns) ? parsed.columns : []);
    const column = columns.find((c) => c && c.ColumnID === VIDEO_INFO_COLUMN_ID);
    return column ? parseVideoInfoSize(column.ColumnValue) : null;
  } catch (_) {
    return null;
  }
}

// A Premiere Graphic (text/shape layer) carries a "Vector Motion" component, matchName
// AE.ADBE Graphic Group (Check Transform on a Graphic, 2026-09-24).
const GRAPHIC_GROUP_MATCH_NAME = "AE.ADBE Graphic Group";

async function isGraphic(item) {
  const comps = await inspectComponents(item);
  if (!comps) return false;
  return comps.some((c) => c.matchName === GRAPHIC_GROUP_MATCH_NAME || c.matchName === TEXT_MATCH_NAME);
}

// The frame Anchor Point is normalized to. For footage and stills: the source frame (above). A
// Graphic has NO project item (Check Transform on a Graphic, 2026-09-24: "no project item"), so
// there is no source size to read; its canvas is the sequence frame (default Anchor [0.5, 0.5]
// with Position [0.5, 0.5] on the same run). That equivalence is the hypothesis the live check
// confirms: the panel's Anchor Point must read 960, 540 on a default Graphic in a 1080p sequence,
// same as Effect Controls. Anything else with no readable size still returns null.
async function readAnchorFrameSize(ppro, item, seq) {
  const source = await readSourceFrameSize(ppro, item);
  if (source) return source;
  if (!(await isGraphic(item))) return null;
  const frame = await readSequenceFrameSize(seq);
  return frame ? { width: frame.width, height: frame.height, pixelAspect: 1 } : null;
}

// A Graphic's own layers. Its Text layer (AE.ADBE Text, 22 params) carries the text's own
// Transform, the one Premiere's Properties panel shows under the text: [2] Position, [3] Scale,
// [4] Horizontal Scale, [5] Uniform, [6] Rotation, [8] Anchor Point (Check Transform on a
// Graphic, 2026-09-24). Position AND Anchor Point are both stored as fractions of the Graphic's
// canvas (the sequence frame): live [0.1120, 0.8700] = Properties 215.1, 939.6 and
// [0.1120, -0.0327] = 215.1, -35.4 in 1920x1080, and a written Position read back as written.
// Its Vector Motion (Graphic Group) has Motion's first six params in the same order.
const TEXT_MATCH_NAME = "AE.ADBE Text";
const TEXT_PARAM_INDEX = { position: 2, scale: 3, horizontalScale: 4, uniformScale: 5, rotation: 6, anchorPoint: 8 };
const KNOWN_GRAPHIC_COMPONENTS = new Set(["AE.ADBE Opacity", MOTION_MATCH_NAME, GRAPHIC_GROUP_MATCH_NAME, TEXT_MATCH_NAME]);

// Reads a Graphic's Vector Motion (scale, scale width, uniform, rotation) and every Text layer's
// Position param. `onlyText` is false when the chain holds anything else (a shape layer, an
// added effect), so a caller that moves text layers knows it would leave something behind.
async function readGraphicLayers(item) {
  const result = { vectorMotion: null, texts: [], onlyText: true, seen: [] };
  const comps = await inspectComponents(item);
  if (!comps) return null;
  for (const { component, matchName } of comps) {
    result.seen.push(matchName);
    if (!KNOWN_GRAPHIC_COMPONENTS.has(matchName)) result.onlyText = false;
    if (matchName === GRAPHIC_GROUP_MATCH_NAME) {
      const [position, scale, scaleWidth, uniformScale, rotation, anchorPoint] = await Promise.all([
        readParamField(component, PARAM_INDEX.position),
        readParamField(component, PARAM_INDEX.scale),
        readParamField(component, PARAM_INDEX.scaleWidth),
        readParamField(component, PARAM_INDEX.uniformScale),
        readParamField(component, PARAM_INDEX.rotation),
        readParamField(component, PARAM_INDEX.anchorPoint),
      ]);
      result.vectorMotion = { position, scale, scaleWidth, uniformScale, rotation, anchorPoint };
    } else if (matchName === TEXT_MATCH_NAME) {
      const getParam = (i) => { try { return component.getParam(i); } catch (_) { return null; } };
      const [position, scale, horizontalScale, uniformScale, rotation, anchorPoint] = await Promise.all([
        readParamField(component, TEXT_PARAM_INDEX.position),
        readParamField(component, TEXT_PARAM_INDEX.scale),
        readParamField(component, TEXT_PARAM_INDEX.horizontalScale),
        readParamField(component, TEXT_PARAM_INDEX.uniformScale),
        readParamField(component, TEXT_PARAM_INDEX.rotation),
        readParamField(component, TEXT_PARAM_INDEX.anchorPoint),
      ]);
      result.texts.push({
        param: getParam(TEXT_PARAM_INDEX.position),
        anchorParam: getParam(TEXT_PARAM_INDEX.anchorPoint),
        scaleParam: getParam(TEXT_PARAM_INDEX.scale),
        rotationParam: getParam(TEXT_PARAM_INDEX.rotation),
        position, scale, horizontalScale, uniformScale, rotation, anchorPoint,
      });
    }
  }
  if (result.texts.length === 0) result.onlyText = false;
  return result;
}

module.exports = {
  MOTION_MATCH_NAME,
  GRAPHIC_GROUP_MATCH_NAME,
  TEXT_MATCH_NAME,
  TEXT_PARAM_INDEX,
  readGraphicLayers,
  isGraphic,
  readAnchorFrameSize,
  PARAM_INDEX,
  findMotionComponent,
  readTransform,
  readSequenceFrameSize,
  readSequencePixelAspect,
  parseVideoInfoSize,
  readSourceFrameSize,
  clearComponentCache,
};
