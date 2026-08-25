/*
 * CutDeck spike #18 -- split probe.
 *
 * Best-effort implementation of a split, staged as: clone the *untouched*
 * item first, then trim the original's end back to the cut point, then
 * correct the clone's start/in-point forward to the same cut point. Issue
 * #18 phrases the recipe as "trim first, then clone, then correct the
 * clone" -- this file clones first instead, deliberately, so the clone
 * inherits the original's untouched end/out-point (the tail must keep the
 * original's real end; cloning after trimming would hand the tail a
 * pre-truncated one that then needs correcting right back). Record on the
 * issue whether trim-then-clone also works and which order Premiere prefers.
 *
 * The one genuinely unknown step either way is what
 * createCloneTrackItemAction() hands back -- a chainable TrackItem, or just
 * an Action descriptor with no item reference until the transaction
 * commits. This file checks which one it got (duck-typing the return value)
 * and logs the answer loudly instead of assuming. See README.md.
 *
 * Adobe's premierepro-types (github.com/adobe/premierepro-types) types
 * createCloneTrackItemAction() as returning bare `Action` (an opaque `{}`
 * type with no methods) -- a documented hint that the fallback branch below
 * is the one to expect, not proof: this project has hit real doc/runtime
 * mismatches before (the manifest schema fields it initially copied from
 * memory were wrong too), so the duck-type check stays live rather than
 * being replaced with an assumption. That same source is also where
 * createCloneTrackItemAction() itself was found to live on `SequenceEditor`
 * (`ppro.SequenceEditor.getEditor(sequence)`), not a `ppro.TrackItem`
 * static -- there is no such export at all.
 *
 * All executeTransaction() calls run inside project.lockedAccess() --
 * confirmed as the required pattern (2026-08-25) by diffing against Adobe's
 * own official sample (AdobeDocs/uxp-premiere-pro-samples,
 * sample-panels/premiere-api/src/sequenceEditor.ts) and an independent
 * third-party UXP Premiere plugin (leancoderkavy/premiere-pro-mcp, which
 * enforces it via a dedicated eslint rule,
 * @adobe/premierepro/prefer-locked-access-wrapper) -- both call
 * executeTransaction only from inside lockedAccess(), never bare, which
 * this file was doing until now. Neither source ever chains a further
 * create*Action call off createCloneTrackItemAction()'s return value either
 * -- independent corroboration (not just the type signature) that the
 * duck-type "happy path" below is expected to lose to the fallback branch.
 *
 * All frame math here is plain JS seconds arithmetic (offset-from-clip-start
 * in, offset-from-clip-start out), not transcribe/timebase.py's tick-exact
 * rounding -- this file is throwaway spike code with no Python dependency,
 * never wired into cutdeck/mark_export.py or bridge.py. It also assumes
 * speed=1 on the target clip; it does not check for speed changes or VFR
 * (out of scope for a one-button spike against a known test clip).
 *
 * Cut points A and B are read from the sequence's own marked in/out points
 * (Sequence.getInPoint()/getOutPoint() -- the ones set with I/O on the
 * timeline), not typed in by hand: the spike must only ever touch the work
 * area the editor marked, matching the real plugin's eventual behaviour.
 */

let ppro;
try {
  ppro = require("premierepro");
} catch (e) {
  // require() itself should not fail inside a real UXP host: if it does,
  // the plugin isn't running where it thinks it is.
  ppro = null;
}

const logEl = document.getElementById("log");

function log(msg) {
  const line = typeof msg === "string" ? msg : describe(msg);
  console.log("[spike18]", line);
  logEl.textContent += line + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

function describe(value) {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value !== "object") return String(value);
  const proto = Object.getPrototypeOf(value);
  const ctorName = proto && proto.constructor ? proto.constructor.name : "?";
  const ownKeys = Object.keys(value);
  const protoMethods = proto ? Object.getOwnPropertyNames(proto).filter((k) => k !== "constructor") : [];
  return `[object ${ctorName}] ownKeys=${JSON.stringify(ownKeys)} protoMethods=${JSON.stringify(protoMethods)}`;
}

// TickTime objects are assumed to expose `.seconds` (read) and to be built
// via `ppro.TickTime.createWithSeconds(n)` (write) -- both unverified against
// a live host. If `.seconds` doesn't exist, this logs every enumerable
// property it does find so the real accessor name is a one-line reconnect
// away rather than a guessing game restarted from zero.
function toSeconds(tickTime, label) {
  if (tickTime && typeof tickTime.seconds === "number") return tickTime.seconds;
  if (tickTime && typeof tickTime.getSeconds === "function") return tickTime.getSeconds();
  log(`WARNING: could not read seconds from ${label}: ${describe(tickTime)}`);
  throw new Error(`toSeconds() failed for ${label} -- see log for its actual shape`);
}

function fromSeconds(seconds) {
  return ppro.TickTime.createWithSeconds(seconds);
}

// Calls obj[methodName]() if it exists, else reads the bare obj[propName],
// else throws -- the "unverified getter spelling" shape this file needs
// everywhere it touches a live Premiere object.
async function callOrProp(obj, methodName, propName, label) {
  if (typeof obj[methodName] === "function") return await obj[methodName]();
  if (obj[propName] !== undefined) return obj[propName];
  log(`WARNING: neither ${methodName}() nor .${propName} exists on ${label}: ${describe(obj)}`);
  throw new Error(`neither ${methodName}() nor .${propName} exists on ${label} -- see log above for its actual shape`);
}

// Reads start/end/inPoint/outPoint via callOrProp, trying the getter
// spelling first (matches the rest of issue #17's documented API).
async function readTimes(item, label) {
  const start = await callOrProp(item, "getStartTime", "startTime", label);
  const end = await callOrProp(item, "getEndTime", "endTime", label);
  const inPoint = await callOrProp(item, "getInPoint", "inPoint", label);
  const outPoint = await callOrProp(item, "getOutPoint", "outPoint", label);
  const result = {
    startSec: toSeconds(start, `${label}.start`),
    endSec: toSeconds(end, `${label}.end`),
    inSec: toSeconds(inPoint, `${label}.inPoint`),
    outSec: toSeconds(outPoint, `${label}.outPoint`),
  };
  log(`${label}: start=${result.startSec.toFixed(3)}s end=${result.endSec.toFixed(3)}s ` +
      `in=${result.inSec.toFixed(3)}s out=${result.outSec.toFixed(3)}s`);
  return result;
}

// Reads the sequence's work-area in/out points (the ones set with I/O on
// the timeline, via Sequence.getInPoint()/getOutPoint()) -- unverified
// against a live host, same as everything else in this file. Falls back to
// the bare property the same way readTimes() does.
async function readSequenceInOut(sequence) {
  const inPoint = await callOrProp(sequence, "getInPoint", "inPoint", "sequence");
  const outPoint = await callOrProp(sequence, "getOutPoint", "outPoint", "sequence");
  const result = {
    inSec: toSeconds(inPoint, "sequence.inPoint"),
    outSec: toSeconds(outPoint, "sequence.outPoint"),
  };
  log(`sequence in/out: in=${result.inSec.toFixed(3)}s out=${result.outSec.toFixed(3)}s`);
  return result;
}

async function getFirstItem(sequence, kind) {
  // kind: "video" | "audio"
  const track =
    kind === "video" ? await sequence.getVideoTrack(0) : await sequence.getAudioTrack(0);
  if (!track) throw new Error(`sequence has no ${kind} track 0`);
  // Track has no item-count/item-by-index API (confirmed against Adobe's
  // premierepro-types after the first live run failed here) -- getTrackItems()
  // returns the whole array in one call. Also confirmed (2026-08-25, diffing
  // the same source): declared synchronous (returns the array directly, not
  // a Promise) on both VideoTrack and AudioTrack -- the `await` here is a
  // harmless no-op on an already-resolved value, kept only for uniformity
  // with the rest of this file's async call sites.
  const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
  if (!items || items.length < 1) throw new Error(`${kind} track 0 has no clips`);
  return { track, item: items[0] };
}

// Diagnostic-only: lists every clip item currently on `track`, logging
// start/end/in/out/disabled for each. No mutation. Used to observe what a
// clone actually produced, rather than assuming.
async function logTrackItems(track, label) {
  const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
  log(`${label}: ${items.length} clip item(s) on track`);
  for (let i = 0; i < items.length; i++) {
    const info = await readTimes(items[i], `${label}[${i}]`);
    const disabled = typeof items[i].isDisabled === "function" ? await items[i].isDisabled() : "?";
    log(`  [${i}] start=${info.startSec.toFixed(3)}s end=${info.endSec.toFixed(3)}s ` +
        `in=${info.inSec.toFixed(3)}s out=${info.outSec.toFixed(3)}s disabled=${disabled}`);
  }
  return items;
}

/**
 * Stages one split inside an already-open compound action.
 *
 * headItem is the (pre-trim) item to split; headInfo is its {startSec,
 * endSec, inSec, outSec} as read BEFORE this function touches anything.
 * offsetSec is the cut point, in seconds from headItem's *own* current
 * start (matches the "seconds from clip start" label on the A/B inputs for
 * the first split; for the second split the caller passes the offset from
 * the *tail's* start the same way).
 *
 * Returns the tail item handle if the clone call handed one back, else null
 * (caller must abort the transaction in that case -- there's nothing to
 * chain the second split or the disable action onto).
 *
 * sequenceEditor is `ppro.SequenceEditor.getEditor(sequence)` -- clone lives
 * there, not on a `ppro.TrackItem` static (that namespace doesn't exist;
 * confirmed against Adobe's premierepro-types after the original guess had
 * never been reached by a live run).
 */
function stageSplit(compoundAction, sequenceEditor, headItem, headInfo, offsetSec, label) {
  log(`--- staging split "${label}" at +${offsetSec}s from clip start ---`);

  const cloneResult = sequenceEditor.createCloneTrackItemAction(
    headItem,
    fromSeconds(0), // timeOffset -- zero: clone lands exactly on top of headItem
    0, // videoTrackVerticalOffset
    0, // audioTrackVerticalOffset
    false, // alignToVideo
    false // isInsert -- false so it doesn't ripple the timeline
  );
  log(`clone call returned: ${describe(cloneResult)}`);

  let tailItem = null;
  if (cloneResult && typeof cloneResult.createSetStartAction === "function") {
    // Looks like a TrackItem-shaped handle we can chain further create*Action
    // calls onto directly. Still unclear whether the clone mutation itself
    // needs staging via addAction() or is registered implicitly by virtue of
    // executing inside the transaction callback -- try staging it too; if
    // it's not a valid Action, addAction() should throw and that's fine,
    // it just means the clone was already implicit.
    try {
      compoundAction.addAction(cloneResult);
      log("clone result also accepted by compoundAction.addAction() -- treating it as needing explicit staging.");
    } catch (e) {
      log(`compoundAction.addAction(cloneResult) threw (expected if the clone is implicit): ${e}`);
    }
    tailItem = cloneResult;
  } else if (cloneResult) {
    // Looks like a bare Action descriptor instead -- stage it, but we have
    // no item reference to chain a trim onto inside this same transaction.
    try {
      compoundAction.addAction(cloneResult);
    } catch (e) {
      log(`compoundAction.addAction(cloneResult) threw: ${e}`);
    }
    log('WARNING: clone did not hand back a chainable item -- cannot stage ' +
        'the tail trim or the disable action in this transaction. See ' +
        'README.md "If the clone does not hand back an item".');
    return null;
  } else {
    throw new Error(`createCloneTrackItemAction returned ${cloneResult}`);
  }

  const cutAbsSec = headInfo.startSec + offsetSec;
  const cutMediaSec = headInfo.inSec + offsetSec;

  // Trim the head: sequence end and media out-point both move to the cut.
  compoundAction.addAction(headItem.createSetEndAction(fromSeconds(cutAbsSec)));
  if (typeof headItem.createSetOutPointAction === "function") {
    compoundAction.addAction(headItem.createSetOutPointAction(fromSeconds(cutMediaSec)));
  } else {
    log(`WARNING: headItem has no createSetOutPointAction -- out-point left unset, ` +
        `check for a differently-named equivalent before trusting frame accuracy.`);
  }

  // Correct the tail (clone): sequence start and media in-point both move
  // to the cut, keeping outSec/endSec at whatever the clone inherited
  // (the untrimmed original's values) -- correct for a plain split.
  compoundAction.addAction(tailItem.createSetStartAction(fromSeconds(cutAbsSec)));
  if (typeof tailItem.createSetInPointAction === "function") {
    compoundAction.addAction(tailItem.createSetInPointAction(fromSeconds(cutMediaSec)));
  } else {
    log(`WARNING: tailItem has no createSetInPointAction -- in-point left unset, ` +
        `check for a differently-named equivalent before trusting frame accuracy.`);
  }

  log(`split "${label}" staged: head now [${headInfo.startSec.toFixed(3)}, ${cutAbsSec.toFixed(3)}], ` +
      `tail now [${cutAbsSec.toFixed(3)}, ${headInfo.endSec.toFixed(3)}]`);

  return { tailItem, cutAbsSec, cutMediaSec, tailEndSec: headInfo.endSec, tailOutSec: headInfo.outSec };
}

async function runSpike(kind) {
  if (!ppro) {
    log("ERROR: require('premierepro') failed -- not running inside a Premiere UXP host?");
    return;
  }

  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error("no active project");
    const sequence = await project.getActiveSequence();
    if (!sequence) throw new Error("no active sequence");

    const inOut = await readSequenceInOut(sequence);

    const { track, item: headItem } = await getFirstItem(sequence, kind);
    log(`found first ${kind} clip:`);
    const headInfo = await readTimes(headItem, "original clip");

    // Cut points come from the sequence's marked in/out, not typed times --
    // the whole point is that this spike (and the real plugin it feeds)
    // never touches anything outside the work area the editor marked.
    // Expressed as offsets from the clip's own start, same units stageSplit()
    // already expects.
    const aSec = inOut.inSec - headInfo.startSec;
    const bSec = inOut.outSec - headInfo.startSec;
    if (!(aSec >= 0) || !(bSec > aSec) || bSec > headInfo.endSec - headInfo.startSec) {
      log(`ERROR: sequence in/out (${inOut.inSec.toFixed(3)}s-${inOut.outSec.toFixed(3)}s) ` +
          `does not fall inside this clip's span (${headInfo.startSec.toFixed(3)}s-` +
          `${headInfo.endSec.toFixed(3)}s). Mark an in/out point that lands entirely ` +
          `within the target clip and try again.`);
      return;
    }

    const sequenceEditor = ppro.SequenceEditor.getEditor(sequence);
    if (!sequenceEditor) throw new Error("SequenceEditor.getEditor(sequence) returned nothing");

    // ROUND 4 (2026-08-25): the full clone+trim split (round 3's stageSplit
    // path, still defined above but unused below for now) is confirmed dead
    // as designed -- round 3's live run got past the "script object is no
    // longer valid" crash (fixed by the lockedAccess wrap) and hit the
    // predicted fallback: createCloneTrackItemAction() succeeds but returns
    // a bare, non-chainable Action (ownKeys=[] protoMethods=[]), so there is
    // no item reference to trim/disable inside the same transaction. The
    // code correctly aborted with nothing committed -- safe, but a dead end
    // for a single-transaction design.
    //
    // What's still unknown, and the only thing this round tests: what does
    // a same-track, zero-time-offset, isInsert=false (overwrite) clone
    // actually produce once it's allowed to commit? Nobody has verified
    // this -- Adobe's own sample only clones to a *different* track with a
    // nonzero time offset and isInsert=true. Guessing the two-transaction
    // redesign (commit clone+head-trim, re-query the track for the new
    // item, commit a second transaction to finish it) on top of that
    // unknown would risk building on a wrong assumption about clone's
    // geometry. So this round stages ONLY the clone (no trims) inside one
    // transaction, commits it for real, then re-lists the track's items
    // right after with logTrackItems() -- diagnostic only, answers the
    // actual open question before any more split logic gets written.
    //
    // Re-fetch right before use, kept from round 2/3's fix.
    const { item: freshHeadItem } = await getFirstItem(sequence, kind);

    await logTrackItems(track, "BEFORE clone");

    let cloneResult = null;
    let txResult = null;

    // ROUND 5 (2026-08-25): round 4's live run showed executeTransaction
    // returning true (committed, no throw) but the track still had exactly
    // 1 item, byte-identical to before (same start/end/in/out). A zero-
    // offset, same-track, isInsert=false clone is a no-op -- "overwrite"
    // really does mean the clone replaces the original in place rather than
    // coexisting with it. One variable changed from round 4: a large,
    // deliberately out-of-clip-range timeOffset (1 hour past the clip's own
    // start) so the clone lands on empty track space with nothing to
    // overwrite. This only tests whether a nonzero-offset clone produces a
    // genuine second item at all -- not yet where the real split's tail
    // needs to end up; that's a later round once an item reference can be
    // obtained post-commit.
    const PROBE_OFFSET_SEC = 3600;

    project.lockedAccess(() => {
      // executeTransaction's type signature returns `boolean` synchronously,
      // not `Promise<boolean>` (confirmed against premierepro.d.ts).
      txResult = project.executeTransaction((compoundAction) => {
        cloneResult = sequenceEditor.createCloneTrackItemAction(
          freshHeadItem,
          fromSeconds(PROBE_OFFSET_SEC), // timeOffset -- nonzero, lands well past the clip's own end
          0, // videoTrackVerticalOffset -- zero: same track
          0, // audioTrackVerticalOffset -- zero: same track
          false, // alignToVideo
          false // isInsert -- false (overwrite), now onto empty space instead of the original's own span
        );
        log(`clone call returned: ${describe(cloneResult)}`);
        if (!compoundAction.addAction(cloneResult)) {
          throw new Error("compoundAction.addAction(cloneResult) returned false -- aborting, nothing should commit.");
        }
      }, `CutDeck spike18: clone-only probe (${kind}), offset +${PROBE_OFFSET_SEC}s`);
    });

    log(`executeTransaction returned: ${describe(txResult)}`);

    const afterItems = await logTrackItems(track, "AFTER clone");
    log(`item count: before vs after -- see logs above. ` +
        (afterItems.length > 1
          ? "More than one item now -- inspect their start/end above to see where the clone landed relative to the original."
          : "Still one item -- either the clone was rejected, or it overwrote the original in place (same span, no duplicate)."));
    log("Diagnostic finished -- do NOT click again on this clip yet. Record the " +
        "before/after item list on issue #18, then press Ctrl+Z to undo before " +
        "trying anything else.");
  } catch (e) {
    log(`FAILED: ${e && e.message ? e.message : e}`);
    if (e && e.stack) log(e.stack);
  }
}

// Dual-fallback pattern (navigator.clipboard first, uxp module's clipboard
// second) confirmed against a real live Premiere UXP plugin
// (rtwoo/soundscape-generator, aisoundscapes_premiere_plugin/main.js) rather
// than assumed -- this file has been burned by unverified API guesses
// before.
async function copyLog() {
  const text = logEl.textContent;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else if (require("uxp").clipboard) {
      require("uxp").clipboard.copyText(text);
    } else {
      throw new Error("no clipboard API available (neither navigator.clipboard nor uxp.clipboard)");
    }
    log("--- log copied to clipboard ---");
  } catch (e) {
    log(`FAILED to copy log: ${e && e.message ? e.message : e}`);
  }
}

document.getElementById("runVideo").addEventListener("click", () => runSpike("video"));
document.getElementById("runAudio").addEventListener("click", () => runSpike("audio"));
document.getElementById("copyLog").addEventListener("click", copyLog);
