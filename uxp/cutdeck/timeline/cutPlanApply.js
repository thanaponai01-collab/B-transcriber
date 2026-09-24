// Pure planning for the native rough cut — no host APIs, no DOM.
// Turns the helper's cut list (sequence frames) plus the clone's clip items into the
// per-item edits Route A applies, and the read-back it must see afterwards.
// Ports cutdeck/xml_recut.py's _keep_subranges / _shift_for_frame / _process_track case
// table to exact BigInt ticks. See docs/HANDOFF_CUTDECK_NATIVE_ROUGH_CUT.md 3.2.

const { TICKS_PER_SECOND, toTicks } = require("../host/ticks.js");

// Helper cuts (frames) -> ticks. Refuses when the helper analysed a different frame
// grid than the live sequence has, replacing the XML route's DurationMismatch guard.
function cutsToTicks(cutsJson, sequenceTicksPerFrame) {
  const tpf = toTicks(cutsJson && cutsJson.ticks_per_frame, "helper ticks_per_frame");
  const live = toTicks(sequenceTicksPerFrame, "sequence ticks per frame");
  if (tpf <= 0n || tpf !== live) {
    throw new Error(`Cut list was built at ${tpf} ticks/frame but the sequence is ${live}; start a new rough cut`);
  }
  const cuts = (cutsJson.cuts_frames || []).map(([a, b]) => [BigInt(a) * tpf, BigInt(b) * tpf]);
  for (let i = 0; i < cuts.length; i++) {
    const [a, b] = cuts[i];
    if (a < 0n || b <= a) throw new Error(`Cut ${i + 1} is empty or negative`);
    if (i > 0 && a < cuts[i - 1][1]) throw new Error(`Cut ${i + 1} overlaps or precedes cut ${i}`);
  }
  return cuts;
}

// Total ticks removed before `t` (a point inside a cut shifts to the cut's start).
function shiftFor(t, cuts) {
  let shift = 0n;
  for (const [a, b] of cuts) {
    if (b <= t) shift += b - a;
    else if (a < t) shift += t - a;
  }
  return shift;
}

// [start, end) minus every overlapping cut, as the surviving sub-ranges in order.
function keepSubranges(start, end, cuts) {
  const kept = [];
  let cursor = start;
  for (const [a, b] of cuts) {
    if (b <= cursor || a >= end) continue;
    if (a > cursor) kept.push([cursor, a < end ? a : end]);
    if (b > cursor) cursor = b;
    if (cursor >= end) break;
  }
  if (cursor < end) kept.push([cursor, end]);
  return kept;
}

function overlapsCut(start, end, cuts) {
  return cuts.some(([a, b]) => a < end && b > start);
}

function timecode(t) {
  const ms = (t * 1000n) / TICKS_PER_SECOND;
  const s = ms / 1000n;
  const pad = (v, n = 2) => String(v).padStart(n, "0");
  return `${pad(s / 3600n)}:${pad((s / 60n) % 60n)}:${pad(s % 60n)}.${pad(ms % 1000n, 3)}`;
}

// Why an item a cut lands inside can't be trimmed natively, or null. Items wholly
// outside every cut only move, which is safe whatever they are.
function unsupportedReason(item) {
  if (item.isTransition) return "a transition";
  if (item.isNested) return "a nested sequence";
  if (item.isMulticam) return "a multicam clip";
  if (item.reversed) return "reversed";
  if (item.speed !== undefined && item.speed !== 1) return `at ${item.speed * 100}% speed`;
  return null;
}

// items: [{ id, name, mediaType: "video"|"audio", track, startTicks, endTicks, inTicks,
//           speed?, reversed?, isTransition?, isNested?, isMulticam? }] — sequence-time
// start/end, media-relative in. Whole-plan refusal before any edit: returns
// { refusal } naming the clip and timecode, else { edits, removedTicks }.
// Each edit: { id, op: "keep"|"move"|"trim"|"remove"|"split", pieces } where every
// piece is { startTicks, endTicks, inTicks } at its *final* position.
function planCutApply(items, cuts) {
  for (const item of items) {
    const start = toTicks(item.startTicks), end = toTicks(item.endTicks);
    if (!overlapsCut(start, end, cuts)) continue;
    const why = unsupportedReason(item);
    if (why) {
      return { refusal: `${item.name || "clip"} (${item.mediaType} track ${item.track + 1}) at ${timecode(start)}-${timecode(end)} is ${why} and a cut lands inside it — refusing` };
    }
  }
  const edits = items.map((item) => {
    const start = toTicks(item.startTicks), end = toTicks(item.endTicks), mediaIn = toTicks(item.inTicks);
    const keeps = overlapsCut(start, end, cuts) ? keepSubranges(start, end, cuts) : [[start, end]];
    const pieces = keeps.map(([s, e]) => ({
      startTicks: s - shiftFor(s, cuts),
      endTicks: e - shiftFor(e, cuts),
      inTicks: mediaIn + (s - start),
    }));
    let op;
    if (pieces.length === 0) op = "remove";
    else if (pieces.length > 1) op = "split";
    else if (keeps[0][0] !== start || keeps[0][1] !== end) op = "trim";
    else op = pieces[0].startTicks === start ? "keep" : "move";
    return { id: item.id, op, pieces };
  });
  const removedTicks = cuts.reduce((sum, [a, b]) => sum + (b - a), 0n);
  return { edits, removedTicks };
}

// Read-back check: every planned piece must exist exactly (0-tick tolerance) on its
// item's track, and nothing unplanned may remain. actual: same shape as items.
// Returns human-readable mismatches; empty means the apply is proven.
function verifyReadBack(items, plan, actual) {
  const key = (it, p) => `${it.mediaType}|${it.track}|${p.startTicks}|${p.endTicks}|${p.inTicks}`;
  const expected = new Map();
  items.forEach((item, i) => {
    for (const p of plan.edits[i].pieces) {
      const k = key(item, p);
      const prev = expected.get(k);
      expected.set(k, { name: item.name || "clip", item, p, n: (prev ? prev.n : 0) + 1 });
    }
  });
  const problems = [];
  for (const a of actual) {
    const k = key(a, { startTicks: toTicks(a.startTicks), endTicks: toTicks(a.endTicks), inTicks: toTicks(a.inTicks) });
    const e = expected.get(k);
    if (e && e.n > 0) e.n -= 1;
    else problems.push(`unexpected ${a.name || "clip"} on ${a.mediaType} track ${a.track + 1} at ${timecode(toTicks(a.startTicks))}`);
  }
  for (const e of expected.values()) {
    if (e.n > 0) problems.push(`missing ${e.name} on ${e.item.mediaType} track ${e.item.track + 1} at ${timecode(e.p.startTicks)}`);
  }
  return problems;
}

module.exports = { cutsToTicks, shiftFor, keepSubranges, overlapsCut, planCutApply, verifyReadBack };
