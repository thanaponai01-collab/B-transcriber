// Owns the Transform panel display state, clip transform reads, and polling loop, and its
// three edits: a typed field (Phase 2), the nine-point anchor (Phases 3/4) and align to the
// sequence frame (Phase 5) — docs/research/cutdeck-transform-panel-plan.md.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const trackItems = require("../host/trackItems.js");
const transformParams = require("../transform/params.js");
const transformGeometry = require("../transform/geometry.js");
const transformApply = require("../transform/apply.js");
const frameBounds = require("../transform/frameBounds.js");
const { activeProjectAndSequence } = require("../host/project.js");
const { PROBES, runProbe, createProbesFeature } = require("./probes.js");

const transformProbe = PROBES.find((p) => p.id === "transform");

function describeField(entry, isPoint, frameSize) {
  if (!entry) return { known: false };
  if (entry.isTimeVarying) return { known: true, animated: true };
  if (isPoint) {
    const px = frameSize
      ? transformGeometry.normalizedToFramePixels(entry.value, frameSize.width, frameSize.height)
      : null;
    return px ? { known: true, animated: false, x: px.x, y: px.y } : { known: false };
  }
  return typeof entry.value === "number" ? { known: true, animated: false, value: entry.value } : { known: false };
}

async function readAlignTransform(seq, ppro) {
  if (!seq) return { clipName: null, available: false, reason: "No sequence open.", fields: null };

  const items = await trackItems.getSelectedTrackItems(seq);
  if (items.length === 0) {
    return { clipName: null, available: false, reason: "Select a clip on the timeline.", fields: null };
  }
  // Linked selection brings the audio along (PREMIERE_FACTS "Sequence.getSelection()"), and audio
  // has no Motion: show the first selected item that has one.
  let item = items[0];
  let transform = null;
  for (const candidate of items) {
    transform = await transformParams.readTransform(candidate);
    if (transform) { item = candidate; break; }
  }
  const clipName = (await trackItems.trackItemName(item, "(unnamed)")) + (items.length > 1 ? ` (+${items.length - 1} more selected)` : "");
  if (!transform) {
    return { clipName, available: false, reason: "This item has no readable Transform.", fields: null };
  }

  const frameSize = await transformParams.readSequenceFrameSize(seq);
  const anchorFrame = await transformParams.readAnchorFrameSize(ppro, item, seq);
  const fields = {
    position: describeField(transform.position, true, frameSize),
    scale: describeField(transform.scale, false, frameSize),
    rotation: describeField(transform.rotation, false, frameSize),
    anchor: describeField(transform.anchorPoint, true, anchorFrame),
  };
  return { clipName, available: true, reason: null, fields };
}

async function readAlignState(ppro) {
  const { sequence: seq } = await activeProjectAndSequence(ppro, { requireProject: false, requireSequence: false });
  return {
    sequence: seq ? { name: seq.name || "(unnamed)" } : null,
    transform: await readAlignTransform(seq, ppro),
  };
}

// --- edits ---------------------------------------------------------------------------------

const staticValue = (entry) => (entry && !entry.isTimeVarying && entry.value !== null && entry.value !== undefined ? entry.value : null);

// Every selected item that has a Motion effect, with its name and transform read.
async function readSelectedMotionClips(seq) {
  const items = await trackItems.getSelectedTrackItems(seq);
  const clips = [];
  for (const item of items) {
    const transform = await transformParams.readTransform(item);
    if (transform) clips.push({ item, transform, name: await trackItems.trackItemName(item, "(unnamed)") });
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
  const source = await transformParams.readAnchorFrameSize(ppro, clip.item, seq);
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
// in, and the plan uses that (`model.drawn`, sequence px). That costs two frame saves and two
// extra undo steps (the clip switched off and back on) per Graphic.
async function editSelectedClips(ppro, label, plan, measure = null) {
  const { project, sequence: seq } = await activeProjectAndSequence(ppro);
  const clips = await readSelectedMotionClips(seq);
  if (clips.length === 0) throw new Error("Select a clip on the timeline.");
  const seqFrame = await transformParams.readSequenceFrameSize(seq);
  if (!seqFrame) throw new Error("Could not read the sequence frame size.");
  const seqAspect = await transformParams.readSequencePixelAspect(seq);

  const writes = [];
  const paramWrites = [];
  const skipped = [];
  let done = 0;
  for (const clip of clips) {
    const m = await clipModel(ppro, clip, seqFrame, seqAspect, seq);
    if (m.skip) { skipped.push(m.skip); continue; }
    if (await transformParams.isGraphic(clip.item)) {
      if (!measure) { skipped.push(`"${clip.name}": a Graphic needs its text measured, which isn't available here.`); continue; }
      try {
        m.drawn = await measure({ project, seq, item: clip.item, frame: seqFrame });
      } catch (error) {
        skipped.push(`"${clip.name}": ${(error && error.message) || error}`);
        continue;
      }
      if (!m.drawn) { skipped.push(`"${clip.name}" draws nothing at the playhead.`); continue; }
      m.layers = await transformParams.readGraphicLayers(clip.item);
    }
    const planned = plan(m, seqFrame);
    if (planned.layerWrites) {
      for (const w of planned.layerWrites) paramWrites.push(Object.assign({ name: clip.name }, w));
      done += 1;
    } else {
      writes.push({ item: clip.item, name: clip.name, values: planned });
      done += 1;
    }
  }
  if (done) await transformApply.applyMotionValues(ppro, project, label, writes, paramWrites);
  // Text layer Position writes are not proven live yet: log before / written / read back, so one
  // run in Premiere shows whether the write took and in what units (UXPLogs).
  for (const w of paramWrites) {
    let after = null;
    try { after = (await w.param.getStartValue()).value; } catch (e) { after = `read failed: ${e && e.message}`; }
    console.log("CutDeck text layer write", JSON.stringify({ clip: w.name, field: w.field, before: w.before, wrote: w.value, readBack: after }));
  }
  return { done, skipped };
}

// Nothing done is an error; some clips skipped is a warning the panel shows; all done is quiet.
function editLevel({ done, skipped }) {
  if (!done) return "error";
  return skipped.length ? "warn" : "ready";
}

function editSummary(verb, { done, skipped }) {
  const head = done ? `${verb} on ${done} clip${done === 1 ? "" : "s"}.` : "Nothing changed.";
  return skipped.length ? `${head} Skipped: ${skipped.join(" ")}` : head;
}

// Phases 3/4: move the anchor to one of nine points on the visible (cropped) picture, and move
// Position with it so the picture stays exactly where it is.
async function setAnchor(ppro, target, measure = null) {
  if (!transformGeometry.ANCHOR_TARGETS[target]) throw new Error(`Unknown anchor point "${target}".`);
  return editSelectedClips(ppro, `CutDeck: Anchor ${target}`, ({ model, source, crop, drawn, layers }, seqFrame) => {
    if (drawn) {
      // The target on the drawn box, in the frame. Text Graphic: the TEXT's own Anchor Point
      // goes there (Premiere's Properties panel), else the Graphic's Motion anchor does. Either
      // way Position moves onto it, so nothing moves on screen.
      const onScreen = transformGeometry.anchorTargetPoint(drawn, target);
      const layerWrites = textLayerAnchor(layers, model, source, onScreen);
      if (layerWrites) return { layerWrites };
      const anchorPx = transformGeometry.sequenceToSource(onScreen, model);
      return {
        anchorPoint: transformGeometry.framePixelsToNormalized(anchorPx, source.width, source.height),
        position: transformGeometry.framePixelsToNormalized(onScreen, seqFrame.width, seqFrame.height),
      };
    }
    const rect = transformGeometry.visibleSourceRect(source, crop);
    const anchorPx = transformGeometry.anchorTargetPoint(rect, target);
    const positionPx = transformGeometry.positionForAnchorMove(model, anchorPx);
    return {
      anchorPoint: transformGeometry.framePixelsToNormalized(anchorPx, source.width, source.height),
      position: transformGeometry.framePixelsToNormalized(positionPx, seqFrame.width, seqFrame.height),
    };
  }, measure);
}

// Moves every text layer of a Graphic by `delta` sequence pixels, through the text layers' own
// Position, the way Premiere's Properties panel aligns text, leaving the Graphic's Motion alone.
// The shift is undone through Motion's and Vector Motion's scale and rotation (translation
// doesn't change a shift), then normalized to the Graphic's canvas. Returns null when that
// can't be done exactly (a non-text layer, a keyframed or unreadable value), so the caller moves
// the whole Graphic instead and nothing is left behind.
function textLayerShift(layers, model, source, delta) {
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
  if (!layers.vectorMotion) return why("no Vector Motion");
  const vm = layers.vectorMotion;
  const scale = staticValue(vm.scale);
  const uniform = staticValue(vm.uniformScale);
  const scaleWidth = uniform === false ? staticValue(vm.scaleWidth) : scale;
  const rotation = staticValue(vm.rotation);
  if (![scale, scaleWidth, rotation].every((v) => typeof v === "number") || !scale || !scaleWidth) return why("Vector Motion values");
  const origin = { x: 0, y: 0 };
  const onCanvas = transformGeometry.sequenceToSource(delta, {
    position: origin, anchor: origin, scaleX: model.scaleX, scaleY: model.scaleY, rotation: model.rotation,
  });
  const inLayer = transformGeometry.sequenceToSource(onCanvas, {
    position: origin, anchor: origin, scaleX: scaleWidth / 100, scaleY: scale / 100, rotation,
  });
  const writes = [];
  for (const text of layers.texts) {
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

// Moves each text layer's own Anchor Point to the text point drawn at `onScreen` (sequence px),
// and its Position onto that same point, so the text stays put. The point is carried back
// through Motion, then Vector Motion, then the text layer's own transform. Null when that
// can't be done exactly, so the caller moves the Graphic's Motion anchor instead.
function textLayerAnchor(layers, model, source, onScreen) {
  if (!layers || !layers.onlyText || !layers.vectorMotion) return null;
  const vm = layers.vectorMotion;
  const vmModel = layerModel(vm.position, vm.anchorPoint, vm.scale, vm.scaleWidth, vm.uniformScale, vm.rotation, source);
  if (!vmModel) return null;
  const inGroup = transformGeometry.sequenceToSource(transformGeometry.sequenceToSource(onScreen, model), vmModel);
  const writes = [];
  for (const t of layers.texts) {
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
// For a Graphic, the bounds are its measured text box, and the text layers move.
async function alignToFrame(ppro, edge, measure = null) {
  if (!transformGeometry.ALIGN_EDGES.includes(edge)) throw new Error(`Unknown alignment "${edge}".`);
  return editSelectedClips(ppro, `CutDeck: Align ${edge}`, ({ model, source, crop, drawn, layers }, seqFrame) => {
    const bounds = drawn || transformGeometry.renderedBounds(model, transformGeometry.visibleSourceRect(source, crop));
    const { dx, dy } = transformGeometry.alignShift(bounds, seqFrame, edge);
    const layerWrites = drawn ? textLayerShift(layers, model, source, { x: dx, y: dy }) : null;
    if (layerWrites) return { layerWrites };
    const positionPx = { x: model.position.x + dx, y: model.position.y + dy };
    return { position: transformGeometry.framePixelsToNormalized(positionPx, seqFrame.width, seqFrame.height) };
  }, measure);
}

// Phase 2: one typed value on the clip the panel shows, in the units the panel shows (px, %, °).
const EDIT_FIELDS = {
  "position-x": { param: "position", axis: "x" },
  "position-y": { param: "position", axis: "y" },
  "anchor-x": { param: "anchorPoint", axis: "x" },
  "anchor-y": { param: "anchorPoint", axis: "y" },
  scale: { param: "scale" },
  rotation: { param: "rotation" },
};

// Sets the typed value on EVERY selected clip (Effect Controls can only do one at a time). A
// point axis is converted per clip, in that clip's own frame, keeping its other axis. Clips
// with that value keyframed are skipped, never flattened. One Ctrl+Z undoes the lot.
async function setField(ppro, field, text) {
  const spec = EDIT_FIELDS[field];
  if (!spec) throw new Error(`Unknown field "${field}".`);
  const typed = String(text).trim();
  const number = Number(typed);
  if (typed === "" || !Number.isFinite(number)) throw new Error(`"${text}" is not a number.`);

  const { project, sequence: seq } = await activeProjectAndSequence(ppro);
  const clips = await readSelectedMotionClips(seq);
  if (clips.length === 0) throw new Error("Select a clip on the timeline.");
  const seqFrame = spec.param === "position" ? await transformParams.readSequenceFrameSize(seq) : null;

  const writes = [];
  const skipped = [];
  for (const clip of clips) {
    const entry = clip.transform[spec.param];
    if (entry && entry.isTimeVarying) { skipped.push(`"${clip.name}" has this value keyframed.`); continue; }
    let value = number;
    if (spec.axis) {
      const frame = seqFrame || await transformParams.readAnchorFrameSize(ppro, clip.item, seq);
      const current = frame && transformGeometry.normalizedToFramePixels(staticValue(entry), frame.width, frame.height);
      if (!current) {
        skipped.push(`"${clip.name}": could not read its ${spec.param === "position" ? "sequence" : "source"} frame size.`);
        continue;
      }
      current[spec.axis] = number;
      value = transformGeometry.framePixelsToNormalized(current, frame.width, frame.height);
    }
    writes.push({ item: clip.item, name: clip.name, values: { [spec.param]: value } });
  }
  if (writes.length) await transformApply.applyMotionValues(ppro, project, `CutDeck: Set ${field}`, writes);
  return { done: writes.length, skipped };
}

// Without events the panel falls back to the old fast poll. With them there is no poll:
// a Position drag in Effect Controls fires no event and shows on the next click or Refresh.
const FAST_POLL_MS = 600;

// Subscribes `handler` to selection changes and sequence switches. EventManager and
// Constants.SequenceEvent {ACTIVATED, SELECTION_CHANGED} are in @adobe/premierepro 26.2.1
// d.ts. Live (2026-09-24): a global ACTIVATED listener fires on sequence switch, but a
// global SELECTION_CHANGED does not — so selection is attached to the active sequence and
// moved on every switch. Returns false if unavailable.
function subscribeSequenceEvents(ppro, handler) {
  const em = ppro && ppro.EventManager;
  const ev = ppro && ppro.Constants && ppro.Constants.SequenceEvent;
  if (!em || typeof em.addGlobalEventListener !== "function" || typeof em.addEventListener !== "function" || !ev) {
    return false;
  }
  let attached = null;
  const attachToActive = async () => {
    try {
      const { sequence } = await activeProjectAndSequence(ppro, { requireProject: false, requireSequence: false });
      if (sequence === attached) return;
      if (attached && typeof em.removeEventListener === "function") {
        try { em.removeEventListener(attached, ev.SELECTION_CHANGED, handler); } catch (_) {}
      }
      attached = sequence || null;
      if (attached) em.addEventListener(attached, ev.SELECTION_CHANGED, handler);
    } catch (error) {
      console.error("CutDeck: could not attach selection listener", error);
    }
  };
  try {
    em.addGlobalEventListener(ev.ACTIVATED, () => { attachToActive(); handler(); });
    attachToActive();
    return true;
  } catch (error) {
    console.error("CutDeck: sequence event subscribe failed, polling instead", error);
    return false;
  }
}

function createAlignFeature({ ppro, ctl, uxp = null, rpc = null, ensureHelper = null }) {
  // Copy uses the probes feature's clipboard code, against this panel's own status.
  const copier = createProbesFeature({ ppro, ctl, uxp });
  // Measuring a Graphic's text needs the helper (it compares the two saved frames).
  const measure = rpc && uxp ? async (args) => {
    if (ensureHelper) await ensureHelper();
    return frameBounds.measureDrawnBounds({ ppro, rpc, uxp, ...args });
  } : null;
  let alignPollTimer = null;
  let pollInFlight = false;
  let pollAgain = false;

  async function refreshAlignSequence() {
    const next = await readAlignState(ppro);
    ctl.state.sequence = next.sequence;
    ctl.state.transform = next.transform;
    ctl.render();
  }

  // Coalesces bursts (a drag-select fires many events): one read at a time, plus one
  // follow-up if more arrived meanwhile.
  async function pollAlignTransform() {
    if (ctl.state.busy) return;
    if (pollInFlight) { pollAgain = true; return; }
    pollInFlight = true;
    try {
      do {
        pollAgain = false;
        const next = await readAlignState(ppro);
        ctl.state.sequence = next.sequence;
        ctl.state.transform = next.transform;
        ctl.render();
      } while (pollAgain);
    } catch (error) {
      console.error("CutDeck: transform poll failed", error);
    } finally {
      pollInFlight = false;
    }
  }

  let started = false;
  function startAlignPolling() {
    if (started) return;
    started = true;
    if (!subscribeSequenceEvents(ppro, () => { pollAlignTransform(); })) {
      alignPollTimer = setInterval(pollAlignTransform, FAST_POLL_MS);
    }
  }

  return {
    onRefresh: () => ctl.act(refreshAlignSequence),
    onSetField: (field, text) => ctl.act(async () => {
      let result;
      try {
        result = await setField(ppro, field, text);
      } finally {
        await refreshAlignSequence();
      }
      ctl.setStatus(editSummary(`Set ${field}`, result), editLevel(result));
    }),
    onAnchor: (target) => ctl.act(async () => {
      const result = await setAnchor(ppro, target, measure);
      await refreshAlignSequence();
      ctl.setStatus(editSummary(`Anchor set to ${target}`, result), editLevel(result));
    }),
    onAlign: (edge) => ctl.act(async () => {
      const result = await alignToFrame(ppro, edge, measure);
      await refreshAlignSequence();
      ctl.setStatus(editSummary(`Aligned ${edge}`, result), editLevel(result));
    }),
    onProbe: (name) => ctl.act(async () => {
      if (name === "copystatus") {
        await copier.handleProbe("copystatus");
        ctl.setStatus(ctl.state.status.text, "info");
        return;
      }
      await refreshAlignSequence();
      await runProbe(transformProbe, ppro, ctl);
      if (ctl.state.status.level === "ready") ctl.setStatus(ctl.state.status.text, "info");
    }),
    refresh: refreshAlignSequence,
    startPolling: startAlignPolling,
    describeField,
    readAlignTransform: (seq) => readAlignTransform(seq, ppro),
    readAlignState: () => readAlignState(ppro),
  };
}

module.exports = {
  createAlignFeature,
  subscribeSequenceEvents,
  describeField,
  readAlignTransform,
  readAlignState,
  clipModel,
  setField,
  setAnchor,
  alignToFrame,
};
