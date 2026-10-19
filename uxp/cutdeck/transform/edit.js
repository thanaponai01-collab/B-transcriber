// transform/edit.js — reads a clip's transform model and performs every write a Transform/Align
// action makes: a typed field, the nine-point anchor, align to frame or selection, distribute
// (docs/research/cutdeck-transform-panel-plan.md). Moved out of features/align.js so the agent
// driver reaches it without importing a feature.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const trackItems = require("../host/trackItems.js");
const transformParams = require("./params.js");
const transformGeometry = require("./geometry.js");
const transformApply = require("./apply.js");
const frameBounds = require("./frameBounds.js");
const { readSnapshot } = require("./snapshot.js");
const { activeProjectAndSequence, runTransaction } = require("../host/project.js");

function describeField(entry, isPoint, frameSize) {
  if (!entry) return { known: false };
  if (entry.isTimeVarying) return { known: true, animated: true };
  if (isPoint) {
    const px = frameSize
      ? transformGeometry.normalizedToFramePixels(entry.value, frameSize.width, frameSize.height)
      : null;
    return px ? { known: true, animated: false, x: px.x, y: px.y } : { known: false };
  }
  return typeof entry.value === "number" || typeof entry.value === "boolean"
    ? { known: true, animated: false, value: entry.value }
    : { known: false };
}

// The rows Effect Controls lists under Motion and Opacity beyond the four the panel always had.
// They are the clip's own Motion/Opacity values, a Graphic included (its text layers' transform
// only replaces Position/Scale/Rotation/Anchor). Scale Width is greyed while Uniform Scale is
// on, as in Effect Controls.
function effectControlsExtras(transform) {
  const t = transform || {};
  const extras = {
    uniformScale: describeField(t.uniformScale, false),
    scaleWidth: describeField(t.scaleWidth, false),
    antiFlicker: describeField(t.antiFlicker, false),
    cropLeft: describeField(t.cropLeft, false),
    cropTop: describeField(t.cropTop, false),
    cropRight: describeField(t.cropRight, false),
    cropBottom: describeField(t.cropBottom, false),
    opacity: describeField(t.opacity, false),
  };
  if (extras.uniformScale.value !== false && extras.scaleWidth.known) extras.scaleWidth.locked = true;
  return extras;
}

function textTarget(layers) {
  return Boolean(layers && layers.onlyText && layers.texts && layers.texts.length > 0);
}

// A text-only Graphic's rows come from its text layer's Transform, the group Effect Controls
// shows under Text > Transform (live 2026-10-16: Position 494.9, 852.0 · Scale 100 · Horizontal
// Scale 100 greyed · Uniform Scale · Rotation 0.0 · Anchor Point 112.1, -68.5). Every other row
// (Anti-flicker, Crop, Opacity) is the clip's own Motion/Opacity, as in Effect Controls' Video
// section.
function textFields(text, frameSize, anchorFrame, transform) {
  const fields = {
    position: describeField(text.position, true, frameSize),
    scale: describeField(text.scale, false),
    rotation: describeField(text.rotation, false),
    anchor: describeField(text.anchorPoint, true, anchorFrame),
    ...effectControlsExtras(transform),
    uniformScale: describeField(text.uniformScale, false),
    scaleWidth: describeField(text.horizontalScale, false),
  };
  if (fields.uniformScale.value !== false && fields.scaleWidth.known) fields.scaleWidth.locked = true;
  return fields;
}

// Every value that moves where a clip is drawn: Motion, Vector Motion and each text layer. A
// cached text box (transform/frameBounds.js) is good only while this string is unchanged, so a
// change made in Effect Controls (Motion Scale, a text Anchor Point...) re-measures the text.
const SIGNATURE_MOTION = ["position", "anchorPoint", "scale", "scaleWidth", "uniformScale", "rotation",
  "cropLeft", "cropTop", "cropRight", "cropBottom"];
const SIGNATURE_LAYER = ["position", "anchorPoint", "scale", "scaleWidth", "horizontalScale", "uniformScale", "rotation"];
function boundsSignature(clip) {
  const pick = (entry) => {
    if (!entry) return null;
    if (entry.isTimeVarying) return "animated";
    const point = transformGeometry.pointXY(entry.value);
    if (point) return [point.x, point.y];
    return entry.value === undefined ? null : entry.value;
  };
  const values = (source, names) => (source ? names.map((n) => pick(source[n])) : null);
  const layers = clip.layers || {};
  return JSON.stringify([
    values(clip.transform, SIGNATURE_MOTION),
    values(layers.vectorMotion, SIGNATURE_LAYER),
    (layers.texts || []).map((t) => values(t, SIGNATURE_LAYER)),
  ]);
}

function targetTexts(layers, layerTarget) {
  if (layerTarget === "all") return layers.texts.slice();
  const i = typeof layerTarget === "number" && layerTarget >= 0 && layerTarget < layers.texts.length ? layerTarget : 0;
  return [layers.texts[i]];
}

// The one text layer an edit measures and moves: its index when the panel targets one layer of a
// text-only Graphic with several (the Text 1 / Text 2 switcher), else null, and the Graphic is
// measured and moved as a whole.
function measuredLayer(layers, layerTarget) {
  return layers && layers.onlyText && layers.texts.length > 1 && Number.isInteger(layerTarget)
    && layerTarget >= 0 && layerTarget < layers.texts.length ? layerTarget : null;
}

// A text layer's cached box lives under its own key, never the item's (that is the whole Graphic).
const layerKey = (clip, index) => (clip.key ? `${clip.key}#text${index}` : null);

// Where a Graphic (index null) or one of its text layers is drawn, sequence px: the cached box
// while the clip's boundsSignature holds, else measured (one text layer with the others hidden,
// frameBounds.measureTextLayer) and cached. Null when it draws nothing at the playhead; throws
// the reason when it can't be measured.
async function drawnBox(project, seq, seqFrame, clip, measure, index = null) {
  const isText = Boolean(clip.layers && clip.layers.texts && clip.layers.texts.length > 0);
  const item = index === null ? clip.item : null;
  const key = index === null ? clip.key : layerKey(clip, index);
  const signature = boundsSignature(clip);
  const cached = isText ? frameBounds.getCachedBounds(item, key, signature) : null;
  if (cached) return cached;
  if (!measure) throw new Error("a Graphic needs its text measured, which isn't available here.");
  const measureOne = () => measure({ project, seq, item: clip.item, frame: seqFrame });
  const measured = index === null
    ? await measureOne()
    : await frameBounds.measureTextLayer(project, clip.layers.texts, index, measureOne);
  const box = measured && measured.bounds ? measured.bounds : (measured && typeof measured.left === "number" ? measured : null);
  if (box && isText) frameBounds.setCachedBounds(item, box, key, signature);
  return box;
}

// After CutDeck's own write: re-read the clips and carry each cached text box along (moved by
// dx, dy) under its new signature. `updates` = [{ item, key, dx, dy, clipKey? }]: `clipKey` is the
// clip's own key when `key` is one of its text layers' (layerKey).
async function shiftCachedBounds(ppro, seq, updates) {
  if (!updates.length) return;
  const fresh = await readSnapshot(ppro, { seq, forceRefresh: true });
  for (const u of updates) {
    const now = fresh.clips.find((c) => c.key === (u.clipKey || u.key));
    if (now) frameBounds.updateCachedBounds(u.item, u.dx, u.dy, u.key, boundsSignature(now));
    else frameBounds.invalidateBounds(u.item, u.key);
  }
}

async function readAlignTransform(seqOrSnapshot, ppro = null, options = {}) {
  const layerTarget = options && options.layerTarget !== undefined ? options.layerTarget : 0;
  let snap;
  if (seqOrSnapshot && seqOrSnapshot.clips !== undefined && seqOrSnapshot.items !== undefined) {
    snap = seqOrSnapshot;
  } else {
    snap = await readSnapshot(ppro, { seq: seqOrSnapshot });
  }

  if (!snap.sequence) return { clipName: null, available: false, reason: "No sequence open.", fields: null };

  const items = snap.items;
  if (items.length === 0) {
    return { clipName: null, available: false, reason: "Select a clip on the timeline.", fields: null };
  }

  if (snap.clips.length === 0) {
    const rawFirst = items[0];
    const rawName = snap.firstItemName || (await trackItems.trackItemName(rawFirst, "(unnamed)"));
    const clipName = rawName + (items.length > 1 ? ` (+${items.length - 1} more selected)` : "");
    return { clipName, available: false, reason: "This item has no readable Transform.", fields: null };
  }

  const primaryClip = snap.clips[0];
  const item = primaryClip.item;
  const clipName = primaryClip.name + (items.length > 1 ? ` (+${items.length - 1} more selected)` : "");
  const seq = snap.sequence;
  const frameSize = snap.seqFrame;
  let anchorFrame = primaryClip.anchorFrame;
  if (!anchorFrame) {
    anchorFrame = await transformParams.readAnchorFrameSize(ppro, item, seq);
  }

  // B4: Check if unmeasured Graphic text has playhead outside clip
  if (primaryClip.isGraphic && textTarget(primaryClip.layers)) {
    const cached = frameBounds.getCachedBounds(primaryClip.item, primaryClip.key, boundsSignature(primaryClip));
    if (!cached && primaryClip.playheadOver === false) {
      const texts = primaryClip.layers.texts;
      const textLayers = texts.length > 1
        ? texts.map((_, i) => ({ index: i, label: `Text ${i + 1}` }))
        : null;
      const targetIdx = (layerTarget === "all" || typeof layerTarget !== "number" || layerTarget < 0 || layerTarget >= texts.length) ? 0 : layerTarget;
      const activeText = texts[targetIdx];
      return {
        clipName,
        available: true,
        reason: null,
        needPlayheadOver: true,
        tooltip: "Move the playhead over it first to measure text bounds.",
        layer: "text",
        fields: textFields(activeText, frameSize, anchorFrame, primaryClip.transform),
        textLayers,
        activeLayerTarget: layerTarget,
      };
    }
  }

  // B1: A Graphic with ONLY text: show text layer transform. Otherwise (e.g. text+shape), Motion.
  if (primaryClip.isGraphic && textTarget(primaryClip.layers)) {
    const texts = primaryClip.layers.texts;
    const textLayers = texts.length > 1
      ? texts.map((_, i) => ({ index: i, label: `Text ${i + 1}` }))
      : null;

    const targetIdx = (layerTarget === "all" || typeof layerTarget !== "number" || layerTarget < 0 || layerTarget >= texts.length) ? 0 : layerTarget;
    const activeText = texts[targetIdx];
    return {
      clipName,
      available: true,
      reason: null,
      layer: "text",
      fields: textFields(activeText, frameSize, anchorFrame, primaryClip.transform),
      textLayers,
      activeLayerTarget: layerTarget,
    };
  }

  const transform = primaryClip.transform;
  const fields = {
    position: describeField(transform.position, true, frameSize),
    scale: describeField(transform.scale, false, frameSize),
    rotation: describeField(transform.rotation, false, frameSize),
    anchor: describeField(transform.anchorPoint, true, anchorFrame),
    ...effectControlsExtras(transform),
  };
  return { clipName, available: true, reason: null, fields };
}

async function readAlignState(ppro, options = {}) {
  const snap = await readSnapshot(ppro, { forceRefresh: !!options.forceRefresh });
  const seq = snap.sequence;
  return {
    sequence: seq ? { name: seq.name || "(unnamed)" } : null,
    transform: await readAlignTransform(snap, ppro, options),
  };
}

// --- edits ---------------------------------------------------------------------------------

const staticValue = (entry) => (entry && !entry.isTimeVarying && entry.value !== null && entry.value !== undefined ? entry.value : null);

// Every selected item that has a Motion effect, with its name and transform read.
async function readSelectedMotionClips(seq, ppro) {
  const items = await trackItems.getSelectedTrackItems(seq, ppro);
  const clips = [];
  for (const item of items) {
    const transform = await transformParams.readTransform(item);
    if (transform) {
      let key = null;
      try {
        const start = typeof item.getStartTime === "function" ? (await item.getStartTime()).ticks : null;
        const track = typeof item.getTrackIndex === "function" ? await item.getTrackIndex() : null;
        if (start !== null && track !== null) key = `${track}:${start}`;
      } catch (_) {}
      clips.push({ item, key, transform, name: await trackItems.trackItemName(item, "(unnamed)") });
    }
  }
  return clips;
}

const MODEL_FIELDS = ["position", "anchorPoint", "scale", "scaleWidth", "rotation", "uniformScale",
  "cropLeft", "cropTop", "cropRight", "cropBottom"];

// One clip in transform/geometry.js's render model, or `{ skip }` saying in plain words why it
// can't be moved safely. Keyframed values are never flattened, and nothing is assumed about a
// value or a frame size the panel couldn't read.
async function clipModel(ppro, clip, seqFrame, seqAspect, seq) {
  const t = clip.transform;
  if (MODEL_FIELDS.some((f) => t[f] && t[f].isTimeVarying)) {
    return { skip: `"${clip.name}" has keyframed Motion values, left alone.` };
  }
  const position = transformGeometry.pointXY(staticValue(t.position));
  const anchor = transformGeometry.pointXY(staticValue(t.anchorPoint));
  const scale = staticValue(t.scale);
  const rotation = staticValue(t.rotation);
  const uniform = staticValue(t.uniformScale);
  // Uniform Scale off: index 1 is the height, index 2 the width.
  const scaleWidth = uniform === false ? staticValue(t.scaleWidth) : scale;
  const crop = { left: staticValue(t.cropLeft), top: staticValue(t.cropTop), right: staticValue(t.cropRight), bottom: staticValue(t.cropBottom) };
  if (!position || !anchor || typeof scale !== "number" || typeof rotation !== "number" || typeof uniform !== "boolean"
    || typeof scaleWidth !== "number" || Object.values(crop).some((v) => typeof v !== "number")) {
    return { skip: `"${clip.name}": could not read all of its Motion values.` };
  }
  const source = clip.anchorFrame !== undefined && clip.anchorFrame !== null
    ? clip.anchorFrame
    : await transformParams.readAnchorFrameSize(ppro, clip.item, seq);
  if (!source) return { skip: `"${clip.name}": could not read its source frame size.` };
  if (source.pixelAspect !== 1 || seqAspect !== 1) {
    return { skip: `"${clip.name}": non-square pixels are not supported yet.` };
  }
  return {
    source,
    crop,
    model: {
      position: { x: position.x * seqFrame.width, y: position.y * seqFrame.height },
      anchor: { x: anchor.x * source.width, y: anchor.y * source.height },
      scaleX: scaleWidth / 100,
      scaleY: scale / 100,
      rotation,
    },
  };
}

// Runs one edit over every selected clip: `plan(model, seqFrame)` returns the Motion values to
// write for that clip. One transaction for all of them = one Ctrl+Z.
//
// A Graphic's canvas is the whole frame, so its geometry says nothing about where its text is.
// For a Graphic, `measure` (transform/frameBounds.js) finds the box its text is actually drawn
// in, and the plan uses that (`model.drawn`, sequence px).
//
// `layerTarget` (a text layer index) on a text-only Graphic with several text layers measures and
// moves that layer alone (measuredLayer); "all" or a single-layer Graphic keeps the whole box.
//
// `textBoxes({ project, seq, clip })`, when given, is asked for a text-only Graphic's per-layer
// blue boxes (the helper's text_box rpc) and the plan gets them as `m.textBoxes` (or the failure
// as `m.textBoxError`). A plan's `note` is reported in the result's `notes`, the clip still done.
async function editSelectedClips(ppro, label, plan, measure = null, group = null, layerTarget = "all", textBoxes = null) {
  const { project, sequence: seq } = await activeProjectAndSequence(ppro);
  const snap = await readSnapshot(ppro, { seq });
  if (snap.clips.length === 0) throw new Error("Select a clip on the timeline.");
  const seqFrame = snap.seqFrame;
  if (!seqFrame) throw new Error("Could not read the sequence frame size.");
  const seqAspect = snap.seqAspect;
  const clips = snap.clips;

  const writes = [];
  const paramWrites = [];
  const skipped = [];
  const notes = [];
  const clipBoundsUpdates = [];
  let done = 0;
  const modelResults = await Promise.all(clips.map(async (clip) => {
    const m = await clipModel(ppro, clip, seqFrame, seqAspect, seq);
    return { clip, m };
  }));

    const ready = [];
    for (const { clip, m } of modelResults) {
      if (m.skip) { skipped.push(m.skip); continue; }
      if (clip.isGraphic) {
        m.layers = clip.layers;
        m.textIndex = measuredLayer(clip.layers, layerTarget);
        let box = null;
        try {
          box = await drawnBox(project, seq, seqFrame, clip, measure, m.textIndex);
        } catch (error) {
          skipped.push(`"${clip.name}": ${(error && error.message) || error}`);
          continue;
        }
        if (!box) { skipped.push(`"${clip.name}" draws nothing at the playhead.`); continue; }
        m.drawn = box;
        if (textBoxes && clip.layers && clip.layers.onlyText) {
          try {
            m.textBoxes = await textBoxes({ project, seq, clip });
          } catch (error) {
            m.textBoxError = (error && error.message) || String(error);
          }
        }
      }
      ready.push({ clip, m });
    }
    // A group command (align to selection, distribute) decides from every usable clip's bounds
    // before any clip is planned; it throws, with nothing written, when there aren't enough.
    const groupCtx = group ? group(ready.map((r) => r.m), seqFrame, skipped) : null;
    for (let index = 0; index < ready.length; index += 1) {
      const { clip, m } = ready[index];
      const planned = plan(m, seqFrame, groupCtx, index);
      if (planned.noop) {
        done += 1;
        continue;
      }
      const boundsShift = planned.boundsShift || null;
      delete planned.boundsShift;
      if (planned.note) notes.push(`"${clip.name}": ${planned.note}`);
      delete planned.note;
      if (planned.layerWrites) {
        for (const w of planned.layerWrites) paramWrites.push(Object.assign({ name: clip.name }, w));
      } else {
        writes.push({ item: clip.item, name: clip.name, values: planned });
      }
      done += 1;
      // Every plan here either keeps the picture put (anchor) or moves it by boundsShift.
      if (m.drawn) {
        const one = m.textIndex !== null && m.textIndex !== undefined;
        clipBoundsUpdates.push({ item: one ? null : clip.item, key: one ? layerKey(clip, m.textIndex) : clip.key, clipKey: clip.key,
          dx: (boundsShift && boundsShift.dx) || 0, dy: (boundsShift && boundsShift.dy) || 0 });
        // One layer moved: the whole Graphic's box changed shape, not just place.
        if (one && boundsShift) frameBounds.invalidateBounds(clip.item, clip.key);
      }
    }
    if (done && (writes.length > 0 || paramWrites.length > 0)) {
      await transformApply.applyMotionValues(ppro, project, label, writes, paramWrites);
    }
    await shiftCachedBounds(ppro, seq, clipBoundsUpdates);
  // Text layer Position writes are not proven live yet: log before / written / read back, so one
  // run in Premiere shows whether the write took and in what units (UXPLogs).
  for (const w of paramWrites) {
    let after = null;
    try { after = (await w.param.getStartValue()).value; } catch (e) { after = `read failed: ${e && e.message}`; }
    console.log("CutDeck text layer write", JSON.stringify({ clip: w.name, field: w.field, before: w.before, wrote: w.value, readBack: after }));
  }
  return notes.length ? { done, skipped, notes } : { done, skipped };
}

// Nothing done is an error; some clips skipped (or done with a note) is a warning the panel
// shows; all done is quiet.
function editLevel({ done, skipped, notes }) {
  if (!done) return "error";
  return skipped.length || (notes && notes.length) ? "warn" : "ready";
}

function editSummary(verb, { done, skipped, notes }) {
  const head = done ? `${verb} on ${done} clip${done === 1 ? "" : "s"}.` : "Nothing changed.";
  const noted = notes && notes.length ? `${head} ${notes.join(" ")}` : head;
  return skipped.length ? `${noted} Skipped: ${skipped.join(" ")}` : noted;
}

// Phases 3/4: move the anchor to one of nine points on the visible (cropped) picture, and move
// Position with it so the picture stays exactly where it is.
async function setAnchor(ppro, target, measure = null, options = {}) {
  if (!transformGeometry.ANCHOR_TARGETS[target]) throw new Error(`Unknown anchor point "${target}".`);
  return editSelectedClips(ppro, `CutDeck: Anchor ${target}`, (ctx, seqFrame) => {
    const { model, source, crop, drawn, layers, textIndex } = ctx;
    if (drawn) {
      // The target on the text's blue box when it can be trusted (textBoxTarget), else on the
      // drawn letters, in the frame. Text Graphic: the TEXT's own Anchor Point goes there
      // (Premiere's Properties panel), else the Graphic's Motion anchor does. Either way
      // Position moves onto it, so nothing moves on screen.
      const snapped = textBoxTarget(ctx, target);
      const onScreen = (snapped && snapped.point) || transformGeometry.anchorTargetPoint(drawn, target);
      const note = snapped && snapped.note ? { note: `anchored to the letters, not the text box: ${snapped.note}.` } : {};
      const layerWrites = textLayerAnchor(layers, model, source, onScreen, textIndex);
      if (layerWrites) return { layerWrites, ...note };
      const anchorPx = transformGeometry.sequenceToSource(onScreen, model);
      return {
        anchorPoint: transformGeometry.framePixelsToNormalized(anchorPx, source.width, source.height),
        position: transformGeometry.framePixelsToNormalized(onScreen, seqFrame.width, seqFrame.height),
        ...note,
      };
    }
    const rect = transformGeometry.visibleSourceRect(source, crop);
    const anchorPx = transformGeometry.anchorTargetPoint(rect, target);
    const positionPx = transformGeometry.positionForAnchorMove(model, anchorPx);
    return {
      anchorPoint: transformGeometry.framePixelsToNormalized(anchorPx, source.width, source.height),
      position: transformGeometry.framePixelsToNormalized(positionPx, seqFrame.width, seqFrame.height),
    };
  }, measure, null, layerOption(options), options && options.textBoxes);
}

const layerOption = (options) => (options && options.layerTarget !== undefined ? options.layerTarget : "all");

// Moves every text layer of a Graphic by `delta` sequence pixels, through the text layers' own
// Position, the way Premiere's Properties panel aligns text, leaving the Graphic's Motion alone.
// The shift is undone through Motion's and Vector Motion's scale and rotation (translation
// doesn't change a shift), then normalized to the Graphic's canvas. Returns null when that
// can't be done exactly (a non-text layer, a keyframed or unreadable value), so the caller moves
// the whole Graphic instead and nothing is left behind. `only` (an index) moves that layer alone.
function textLayerShift(layers, model, source, delta, only = null) {
  // Not proven live yet: log what it saw (raw stored text Position / Anchor Point, to pin their
  // units against the Properties panel), and why it falls back when it does.
  const summary = layers && {
    seen: layers.seen,
    onlyText: layers.onlyText,
    vectorMotion: layers.vectorMotion,
    texts: layers.texts.map((t) => ({ hasParam: !!t.param, position: t.position, anchorPoint: t.anchorPoint })),
    delta,
  };
  console.log("CutDeck text layer align sees:", JSON.stringify(summary));
  const why = (reason) => {
    console.log("CutDeck text layer align fell back to Motion:", reason);
    return null;
  };
  if (!layers) return why("layers unreadable");
  if (!layers.onlyText) return why("not text-only");
  const vm = layers.vectorMotion;
  let scale = 100;
  let scaleWidth = 100;
  let rotation = 0;
  if (vm) {
    const s = staticValue(vm.scale);
    const uniform = staticValue(vm.uniformScale);
    const sw = uniform === false ? staticValue(vm.scaleWidth) : s;
    const r = staticValue(vm.rotation);
    if (![s, sw, r].every((v) => typeof v === "number") || !s || !sw) return why("Vector Motion values");
    scale = s;
    scaleWidth = sw;
    rotation = r;
  }
  const origin = { x: 0, y: 0 };
  const onCanvas = transformGeometry.sequenceToSource(delta, {
    position: origin, anchor: origin, scaleX: model.scaleX, scaleY: model.scaleY, rotation: model.rotation,
  });
  const inLayer = transformGeometry.sequenceToSource(onCanvas, {
    position: origin, anchor: origin, scaleX: scaleWidth / 100, scaleY: scale / 100, rotation,
  });
  const writes = [];
  for (const text of only === null || only === undefined ? layers.texts : [layers.texts[only]]) {
    const current = transformGeometry.pointXY(staticValue(text.position));
    if (!current || !text.param) return why("text Position unreadable or keyframed");
    writes.push({
      param: text.param,
      field: "text Position",
      before: current,
      value: { x: current.x + inLayer.x / source.width, y: current.y + inLayer.y / source.height },
    });
  }
  return writes;
}

// Scale/rotation of a layer transform as the geometry model wants them, or null if any value is
// keyframed or unreadable. `widthEntry` is used only when uniform scale is off.
function layerModel(position, anchorPoint, scaleEntry, widthEntry, uniformEntry, rotationEntry, canvas) {
  const p = transformGeometry.pointXY(staticValue(position));
  const a = transformGeometry.pointXY(staticValue(anchorPoint));
  const scale = staticValue(scaleEntry);
  const uniform = staticValue(uniformEntry);
  const width = uniform === false ? staticValue(widthEntry) : scale;
  const rotation = staticValue(rotationEntry);
  if (!p || !a || ![scale, width, rotation].every((v) => typeof v === "number") || !scale || !width) return null;
  return {
    position: { x: p.x * canvas.width, y: p.y * canvas.height },
    anchor: { x: a.x * canvas.width, y: a.y * canvas.height },
    scaleX: width / 100, scaleY: scale / 100, rotation,
  };
}

// How far (sequence px, each edge) the letters the save predicts may sit from the letters the
// frame measure saw: anti-aliasing is 1-2 px (live 2026-10-19: within 1.5 px at 105%); a stale
// save (other size or text) is off by far more.
const TEXT_BOX_TOLERANCE = 4;

// A text Graphic's blue boxes (PREMIERE_FACTS "Premiere's blue text box") carried to the screen:
// `{ placed: [{ entry, toScreen }] }`, or `{ note }` saying why the letters' box is used instead,
// or null when no box was asked for. `textBoxes` holds each layer's box and predicted letters
// (ink) in the layer's own space; each is carried to the screen through the layer's transform,
// Vector Motion and Motion, and trusted only when the letters land where they were measured.
function placedTextBoxes({ model, source, drawn, layers, textIndex, textBoxes, textBoxError }) {
  if (textBoxError) return { note: textBoxError };
  if (!textBoxes || !layers || !layers.onlyText) return null;
  const vm = layers.vectorMotion;
  const vmModel = vm ? layerModel(vm.position, vm.anchorPoint, vm.scale, vm.scaleWidth, vm.uniformScale, vm.rotation, source) : null;
  if (vm && !vmModel) return { note: "its Vector Motion is keyframed" };
  const one = textIndex !== null && textIndex !== undefined;
  const indices = one ? [textIndex] : layers.texts.map((_, i) => i);
  const placed = [];
  for (const i of indices) {
    const entry = textBoxes[i];
    if (!entry || !entry.box) return { note: (entry && entry.reason) || "the last save has no text for this layer" };
    if (!entry.ink) return { note: "the last save's text draws no letters" };
    const t = layers.texts[i];
    const textModel = layerModel(t.position, t.anchorPoint, t.scale, t.horizontalScale, t.uniformScale, t.rotation, source);
    if (!textModel) return { note: "its text transform is keyframed" };
    const toScreen = (p) => {
      const inGroup = transformGeometry.sourceToSequence(p, textModel);
      return transformGeometry.sourceToSequence(vmModel ? transformGeometry.sourceToSequence(inGroup, vmModel) : inGroup, model);
    };
    placed.push({ entry, toScreen });
  }
  const letters = transformGeometry.unionBounds(placed.map((p) => rectOnScreen(p.entry.ink, p.toScreen)));
  if (["left", "top", "right", "bottom"].some((edge) => Math.abs(letters[edge] - drawn[edge]) > TEXT_BOX_TOLERANCE)) {
    return { note: "the last save doesn't match what is drawn now; save the project and try again" };
  }
  return { placed };
}

// The screen-aligned box around `rect` (layer space) once `toScreen` has carried its corners.
function rectOnScreen(rect, toScreen) {
  const corners = [[rect.left, rect.top], [rect.right, rect.top], [rect.left, rect.bottom], [rect.right, rect.bottom]]
    .map(([x, y]) => toScreen({ x, y }));
  return { left: Math.min(...corners.map((c) => c.x)), right: Math.max(...corners.map((c) => c.x)),
    top: Math.min(...corners.map((c) => c.y)), bottom: Math.max(...corners.map((c) => c.y)) };
}

// The anchor target on the blue box, in sequence px: `{ point }`, `{ note }` or null (placedTextBoxes).
function textBoxTarget(ctx, target) {
  const found = placedTextBoxes(ctx);
  if (!found || found.note) return found;
  const { placed } = found;
  // One layer: the target on its own box, exact under rotation. Several: their outer box.
  if (placed.length === 1) return { point: placed[0].toScreen(transformGeometry.anchorTargetPoint(placed[0].entry.box, target)) };
  return { point: transformGeometry.anchorTargetPoint(transformGeometry.unionBounds(placed.map((p) => rectOnScreen(p.entry.box, p.toScreen))), target) };
}

// The blue box on screen (its screen-aligned outer box, what Premiere's Align lines up), as
// `{ rect }`, `{ note }` or null (placedTextBoxes).
function textBoxBounds(ctx) {
  const found = placedTextBoxes(ctx);
  if (!found || found.note) return found;
  return { rect: transformGeometry.unionBounds(found.placed.map((p) => rectOnScreen(p.entry.box, p.toScreen))) };
}

// Moves each text layer's own Anchor Point to the text point drawn at `onScreen` (sequence px),
// and its Position onto that same point, so the text stays put. The point is carried back
// through Motion, then Vector Motion, then each text layer's own transform. Null when that
// can't be done exactly, so the caller moves the Graphic's Motion anchor instead. With several
// text layers only the measured one (`only`) can take the box's point.
function textLayerAnchor(layers, model, source, onScreen, only = null) {
  const one = only !== null && only !== undefined;
  if (!layers || !layers.onlyText || !layers.texts || (!one && layers.texts.length !== 1)) return null;
  const vm = layers.vectorMotion;
  let inGroup = transformGeometry.sequenceToSource(onScreen, model);
  if (vm) {
    const vmModel = layerModel(vm.position, vm.anchorPoint, vm.scale, vm.scaleWidth, vm.uniformScale, vm.rotation, source);
    if (!vmModel) return null;
    inGroup = transformGeometry.sequenceToSource(inGroup, vmModel);
  }
  const writes = [];
  for (const t of one ? [layers.texts[only]] : layers.texts) {
    const textModel = layerModel(t.position, t.anchorPoint, t.scale, t.horizontalScale, t.uniformScale, t.rotation, source);
    if (!textModel || !t.param || !t.anchorParam) return null;
    const inText = transformGeometry.sequenceToSource(inGroup, textModel);
    writes.push(
      { param: t.anchorParam, field: "text Anchor Point", before: staticValue(t.anchorPoint),
        value: transformGeometry.framePixelsToNormalized(inText, source.width, source.height) },
      { param: t.param, field: "text Position", before: staticValue(t.position),
        value: transformGeometry.framePixelsToNormalized(inGroup, source.width, source.height) },
    );
  }
  return writes;
}

// Phase 5: line each clip's rendered (cropped, scaled, rotated) bounds up with the sequence frame.
// For a Graphic, the bounds are its text's box, and the text layers move.
// Where a clip's picture is drawn, in sequence pixels: for a Graphic, the blue text box when it
// can be trusted (textBoxBounds), else the measured letters; else the cropped source under the
// clip's transform.
function clipBounds(ctx) {
  const { model, source, crop, drawn } = ctx;
  const box = drawn && textBoxBounds(ctx);
  return (box && box.rect) || drawn || transformGeometry.renderedBounds(model, transformGeometry.visibleSourceRect(source, crop));
}

const lettersNote = (why) => `lined up by the letters, not the text box: ${why}.`;

// The write that moves a clip's picture by (dx, dy) sequence pixels: its text layers for a
// Graphic when that can be done exactly, else Motion Position.
function moveBy(ctx, seqFrame, dx, dy) {
  if (Math.abs(dx) < 1e-4 && Math.abs(dy) < 1e-4) return { noop: true };
  const box = ctx.drawn && textBoxBounds(ctx);
  const note = box && box.note ? { note: lettersNote(box.note) } : {};
  const layerWrites = ctx.drawn ? textLayerShift(ctx.layers, ctx.model, ctx.source, { x: dx, y: dy }, ctx.textIndex) : null;
  if (layerWrites) return { layerWrites, boundsShift: { dx, dy }, ...note };
  const positionPx = { x: ctx.model.position.x + dx, y: ctx.model.position.y + dy };
  return { position: transformGeometry.framePixelsToNormalized(positionPx, seqFrame.width, seqFrame.height), boundsShift: { dx, dy }, ...note };
}

async function alignToFrame(ppro, edge, measure = null, options = {}) {
  if (!transformGeometry.ALIGN_EDGES.includes(edge)) throw new Error(`Unknown alignment "${edge}".`);
  return editSelectedClips(ppro, `CutDeck: Align ${edge}`, (ctx, seqFrame) => {
    const { dx, dy } = transformGeometry.alignShift(clipBounds(ctx), seqFrame, edge);
    return moveBy(ctx, seqFrame, dx, dy);
  }, measure, null, layerOption(options), options && options.textBoxes);
}

// Lays out the text layers of ONE text-only Graphic by their own boxes: each layer's blue box
// when it can be trusted against its letters (measured with the others hidden), else those
// letters. `shifts(boxes, seqFrame)` gives each layer's {dx, dy} on screen, and each layer's
// Position takes it back through Motion and Vector Motion (textLayerShift). One transaction =
// one Ctrl+Z; the measure's hide/show steps come before it in History.
async function moveTextLayersByBoxes(ppro, project, snap, clip, label, shifts, measure, textBoxes = null) {
  const { sequence: seq, seqFrame } = snap;
  if (!seqFrame) throw new Error("Could not read the sequence frame size.");
  const m = await clipModel(ppro, clip, seqFrame, snap.seqAspect, seq);
  if (m.skip) throw new Error(m.skip);
  const boxCtx = { model: m.model, source: m.source, layers: clip.layers };
  if (textBoxes) {
    try {
      boxCtx.textBoxes = await textBoxes({ project, seq, clip });
    } catch (error) {
      boxCtx.textBoxError = (error && error.message) || String(error);
    }
  }
  const boxes = [];
  const notes = [];
  for (let i = 0; i < clip.layers.texts.length; i += 1) {
    let box;
    try {
      box = await drawnBox(project, seq, seqFrame, clip, measure, i);
    } catch (error) {
      throw new Error(`"${clip.name}" text ${i + 1}: ${(error && error.message) || error}`);
    }
    if (!box) throw new Error(`"${clip.name}" text ${i + 1} draws nothing at the playhead.`);
    const blue = textBoxes ? textBoxBounds(Object.assign({ drawn: box, textIndex: i }, boxCtx)) : null;
    if (blue && blue.note) {
      const note = `"${clip.name}" text ${i + 1}: ${lettersNote(blue.note)}`;
      if (!notes.includes(note)) notes.push(note);
    }
    boxes.push((blue && blue.rect) || box);
  }
  const deltas = shifts(boxes, seqFrame);
  const paramWrites = [];
  deltas.forEach((d, i) => {
    if (Math.abs(d.dx) < 1e-4 && Math.abs(d.dy) < 1e-4) return;
    const writes = textLayerShift(clip.layers, m.model, m.source, { x: d.dx, y: d.dy }, i);
    if (!writes) throw new Error(`"${clip.name}": its text layers can't be moved exactly (a keyframed or unreadable value).`);
    for (const w of writes) paramWrites.push(Object.assign({ name: clip.name }, w));
  });
  if (paramWrites.length) {
    await transformApply.applyMotionValues(ppro, project, label, [], paramWrites);
    frameBounds.invalidateBounds(clip.item, clip.key);
  }
  await shiftCachedBounds(ppro, seq, deltas.map((d, i) => ({ item: null, key: layerKey(clip, i), clipKey: clip.key, dx: d.dx, dy: d.dy })));
  return notes.length ? { done: 1, skipped: [], notes } : { done: 1, skipped: [] };
}

async function alignTextLayersInGraphic(ppro, project, seq, clip, layers, edge) {
  const seqFrame = await transformParams.readSequenceFrameSize(seq);
  if (!seqFrame) throw new Error("Could not read the sequence frame size.");

  const paramWrites = [];
  const coords = [];
  for (const t of layers.texts) {
    const p = transformGeometry.pointXY(staticValue(t.position));
    if (!p || !t.param) throw new Error(`"${clip.name}": text layer position is unreadable or keyframed.`);
    coords.push({ t, px: { x: p.x * seqFrame.width, y: p.y * seqFrame.height } });
  }

  const xs = coords.map((c) => c.px.x);
  const ys = coords.map((c) => c.px.y);
  let targetVal = null;
  const isX = ["left", "hcenter", "right"].includes(edge);

  if (edge === "left") targetVal = Math.min(...xs);
  else if (edge === "hcenter") targetVal = (Math.min(...xs) + Math.max(...xs)) / 2;
  else if (edge === "right") targetVal = Math.max(...xs);
  else if (edge === "top") targetVal = Math.min(...ys);
  else if (edge === "vcenter") targetVal = (Math.min(...ys) + Math.max(...ys)) / 2;
  else if (edge === "bottom") targetVal = Math.max(...ys);

  for (let i = 0; i < coords.length; i++) {
    const { t, px } = coords[i];
    const newPx = {
      x: isX ? targetVal : px.x,
      y: !isX ? targetVal : px.y,
    };
    const norm = transformGeometry.framePixelsToNormalized(newPx, seqFrame.width, seqFrame.height);
    paramWrites.push({
      name: clip.name,
      param: t.param,
      field: "text Position",
      value: norm,
    });
  }

  await transformApply.applyMotionValues(ppro, project, `CutDeck: Align ${edge} text layers`, [], paramWrites, []);
  frameBounds.invalidateBounds(clip.item, clip.key);
  return { done: 1, skipped: [] };
}

// Phase 6: every selected clip to the outer box of all their drawn bounds.
async function alignToSelection(ppro, edge, measure = null, options = {}) {
  if (!transformGeometry.ALIGN_EDGES.includes(edge)) throw new Error(`Unknown alignment "${edge}".`);
  const { project, sequence: seq } = await activeProjectAndSequence(ppro);
  const snap = await readSnapshot(ppro, { seq });
  const clips = snap.clips;
  if (clips.length === 1 && clips[0].isGraphic) {
    const layers = clips[0].layers;
    if (layers && layers.texts && layers.texts.length >= 2) {
      if (measure && layers.onlyText) {
        return moveTextLayersByBoxes(ppro, project, snap, clips[0], `CutDeck: Align ${edge} text layers`, (boxes) => {
          const box = transformGeometry.unionBounds(boxes);
          return boxes.map((b) => transformGeometry.alignShiftTo(b, box, edge));
        }, measure, options && options.textBoxes);
      }
      return alignTextLayersInGraphic(ppro, project, seq, clips[0], layers, edge);
    }
  }
  const group = (models, _frame, skipped) => {
    if (models.length < 2) throw new Error(`Select at least 2 clips to align to the selection.${skippedNote(skipped)}`);
    return transformGeometry.unionBounds(models.map(clipBounds));
  };
  return editSelectedClips(ppro, `CutDeck: Align ${edge} to selection`, (ctx, seqFrame, box) => {
    const { dx, dy } = transformGeometry.alignShiftTo(clipBounds(ctx), box, edge);
    return moveBy(ctx, seqFrame, dx, dy);
  }, measure, group, "all", options && options.textBoxes);
}

// Premiere's own third align mode, "Align to Video Frame as Group" (Properties panel strings
// $$$/Premiere/HSL/TransformControlsView/AlignToVideoFrameAsGroup, REA string scan 2026-10-16):
// the selection's outer box goes to the frame edge and every clip moves by the same amount, so
// their layout relative to each other is kept.
async function alignToFrameAsGroup(ppro, edge, measure = null, options = {}) {
  if (!transformGeometry.ALIGN_EDGES.includes(edge)) throw new Error(`Unknown alignment "${edge}".`);
  const group = (models, frame, skipped) => {
    if (models.length < 1) throw new Error(`Select a clip to align.${skippedNote(skipped)}`);
    return transformGeometry.alignShift(transformGeometry.unionBounds(models.map(clipBounds)), frame, edge);
  };
  return editSelectedClips(ppro, `CutDeck: Align ${edge} as group`, (ctx, seqFrame, shift) => (
    moveBy(ctx, seqFrame, shift.dx, shift.dy)
  ), measure, group, "all", options && options.textBoxes);
}

const skippedNote = (skipped) => (skipped.length ? ` Skipped: ${skipped.join(" ")}` : "");

const DISTRIBUTE = {
  "h-centers": ["x", "centers"], "v-centers": ["y", "centers"],
  "h-gaps": ["x", "gaps"], "v-gaps": ["y", "gaps"],
};

async function distributeTextLayersInGraphic(ppro, project, seq, clip, layers, kind, spec, to = "frame") {
  const seqFrame = await transformParams.readSequenceFrameSize(seq);
  if (!seqFrame) throw new Error("Could not read the sequence frame size.");

  const paramWrites = [];
  const coords = [];
  for (const t of layers.texts) {
    const p = transformGeometry.pointXY(staticValue(t.position));
    if (!p || !t.param) throw new Error(`"${clip.name}": text layer position is unreadable or keyframed.`);
    coords.push({ t, px: { x: p.x * seqFrame.width, y: p.y * seqFrame.height } });
  }

  const axis = spec[0]; // "x" or "y"
  const order = coords.map((_, i) => i).sort((a, b) => coords[a].px[axis] - coords[b].px[axis]);
  const n = order.length;
  const isFrame = to === "frame";
  const frameDim = axis === "x" ? seqFrame.width : seqFrame.height;

  for (let k = 0; k < n; k++) {
    const idx = order[k];
    const { t, px } = coords[idx];
    let targetPos;
    if (isFrame) {
      const step = frameDim / (n + 1);
      targetPos = (k + 1) * step;
    } else {
      const firstVal = coords[order[0]].px[axis];
      const lastVal = coords[order[n - 1]].px[axis];
      const step = (lastVal - firstVal) / (n - 1);
      targetPos = firstVal + k * step;
    }
    const newPx = {
      x: axis === "x" ? targetPos : px.x,
      y: axis === "y" ? targetPos : px.y,
    };
    const norm = transformGeometry.framePixelsToNormalized(newPx, seqFrame.width, seqFrame.height);
    paramWrites.push({
      name: clip.name,
      param: t.param,
      field: "text Position",
      value: norm,
    });
  }

  await transformApply.applyMotionValues(ppro, project, `CutDeck: Distribute ${kind}${isFrame ? " across frame" : ""} text layers`, [], paramWrites, []);
  frameBounds.invalidateBounds(clip.item, clip.key);
  return { done: 1, skipped: [] };
}

// Phase 6: distribute across the frame (equal margins on screen) or between outer selection.
async function distribute(ppro, kind, measure = null, to = "selection", options = {}) {
  const spec = DISTRIBUTE[kind];
  if (!spec) throw new Error(`Unknown distribution "${kind}".`);
  const { project, sequence: seq } = await activeProjectAndSequence(ppro);
  const snap = await readSnapshot(ppro, { seq });
  const clips = snap.clips;
  const isFrame = to === "frame";

  if (clips.length === 1 && clips[0].isGraphic) {
    const layers = clips[0].layers;
    const minLayers = isFrame ? 2 : 3;
    if (layers && layers.texts && layers.texts.length >= minLayers) {
      if (measure && layers.onlyText) {
        const [axis, mode] = spec;
        return moveTextLayersByBoxes(ppro, project, snap, clips[0],
          `CutDeck: Distribute ${kind}${isFrame ? " across frame" : ""} text layers`, (boxes, frame) => {
            const d = isFrame ? transformGeometry.distributeFrameShifts(boxes, frame, axis, mode)
              : transformGeometry.distributeShifts(boxes, axis, mode);
            return d.map((v) => ({ dx: axis === "x" ? v : 0, dy: axis === "y" ? v : 0 }));
          }, measure, options && options.textBoxes);
      }
      return distributeTextLayersInGraphic(ppro, project, seq, clips[0], layers, kind, spec, to);
    }
  }

  const minClips = isFrame ? 2 : 3;
  const group = (models, frame, skipped) => {
    if (models.length < minClips) {
      throw new Error(`Select at least ${minClips} clips to distribute${isFrame ? " across the frame" : ""}.${skippedNote(skipped)}`);
    }
    return isFrame
      ? transformGeometry.distributeFrameShifts(models.map(clipBounds), frame, spec[0], spec[1])
      : transformGeometry.distributeShifts(models.map(clipBounds), spec[0], spec[1]);
  };
  return editSelectedClips(ppro, `CutDeck: Distribute ${kind}${isFrame ? " across frame" : ""}`, (ctx, seqFrame, shifts, index) => {
    const d = shifts[index];
    return moveBy(ctx, seqFrame, spec[0] === "x" ? d : 0, spec[0] === "y" ? d : 0);
  }, measure, group, "all", options && options.textBoxes);
}

// Phase 2: one typed value on the clip the panel shows, in the units the panel shows (px, %, °).
const EDIT_FIELDS = {
  "position-x": { param: "position", axis: "x" },
  "position-y": { param: "position", axis: "y" },
  "anchor-x": { param: "anchorPoint", axis: "x" },
  "anchor-y": { param: "anchorPoint", axis: "y" },
  scale: { param: "scale", min: 0 },
  rotation: { param: "rotation" },
  // The other Effect Controls rows. Ranges are the params' own units: Crop and Opacity are
  // percent, Anti-flicker 0..1, so a typed value outside is clamped rather than sent.
  "scale-width": { param: "scaleWidth", min: 0 },
  "uniform-scale": { param: "uniformScale", bool: true },
  "anti-flicker": { param: "antiFlicker", min: 0, max: 1 },
  "crop-left": { param: "cropLeft", min: 0, max: 100 },
  "crop-top": { param: "cropTop", min: 0, max: 100 },
  "crop-right": { param: "cropRight", min: 0, max: 100 },
  "crop-bottom": { param: "cropBottom", min: 0, max: 100 },
  opacity: { param: "opacity", min: 0, max: 100 },
};

// The params a text-only Graphic takes from its text layer; every other field is the clip's own.
// Each maps to the text layer's [value entry, param handle] (transform/params.js readGraphicLayers).
const TEXT_FIELDS = {
  position: ["position", "param"],
  anchorPoint: ["anchorPoint", "anchorParam"],
  scale: ["scale", "scaleParam"],
  scaleWidth: ["horizontalScale", "horizontalScaleParam"],
  uniformScale: ["uniformScale", "uniformParam"],
  rotation: ["rotation", "rotationParam"],
};
const TEXT_LAYER_PARAMS = new Set(Object.keys(TEXT_FIELDS));

// Typed text to a value. Rotation also takes Effect Controls' own "turns x degrees" form
// ("1x10" = 370, "-1x-10" = -370), so a value copied from Effect Controls pastes back unchanged.
function parseFieldValue(spec, text) {
  const raw = String(text).trim();
  if (spec.bool) {
    if (/^(true|on|1)$/i.test(raw)) return true;
    if (/^(false|off|0)$/i.test(raw)) return false;
    throw new Error(`"${text}" is not on or off.`);
  }
  const typed = raw.replace(/[%°]/g, "").trim();
  const turns = spec.param === "rotation" ? /^(-?\d+)\s*x\s*(-?[\d.]+)$/i.exec(typed) : null;
  const number = turns ? Number(turns[1]) * 360 + Number(turns[2]) : Number(typed);
  if (typed === "" || !Number.isFinite(number)) throw new Error(`"${text}" is not a number.`);
  const min = spec.min === undefined ? -Infinity : spec.min;
  const max = spec.max === undefined ? Infinity : spec.max;
  return Math.min(max, Math.max(min, number));
}

// Sets the typed value on EVERY selected clip (Effect Controls can only do one at a time). A
// point axis is converted per clip, in that clip's own frame, keeping its other axis. Clips
// with that value keyframed are skipped, never flattened. One Ctrl+Z undoes the lot.
async function setField(ppro, field, text, options = {}) {
  const spec = EDIT_FIELDS[field];
  if (!spec) throw new Error(`Unknown field "${field}".`);
  const number = parseFieldValue(spec, text);
  const layerTarget = (options && options.layerTarget !== undefined) ? options.layerTarget : "all";

  const { project, sequence: seq } = await activeProjectAndSequence(ppro);
  const snap = await readSnapshot(ppro, { seq });
  const clips = snap.clips;
  if (clips.length === 0) throw new Error("Select a clip on the timeline.");
  const seqFrame = spec.param === "position" ? (snap.seqFrame || await transformParams.readSequenceFrameSize(seq)) : null;

  const writes = [];
  const paramWrites = [];
  const skipped = [];
  const boundsUpdates = [];
  let done = 0;
  for (const clip of clips) {
    if (clip.isGraphic && TEXT_LAYER_PARAMS.has(spec.param)) {
      const layers = clip.layers;
      if (textTarget(layers)) {
        const textsToTarget = (layerTarget === "all")
          ? layers.texts.map((_, i) => i)
          : [(typeof layerTarget === "number" && layerTarget >= 0 && layerTarget < layers.texts.length) ? layerTarget : 0];

        let textSkipped = false;
        for (const idx of textsToTarget) {
          const t = layers.texts[idx];
          const entry = t[TEXT_FIELDS[spec.param][0]];
          if (entry && entry.isTimeVarying) {
            skipped.push(`"${clip.name}" has this value keyframed.`);
            textSkipped = true;
            break;
          }
        }
        if (textSkipped) continue;

        const frame = seqFrame || clip.anchorFrame || await transformParams.readAnchorFrameSize(ppro, clip.item, seq);
        if (!frame) {
          skipped.push(`"${clip.name}": could not read its ${spec.param === "position" ? "sequence" : "source"} frame size.`);
          continue;
        }

        let clipWrote = false;
        let deltaPx = 0;
        if (spec.param === "scaleWidth" || spec.param === "uniformScale") {
          // Horizontal Scale and Uniform Scale: the same value on each targeted text layer.
          const paramName = TEXT_FIELDS[spec.param][1];
          for (const t of targetTexts(layers, layerTarget)) {
            if (!t[paramName]) continue;
            paramWrites.push({ param: t[paramName], field: `text ${spec.param}`, value: number, name: clip.name });
            clipWrote = true;
          }
        } else if (spec.axis) {
          const refIdx = textsToTarget[0];
          const refText = layers.texts[refIdx];
          const refEntry = refText && refText[spec.param];
          const refCurrent = frame && refEntry && transformGeometry.normalizedToFramePixels(staticValue(refEntry), frame.width, frame.height);
          if (refCurrent) {
            deltaPx = number - refCurrent[spec.axis];
            for (const tIdx of textsToTarget) {
              const t = layers.texts[tIdx];
              const entry = t[spec.param];
              const current = frame && transformGeometry.normalizedToFramePixels(staticValue(entry), frame.width, frame.height);
              if (!current) continue;
              current[spec.axis] += deltaPx;
              const norm = transformGeometry.framePixelsToNormalized(current, frame.width, frame.height);

              if (spec.param === "anchorPoint") {
                // B5: Typed Anchor on text must compensate Position so the text stays frozen on screen
                const tModel = layerModel(t.position, t.anchorPoint, t.scale, t.horizontalScale, t.uniformScale, t.rotation, frame);
                if (tModel && t.anchorParam && t.param) {
                  const newAnchorPx = { ...tModel.anchor, [spec.axis]: current[spec.axis] };
                  const newPosPx = transformGeometry.positionForAnchorMove(tModel, newAnchorPx);
                  paramWrites.push({
                    param: t.anchorParam,
                    field: "text anchorPoint",
                    value: norm,
                    name: clip.name,
                  });
                  paramWrites.push({
                    param: t.param,
                    field: "text Position",
                    value: transformGeometry.framePixelsToNormalized(newPosPx, frame.width, frame.height),
                    name: clip.name,
                  });
                  clipWrote = true;
                }
              } else {
                const targetParam = spec.param === "position" ? t.param : t.anchorParam;
                if (targetParam) {
                  paramWrites.push({
                    param: targetParam,
                    field: `text ${spec.param}`,
                    value: norm,
                    name: clip.name,
                  });
                  clipWrote = true;
                }
              }
            }
          }
        } else if (spec.param === "scale") {
          const refIdx = textsToTarget[0];
          const refScale = staticValue(layers.texts[refIdx].scale) || 100;
          const ratio = refScale !== 0 ? number / refScale : 1;
          for (const tIdx of textsToTarget) {
            const t = layers.texts[tIdx];
            if (t.scaleParam) {
              const curScale = staticValue(t.scale) || 100;
              const newScale = tIdx === refIdx ? number : (curScale * ratio);
              paramWrites.push({
                param: t.scaleParam,
                field: "text scale",
                value: newScale,
                name: clip.name,
              });
              clipWrote = true;
            }
          }
        } else if (spec.param === "rotation") {
          const refIdx = textsToTarget[0];
          const refRot = staticValue(layers.texts[refIdx].rotation) || 0;
          const deltaRot = number - refRot;
          for (const tIdx of textsToTarget) {
            const t = layers.texts[tIdx];
            if (t.rotationParam) {
              const curRot = staticValue(t.rotation) || 0;
              const newRot = tIdx === refIdx ? number : (curRot + deltaRot);
              paramWrites.push({
                param: t.rotationParam,
                field: "text rotation",
                value: newRot,
                name: clip.name,
              });
              clipWrote = true;
            }
          }
        }
        if (clipWrote) {
          done += 1;
          if (spec.param === "position" && typeof deltaPx === "number" && layerTarget === "all") {
            const dx = spec.axis === "x" ? deltaPx : 0;
            const dy = spec.axis === "y" ? deltaPx : 0;
            boundsUpdates.push({ item: clip.item, key: clip.key, dx, dy });
          } else {
            frameBounds.invalidateBounds(clip.item, clip.key);
          }
        }
        continue;
      }
    }

    const entry = clip.transform[spec.param];
    if (entry && entry.isTimeVarying) { skipped.push(`"${clip.name}" has this value keyframed.`); continue; }
    let value = number;
    if (spec.axis) {
      const frame = seqFrame || clip.anchorFrame || await transformParams.readAnchorFrameSize(ppro, clip.item, seq);
      if (!frame) {
        skipped.push(`"${clip.name}": could not read its ${spec.param === "position" ? "sequence" : "source"} frame size.`);
        continue;
      }
      const current = transformGeometry.normalizedToFramePixels(staticValue(entry), frame.width, frame.height);
      if (!current) { skipped.push(`"${clip.name}": could not read its current ${spec.param}.`); continue; }
      current[spec.axis] = number;
      value = transformGeometry.framePixelsToNormalized(current, frame.width, frame.height);
    }
    writes.push({ item: clip.item, name: clip.name, values: { [spec.param]: value } });
    done += 1;
  }
  if (writes.length || paramWrites.length) {
    await transformApply.applyMotionValues(ppro, project, `CutDeck: Set ${field}`, writes, paramWrites);
    await shiftCachedBounds(ppro, seq, boundsUpdates);
  }
  return { done, skipped };
}

// Each row's reset, the value Effect Controls' reset arrow puts back. Motion: Position the
// sequence centre and Anchor Point the source centre (both [0.5, 0.5] normalized; a Graphic's
// canvas is the sequence frame), Scale 100, Uniform on, Rotation 0, Anti-flicker 0, Crop 0,
// Opacity 100. A text layer: Anchor Point [0, 0] (a new text layer reads [0,0], PREMIERE_FACTS
// "Graphic Text layer"); its Position has no fixed default (it is where the text was placed),
// so that reset is refused rather than guessed.
const RESET_FIELDS = {
  position: { param: "position", label: "Position", motion: { x: 0.5, y: 0.5 } },
  anchor: { param: "anchorPoint", label: "Anchor Point", motion: { x: 0.5, y: 0.5 }, text: { x: 0, y: 0 } },
  scale: { param: "scale", label: "Scale", motion: 100, text: 100 },
  "scale-width": { param: "scaleWidth", label: "Scale Width", motion: 100, text: 100 },
  "uniform-scale": { param: "uniformScale", label: "Uniform Scale", motion: true, text: true },
  rotation: { param: "rotation", label: "Rotation", motion: 0, text: 0 },
  "anti-flicker": { param: "antiFlicker", label: "Anti-flicker Filter", motion: 0 },
  "crop-left": { param: "cropLeft", label: "Crop Left", motion: 0 },
  "crop-top": { param: "cropTop", label: "Crop Top", motion: 0 },
  "crop-right": { param: "cropRight", label: "Crop Right", motion: 0 },
  "crop-bottom": { param: "cropBottom", label: "Crop Bottom", motion: 0 },
  opacity: { param: "opacity", label: "Opacity", motion: 100 },
};

// Resets one row on every selected clip (both axes of a point together) in ONE transaction, so
// one Ctrl+Z puts it back. Keyframed values are skipped, never flattened.
async function resetField(ppro, row, options = {}) {
  const spec = RESET_FIELDS[row];
  if (!spec) throw new Error(`Unknown field "${row}".`);
  const layerTarget = options && options.layerTarget !== undefined ? options.layerTarget : "all";
  const { project, sequence: seq } = await activeProjectAndSequence(ppro);
  const snap = await readSnapshot(ppro, { seq });
  if (snap.clips.length === 0) throw new Error("Select a clip on the timeline.");

  const writes = [];
  const paramWrites = [];
  const skipped = [];
  let done = 0;
  for (const clip of snap.clips) {
    if (clip.isGraphic && TEXT_FIELDS[spec.param] && textTarget(clip.layers)) {
      if (spec.text === undefined) {
        skipped.push(`"${clip.name}": a text layer's ${spec.label} has no fixed default.`);
        continue;
      }
      const [entryName, paramName] = TEXT_FIELDS[spec.param];
      const texts = targetTexts(clip.layers, layerTarget);
      if (texts.some((t) => t[entryName] && t[entryName].isTimeVarying)) {
        skipped.push(`"${clip.name}" has this value keyframed.`);
        continue;
      }
      if (texts.some((t) => !t[paramName])) {
        skipped.push(`"${clip.name}": could not reach its text ${spec.label}.`);
        continue;
      }
      for (const t of texts) paramWrites.push({ param: t[paramName], field: `text ${spec.param}`, value: spec.text, name: clip.name });
      done += 1;
      continue;
    }
    const entry = clip.transform[spec.param];
    if (entry && entry.isTimeVarying) { skipped.push(`"${clip.name}" has this value keyframed.`); continue; }
    writes.push({ item: clip.item, name: clip.name, values: { [spec.param]: spec.motion } });
    done += 1;
  }
  if (writes.length || paramWrites.length) {
    await transformApply.applyMotionValues(ppro, project, `CutDeck: Reset ${spec.label}`, writes, paramWrites);
  }
  return { done, skipped };
}

module.exports = {
  describeField,
  readAlignTransform,
  readAlignState,
  clipModel,
  editLevel,
  editSummary,
  setField,
  resetField,
  RESET_FIELDS,
  boundsSignature,
  setAnchor,
  alignToFrame,
  alignToFrameAsGroup,
  alignToSelection,
  distribute,
  textTarget,
  parseFieldValue,
  EDIT_FIELDS,
};
