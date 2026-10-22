/* Read-only probes for questions PREMIERE_FACTS still lists as unproven.
   Adobe API source: reference/adobe/api/premierepro.txt (Sequence.get*Track/get*TrackCount,
   Video/Audio/CaptionTrack.isMuted, Sequence.getSelection, TrackItemSelection.getTrackItems,
   VideoClipTrackItem.getProjectItem).

   1. muteState: does isMuted() read TRUE on a track muted in Premiere's UI? Frame Hold and
      frameBounds mute other tracks and unmute only the ones they muted, trusting isMuted() to
      skip tracks the user had already muted. Mute one track by hand, run this, and check that
      track reads muted.
   2. textCanvas: are a Graphic's text Position values fractions of the sequence frame or of the
      Graphic's own canvas? align.js uses the sequence frame in setField and
      alignTextLayersInGraphic, and readAnchorFrameSize (project-item size, else sequence frame)
      in textLayerShift and textLayerAnchor. They agree unless the Graphic has a project item
      whose size differs from the sequence.
   3. captionTiming: on which frames did an imported SRT's captions land? Reads every caption
      item's start/end ticks and the sequence's ticks per frame (Sequence.getTimebase, Sequence.
      getCaptionTrackCount/getCaptionTrack, CaptionTrack.getTrackItems). getTrackItems is typed
      as returning [], so caption items' getStartTime/getEndTime come from the clip track items'
      declaration and the live readback in PREMIERE_FACTS "UI caption placement"; the probe
      reports the item's members instead of guessing when they are missing.
      tools/srt_roundtrip.py compares the result with the SRT frame by frame.

   Nothing here writes. A failed call is a finding, never a throw. */

const transformParams = require("./transform/params.js");

async function attempt(fn) {
  try {
    return { ok: true, value: await fn() };
  } catch (error) {
    return { ok: false, error: (error && error.message) || String(error) };
  }
}

async function activeSequence(ppro) {
  if (!ppro || !ppro.Project) return { error: "Premiere API not reachable" };
  const project = await attempt(() => ppro.Project.getActiveProject());
  if (!project.ok || !project.value) return { error: "no active project" };
  const seq = await attempt(() => project.value.getActiveSequence());
  if (!seq.ok || !seq.value) return { error: "no active sequence" };
  return { seq: seq.value };
}

async function readKind(seq, kind, countFn, getFn) {
  const rows = [];
  if (typeof seq[countFn] !== "function" || typeof seq[getFn] !== "function") {
    return { rows, note: `no ${countFn} on this build` };
  }
  const count = await attempt(() => seq[countFn]());
  if (!count.ok) return { rows, note: count.error };
  for (let i = 0; i < count.value; i++) {
    const track = await attempt(() => seq[getFn](i));
    if (!track.ok || !track.value) { rows.push({ kind, index: i, error: track.error || "no track" }); continue; }
    if (typeof track.value.isMuted !== "function") { rows.push({ kind, index: i, error: "no isMuted on this track" }); continue; }
    const muted = await attempt(() => track.value.isMuted());
    rows.push({ kind, index: i, muted: muted.ok ? muted.value : null, error: muted.ok ? null : muted.error });
  }
  return { rows };
}

async function probeMuteState(ppro) {
  const found = await activeSequence(ppro);
  if (found.error) return { probe: "mute-state", complete: false, error: found.error, tracks: [], notes: [] };
  const { seq } = found;
  const tracks = [];
  const notes = [];
  for (const [kind, countFn, getFn] of [
    ["video", "getVideoTrackCount", "getVideoTrack"],
    ["audio", "getAudioTrackCount", "getAudioTrack"],
    ["caption", "getCaptionTrackCount", "getCaptionTrack"],
  ]) {
    const out = await readKind(seq, kind, countFn, getFn);
    tracks.push(...out.rows);
    if (out.note) notes.push(`${kind}: ${out.note}`);
  }
  const mutedCount = tracks.filter((t) => t.muted === true).length;
  return { probe: "mute-state", complete: true, mutedCount, total: tracks.length, tracks, notes };
}

function formatMuteStateReport(report) {
  if (!report.complete) return `Mute state: ${report.error}.`;
  const lines = report.tracks.map((t) => {
    const name = `${t.kind[0].toUpperCase()}${t.index + 1}`;
    if (t.error) return `  ${name}: could not read (${t.error})`;
    return `  ${name}: ${t.muted ? "MUTED" : "not muted"}`;
  });
  const verdict = report.mutedCount > 0
    ? `${report.mutedCount} of ${report.total} tracks read muted, so isMuted() sees at least some UI mutes. Check these are the ones you muted.`
    : "No track reads muted. If you muted one in Premiere before this run, isMuted() is NOT reliable and Frame Hold can unmute your track. If you muted none, mute a track (M button) and run again.";
  return ["Mute state (read-only):", ...lines, ...report.notes, verdict].join("\n");
}

const dims = (s) => (s ? `${s.width}x${s.height}` : null);

// Names observed in this installed executable's scripting registrations. Inspect
// exposure only: binary registration alone is not permission to call an accessor.
function runtimeGraphicsExports(ppro) {
  const names = new Set([
    ...Object.getOwnPropertyNames(ppro || {}).filter((name) => /graphic|text|layer/i.test(name)),
    "Graphics", "GraphicsTrackItemObject", "GraphicsTrackItem", "TextLayerObject", "TextDocument",
  ]);
  return [{ name: "<module>", type: "module", members: Object.getOwnPropertyNames(ppro || {}) }, ...Array.from(names, (name) => {
    try {
      const value = ppro && ppro[name];
      return { name, type: typeof value,
        members: value && (typeof value === "object" || typeof value === "function")
          ? Object.getOwnPropertyNames(value) : [] };
    } catch (error) {
      return { name, error: String(error) };
    }
  })];
}

async function probeTextCanvas(ppro) {
  const exports = runtimeGraphicsExports(ppro);
  const found = await activeSequence(ppro);
  if (found.error) return { probe: "text-canvas", complete: false, error: found.error, runtimeGraphicsExports: exports };
  const { seq } = found;
  const sel = await attempt(() => seq.getSelection());
  let items = [];
  if (sel.ok && sel.value && typeof sel.value.getTrackItems === "function") {
    const got = await attempt(() => sel.value.getTrackItems());
    items = got.ok && got.value ? got.value : [];
  }
  if (items.length !== 1) {
    return { probe: "text-canvas", complete: false, error: `select exactly one Graphic clip (${items.length} selected)`, runtimeGraphicsExports: exports };
  }
  const item = items[0];
  const graphic = await attempt(() => transformParams.isGraphic(item));
  if (!graphic.ok || !graphic.value) return { probe: "text-canvas", complete: false, error: "the selected clip is not a Graphic" };
  const layers = await attempt(() => transformParams.readGraphicLayers(item));
  const texts = layers.ok && layers.value ? layers.value.texts : [];
  if (texts.length === 0) return { probe: "text-canvas", complete: false, error: "the Graphic has no text layer" };

  const sequenceFrame = await transformParams.readSequenceFrameSize(seq);
  const sourceFrame = await transformParams.readSourceFrameSize(ppro, item);
  const anchorFrame = await transformParams.readAnchorFrameSize(ppro, item, seq);
  const hasProjectItem = typeof item.getProjectItem === "function"
    ? !!(await attempt(() => item.getProjectItem())).value : null;

  const positions = texts.map((t) => {
    const v = t.position && t.position.value;
    const p = Array.isArray(v) ? { x: v[0], y: v[1] } : (v && typeof v === "object" ? { x: v.x, y: v.y } : null);
    return {
      raw: p,
      inSequencePx: p && sequenceFrame ? { x: p.x * sequenceFrame.width, y: p.y * sequenceFrame.height } : null,
      inCanvasPx: p && anchorFrame ? { x: p.x * anchorFrame.width, y: p.y * anchorFrame.height } : null,
    };
  });
  const routesDiffer = !!(sequenceFrame && anchorFrame
    && (sequenceFrame.width !== anchorFrame.width || sequenceFrame.height !== anchorFrame.height));
  return {
    probe: "text-canvas", complete: true, clipHasProjectItem: hasProjectItem,
    runtimeGraphicsExports: exports,
    sequenceFrame: dims(sequenceFrame), projectItemSize: dims(sourceFrame), canvasUsedByShiftRoutes: dims(anchorFrame),
    routesDiffer, positions,
  };
}

function formatTextCanvasReport(report) {
  if (!report.complete) return `Text canvas: ${report.error}.`;
  const px = (v) => (v ? `${v.x.toFixed(1)}, ${v.y.toFixed(1)}` : "?");
  const rows = report.positions.map((p, i) => (p.raw
    ? `  text ${i + 1}: raw ${p.raw.x.toFixed(4)}, ${p.raw.y.toFixed(4)} | sequence px ${px(p.inSequencePx)} | canvas px ${px(p.inCanvasPx)}`
    : `  text ${i + 1}: position unreadable`));
  const verdict = report.routesDiffer
    ? "The two routes use DIFFERENT sizes for this Graphic. Compare the pixel pairs above with the Position Properties shows for the text: the pair that matches is the right unit, and the other route in align.js is wrong."
    : "Both routes use the same size for this Graphic, so the inconsistency in align.js has no effect here. Try a Graphic that has a project item (a .mogrt or a Graphic from a bin) to be sure.";
  return ["Text canvas (read-only):",
    `  sequence ${report.sequenceFrame} | project item ${report.projectItemSize || "none"} | canvas used by shift routes ${report.canvasUsedByShiftRoutes}`,
    ...rows, verdict].join("\n");
}

const ticksOf = (t) => (t && t.ticks !== undefined ? String(t.ticks) : null);

async function readCaptionItems(track, ppro) {
  const clipType = ppro.Constants && ppro.Constants.TrackItemType ? ppro.Constants.TrackItemType.CLIP : 1;
  const got = await attempt(() => track.getTrackItems(clipType, false));
  if (!got.ok) return { error: got.error };
  const items = [];
  for (const item of (got.value || []).filter((it) => it != null)) {
    if (typeof item.getStartTime !== "function" || typeof item.getEndTime !== "function") {
      return { error: "caption items have no getStartTime/getEndTime", members: Object.getOwnPropertyNames(Object.getPrototypeOf(item) || item) };
    }
    const start = await attempt(() => item.getStartTime());
    const end = await attempt(() => item.getEndTime());
    if (!start.ok || !end.ok) return { error: start.error || end.error };
    items.push({ start_ticks: ticksOf(start.value), end_ticks: ticksOf(end.value) });
  }
  items.sort((a, b) => (BigInt(a.start_ticks) < BigInt(b.start_ticks) ? -1 : 1));
  return { items };
}

async function probeCaptionTiming(ppro) {
  const found = await activeSequence(ppro);
  if (found.error) return { probe: "caption-timing", complete: false, error: found.error };
  const { seq } = found;
  const tpf = await attempt(() => seq.getTimebase());
  if (!tpf.ok) return { probe: "caption-timing", complete: false, error: `getTimebase: ${tpf.error}` };
  const count = await attempt(() => seq.getCaptionTrackCount());
  if (!count.ok) return { probe: "caption-timing", complete: false, error: count.error };
  const tracks = [];
  for (let i = 0; i < count.value; i++) {
    const track = await attempt(() => seq.getCaptionTrack(i));
    tracks.push({ index: i, ...(track.ok && track.value ? await readCaptionItems(track.value, ppro) : { error: track.error || "no track" }) });
  }
  return { probe: "caption-timing", complete: true, sequence_name: seq.name, ticks_per_frame: String(tpf.value), tracks };
}

function formatCaptionTimingReport(report) {
  if (!report.complete) return `Caption timing: ${report.error}.`;
  if (report.tracks.length === 0) return "Caption timing: this sequence has no caption track. Drag the SRT onto the timeline first.";
  const tpf = BigInt(report.ticks_per_frame);
  const lines = report.tracks.map((t) => {
    if (t.error) return `  C${t.index + 1}: could not read (${t.error})`;
    if (t.items.length === 0) return `  C${t.index + 1}: no captions`;
    const first = t.items[0], last = t.items[t.items.length - 1];
    return `  C${t.index + 1}: ${t.items.length} captions, frames ${BigInt(first.start_ticks) / tpf}-${BigInt(last.end_ticks) / tpf}`;
  });
  return ["Caption timing (read-only):", ...lines,
    "Compare with the SRT: python -m tools.srt_roundtrip <file.srt> --fps <rate>"].join("\n");
}

module.exports = { probeMuteState, formatMuteStateReport, probeTextCanvas, formatTextCanvasReport,
  probeCaptionTiming, formatCaptionTimingReport };
