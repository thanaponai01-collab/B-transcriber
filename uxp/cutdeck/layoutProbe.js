/* Read-only probes for two questions PREMIERE_FACTS still lists as unproven.
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

async function probeTextCanvas(ppro) {
  const found = await activeSequence(ppro);
  if (found.error) return { probe: "text-canvas", complete: false, error: found.error };
  const { seq } = found;
  const sel = await attempt(() => seq.getSelection());
  let items = [];
  if (sel.ok && sel.value && typeof sel.value.getTrackItems === "function") {
    const got = await attempt(() => sel.value.getTrackItems());
    items = got.ok && got.value ? got.value : [];
  }
  if (items.length !== 1) {
    return { probe: "text-canvas", complete: false, error: `select exactly one Graphic clip (${items.length} selected)` };
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

module.exports = { probeMuteState, formatMuteStateReport, probeTextCanvas, formatTextCanvasReport };
