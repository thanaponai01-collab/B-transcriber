/* Pure range intersection and destination placement. No Premiere calls, no I/O.

   Implements docs/HANDOFF_CUTDECK_TIMELINE_IN_OUT.md section 6 exactly:

     overlapStart = max(S, I)          destinationStart = D + overlapStart - I
     overlapEnd   = min(E, O)          destinationEnd   = D + overlapEnd   - I
     include item only when overlapEnd > overlapStart
     nextAppendCursor = D + O - I

   The cursor advances by the whole marked interval, not by the last clip's end, so
   a trailing gap inside the marks is preserved rather than eaten. Nothing here
   rounds: every value is ticks, so repeated adds cannot accumulate drift. */

const { ticks, serialize, toFrames } = require("./timelineRange.js");

const max = (a, b) => (a > b ? a : b);
const min = (a, b) => (a < b ? a : b);

/* Section 8's supported subset: ordinary forward 1x clips. The media-In equation
   below is only true at speed 1 forward, so anything else is refused before any
   mutation rather than placed wrongly. */
function unsupportedReason(item) {
  if (item.reversed) return "plays in reverse";
  if (item.speed !== undefined && item.speed !== null && Number(item.speed) !== 1) {
    return `has a speed change (${item.speed}x)`;
  }
  if (Array.isArray(item.unsupported) && item.unsupported.length) return item.unsupported.join("; ");
  return null;
}

const describe = (item) => `${item.name || "clip"} on ${item.mediaType || "?"} ${(item.trackIndex ?? "?")}`;

/* selection: the result of normalizeSelection().
   items:     source track items in sequence-timeline ticks, each
              { id, name, mediaType, trackIndex, startTicks, endTicks, mediaInTicks, speed, reversed }.
   appendCursorTicks: D, in destination-timeline ticks.

   Returns a plan. An unsupported plan carries no placements at all — a caller must
   not be able to apply half of a refused range. */
function planAppend(options) {
  const selection = options.selection;
  const D = ticks(options.appendCursorTicks === undefined ? 0 : options.appendCursorTicks, "Append cursor");
  if (D < 0n) throw new Error("Append cursor is before the start of the destination.");
  const I = selection.inTicks;
  const O = selection.outExclusiveTicks;
  const tpf = selection.ticksPerFrame;

  const placements = [];
  const unsupported = [];
  for (const item of options.items || []) {
    const S = ticks(item.startTicks, `Start time of ${describe(item)}`);
    const E = ticks(item.endTicks, `End time of ${describe(item)}`);
    if (E <= S) throw new Error(`${describe(item)} has a non-positive duration; the timeline read is unusable.`);

    const overlapStart = max(S, I);
    const overlapEnd = min(E, O);
    if (overlapEnd <= overlapStart) continue;  // outside the marks, including edge-touching

    const reason = unsupportedReason(item);
    if (reason) { unsupported.push({ id: item.id, name: item.name, mediaType: item.mediaType,
      trackIndex: item.trackIndex, reason }); continue; }

    // Trimming the head of a clip walks its media In forward by the same amount.
    const mediaIn = ticks(item.mediaInTicks === undefined ? 0 : item.mediaInTicks,
      `Media In of ${describe(item)}`) + (overlapStart - S);
    const destinationStart = D + overlapStart - I;
    const destinationEnd = D + overlapEnd - I;
    placements.push({
      id: item.id, name: item.name, mediaType: item.mediaType, trackIndex: item.trackIndex,
      sourceStartTicks: overlapStart, sourceEndTicks: overlapEnd,
      mediaInTicks: mediaIn, mediaOutTicks: mediaIn + (overlapEnd - overlapStart),
      destinationStartTicks: destinationStart, destinationEndTicks: destinationEnd,
      trimmedHead: overlapStart > S, trimmedTail: overlapEnd < E,
      destinationStart: serialize(destinationStart), destinationEnd: serialize(destinationEnd),
      mediaIn: serialize(mediaIn), mediaOut: serialize(mediaIn + (overlapEnd - overlapStart)),
    });
  }

  const nextAppendCursorTicks = D + O - I;
  const base = {
    appendCursorTicks: D, nextAppendCursorTicks,
    appendCursor: serialize(D), nextAppendCursor: serialize(nextAppendCursorTicks),
    durationTicks: O - I, frames: toFrames(O - I, tpf, "Marked range"),
  };
  if (unsupported.length) {
    return { ...base, supported: false, empty: false, placements: [], unsupported };
  }
  placements.sort((a, b) =>
    a.destinationStartTicks === b.destinationStartTicks
      ? (a.mediaType === b.mediaType ? a.trackIndex - b.trackIndex : String(a.mediaType).localeCompare(String(b.mediaType)))
      : (a.destinationStartTicks < b.destinationStartTicks ? -1 : 1));
  return { ...base, supported: true, empty: placements.length === 0, placements, unsupported: [] };
}

module.exports = { planAppend, unsupportedReason };
