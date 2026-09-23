/* Exact timeline arithmetic for native assembly. No Premiere calls live here.

   Premiere counts time in ticks: 254016000000 per second, chosen so that every
   broadcast frame rate divides it exactly (29.97 = 8475667200 ticks/frame,
   23.976 = 10594584000, 25 = 10160640000).

   Every value here is a BigInt, parsed from and serialized back to a decimal string
   at each host and storage boundary. Two honest reasons, neither of them "Number
   overflows" — measured, a frame-aligned tick value survives a Number round trip
   through TickTime.seconds to within 4 ticks even at 37 hours (a frame is 8.4
   billion ticks), and fifty accumulated adds drift by zero:

   1. Off-grid tick values above 2^53 lose their identity outright. Frame-aligned
      values carry a 2^8 factor and stay representable; a media In point from a
      source on a different time base does not, and `v + 1` silently becomes `v`.
   2. Exactness becomes checkable. `span % ticksPerFrame !== 0n` is a real assertion
      that catches a rounding introduced upstream. In floats the same check is
      meaningless, so the drift this module exists to prevent could not be detected
      even in principle.

   Nothing is ever rounded: frames are a display and verification unit, ticks are
   the unit of record. Section 6 of the handoff mandates the same rule.

   See docs/HANDOFF_CUTDECK_TIMELINE_IN_OUT.md section 6. */

const { TICKS_PER_SECOND, toTicks } = require("./host/ticks.js");
const ticks = toTicks;

/* Premiere's Out point convention is UNVERIFIED on this host.

   Adobe's reference does not say whether Sequence.getOutPoint() names the last
   included frame or the first excluded one, and the difference is exactly one
   frame on every single add — invisible on one clip and obvious after fifty. It
   is probe 1 of the Phase 0 spike (assemblyProbe.js). Until that probe has run on
   a real build, this stays null and normalizeSelection() refuses rather than
   guessing, so no code path can silently pick a convention. */
const OUT_CONVENTION = null;
const OUT_CONVENTIONS = ["exclusive", "inclusive"];

const serialize = (value) => value.toString();

/* Frames are exact or they are a bug: a mark that does not land on a frame
   boundary means the tick value came from somewhere that rounded. */
function toFrames(span, ticksPerFrame, what) {
  if (ticksPerFrame <= 0n) throw new Error("Sequence timebase is not a positive tick count.");
  if (span % ticksPerFrame !== 0n) {
    throw new Error(`${what || "Span"} is not a whole number of frames (${span} ticks at ${ticksPerFrame} ticks/frame).`);
  }
  return span / ticksPerFrame;
}

/* Turns the host's raw marks into the half-open interval the rest of the code uses.
   Returns tick BigInts plus decimal strings, so callers persist without reformatting. */
function normalizeSelection(raw) {
  const convention = raw.outConvention === undefined ? OUT_CONVENTION : raw.outConvention;
  if (!OUT_CONVENTIONS.includes(convention)) {
    throw new Error(
      "Premiere's Out point convention has not been verified on this build. " +
      "Run the CutDeck capability probe (Phase 0, probe 1) and set OUT_CONVENTION in timelineRange.js from its result.");
  }
  if (raw.inTicks === null || raw.inTicks === undefined || raw.outTicks === null || raw.outTicks === undefined) {
    throw new Error("Mark In and Out on your source timeline.");
  }
  const ticksPerFrame = ticks(raw.ticksPerFrame, "Sequence timebase");
  if (ticksPerFrame <= 0n) throw new Error("Sequence timebase is not a positive tick count.");

  const inTicks = ticks(raw.inTicks, "In point");
  const rawOut = ticks(raw.outTicks, "Out point");
  const outExclusiveTicks = convention === "inclusive" ? rawOut + ticksPerFrame : rawOut;

  if (inTicks < 0n) throw new Error("In point is before the start of the sequence.");
  if (outExclusiveTicks <= inTicks) throw new Error("Out point is not after the In point. Re-mark the range.");
  if (raw.endTicks !== null && raw.endTicks !== undefined) {
    const endTicks = ticks(raw.endTicks, "Sequence end");
    if (outExclusiveTicks > endTicks) throw new Error("Out point is past the end of the sequence.");
  }

  const frames = toFrames(outExclusiveTicks - inTicks, ticksPerFrame, "Marked range");
  return {
    inTicks, outExclusiveTicks, ticksPerFrame, frames,
    durationTicks: outExclusiveTicks - inTicks,
    in: serialize(inTicks), outExclusive: serialize(outExclusiveTicks),
    outConvention: convention,
  };
}

module.exports = {
  TICKS_PER_SECOND, OUT_CONVENTION, OUT_CONVENTIONS,
  ticks, serialize, toFrames, normalizeSelection,
};
