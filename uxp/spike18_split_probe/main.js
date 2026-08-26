/*
 * CutDeck spike #18 -- split probe.
 *
 * ROUND 15 (issue #24, 2026-08-26): #18 closed having PROVEN (not just left
 * open) that same-track isInsert=false clone+trim can never produce a
 * correct split -- (start - in) is an invariant of createSetStartAction/
 * createSetInPointAction, permanently fixed at the clone's timeOffset the
 * instant it's created, and no sequence of trim calls can close that gap
 * back to zero (round 13's algebra, confirmed live rounds 4/13/14). That
 * math is a property of the trim actions themselves, independent of how the
 * item was created -- so isInsert=true would hit the identical dead end if
 * the next thing tried were "insert-clone, then one createSetStartAction
 * call to reposition." Not testing that. Filed as its own issue (#24)
 * rather than continuing #18, per #18's own closing comment.
 *
 * What #18 never tested at all, and what round 15 (below, in runSpike())
 * actually probes: basic isInsert=true geometry. Does timeOffset=0 ripple
 * the rest of the track (unlike isInsert=false's confirmed no-op at
 * round 4)? Is the returned clone chainable this time? By how much does
 * anything downstream shift? One variable changed from round 4's own
 * baseline (isInsert: false -> true), clone only, no trims -- same
 * diagnostic-first discipline every round in this file has used since
 * round 4. See the ROUND 15 comment block inside runSpike() and
 * README.md for the full reasoning and how to record the result on #24.
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

// Synchronous twin of callOrProp() -- needed inside executeTransaction()'s
// callback, which is declared synchronous/void (confirmed round 3); `await`
// isn't valid there. Every getter this file has called so far has turned out
// to be synchronous in practice regardless of the `await` used elsewhere
// (round 4/5's note on getTrackItems), so this isn't a new assumption, just
// the correct calling convention for a sync context. Added for round 17's
// mid-transaction candidate identification; unused as of round 18 (which
// doesn't query mid-transaction at all), kept for the round that tests
// removal, which will likely need it again if that removal ever needs to
// happen from inside an open transaction.
function callOrPropSync(obj, methodName, propName, label) {
  if (typeof obj[methodName] === "function") return obj[methodName]();
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

    await logTrackItems(track, "BEFORE");

    // ROUND 5 (confirmed, 2026-08-25): a same-track, nonzero-timeOffset,
    // isInsert=false clone onto empty track space produces a real, correctly
    // -shaped second item (full duration, same in/out as the original, just
    // shifted in sequence time by whatever offset was passed -- rounds 5-13
    // used a 3600s temp park spot, referred to below as PROBE_OFFSET_SEC.
    // Live-confirmed with a clean single-click before/after (1 item -> 2
    // items). Round 14 (below) stops using a temp offset at all, so the
    // constant itself is gone from the code -- kept only as a name in this
    // history for continuity with the round 11-13 comments.
    //
    // ROUND 7 result (2026-08-25): clone + trim-of-original staged together
    // in ONE transaction threw "A nullptr was dereferenced" from inside
    // executeTransaction itself -- no JS-level exception, no frame pointing
    // inside the callback, meaning our staging code ran to completion
    // without error and the native commit choked on the combination.
    // Clone alone (rounds 5-6) and trim alone (proven safe elsewhere --
    // leancoderkavy/premiere-pro-mcp's production code stages
    // createSetStartAction/createSetEndAction/etc. routinely with no
    // incident) are each individually fine, so the suspect is specifically
    // *combining* a clone with another structural edit in one compound
    // transaction, not trim in general and not clone-then-trim ordering
    // within the callback (both were staged in that order and it still
    // crashed; order inside one transaction was never actually the
    // variable that changed here).
    //
    // ROUND 8 result (2026-08-25): two SEPARATE transactions instead of one
    // compound -- clone alone, commit, THEN (in a brand new transaction,
    // with a freshly re-fetched item reference) trim alone. Transaction 1
    // committed cleanly both times (video and audio, run independently).
    // Transaction 2 -- pure trim, NO clone action anywhere in it -- still
    // threw the identical "A nullptr was dereferenced" from inside
    // executeTransaction, on both tracks. So it isn't simultaneous staging
    // that's broken; a committed clone appears to poison the track for a
    // later, unrelated transaction too.
    //
    // ROUND 9 result (2026-08-25): the missing control -- trim with NO clone
    // anywhere in the session, on a confirmed-clean clip (BEFORE showed
    // exactly 1 item, matching the untouched original). Still threw the
    // identical "A nullptr was dereferenced" on both tracks. Round 8's
    // clone-poisoning theory is dead: the crash comes from the trim itself,
    // independent of any clone history. Everything staged without a JS
    // error before the crash -- createSetEndAction returned a valid action,
    // addAction accepted it (no "returned false" from our own guard),
    // createSetOutPointAction exists (no WARNING about a missing method) and
    // was staged too -- so both trim actions staged fine; the native commit
    // is what fails.
    //
    // ROUND 10 result (2026-08-25): ROOT CAUSE FOUND. createSetEndAction
    // ALONE (no createSetOutPointAction) committed cleanly, AND the
    // out-point moved right along with it with no explicit call at all --
    // AFTER showed end=24.000s out=24.000s from a single createSetEndAction.
    // Premiere derives the media bound from the sequence-time bound
    // automatically. Every crash since round 7 happened because this file
    // was staging createSetEndAction and createSetOutPointAction TOGETHER,
    // which conflict internally -- calling both is not "extra safety", it's
    // the bug. The fix: never call createSetOutPointAction/
    // createSetInPointAction alongside createSetEndAction/
    // createSetStartAction; the single call is sufficient and correct.
    //
    // ROUND 11 (2026-08-25): retries round 7's exact original scenario --
    // clone (to the temp offset, proven safe since round 5) + trim the
    // original, together in ONE transaction -- with the fix applied: only
    // createSetEndAction for the trim, no createSetOutPointAction call at
    // all. If this commits cleanly, the single-transaction split design is
    // back alive (it looked dead after round 7, but round 7's crash was
    // this bug, not a fundamental clone+trim incompatibility).
    //
    // (cutAbsSec/cutMediaSec, used by rounds 11-14's trim/reposition calls,
    // are gone from this scope as of round 15 -- round 15 is clone-only,
    // diagnostic, no trims. See the ROUND 15 block below.)
    //
    // ROUND 11 result (2026-08-25, prior click): CONFIRMED clean on a real, non-degenerate
    // cut (in/out marked at 57.080s/135.960s, well inside the 2950.120s
    // clip). item[0] (trimmed original) read back end=out=135.960s exactly
    // as predicted. item[1] (clone at the temp offset) read back the FULL
    // pre-trim duration (2950.120s), confirming clone captured the
    // original's untouched state even with the trim happening in the same
    // commit. The single-transaction clone+trim split design is confirmed
    // working end to end for the head/trim half.
    //
    // ROUND 12 result (2026-08-25): DISAMBIGUATED. Repositioned the clone
    // via createSetStartAction ALONE, to cutAbsSec=40.800s. In-point came
    // back negative (-3559.200s = 0 + (40.800 - 3600.000) exactly) --
    // createSetStartAction auto-derives in-point via the same delta-shift
    // rule createSetEndAction used for out-point (round 10). start itself
    // landed correctly at 40.800s; only in-point was broken. Looked like it
    // just needed one more, separate correction.
    //
    // ROUND 13 result (2026-08-25): that correction -- createSetInPointAction
    // ALONE, in its own transaction -- did NOT converge. The tail came back
    // start=3640.800s (not 40.800s), off by exactly PROBE_OFFSET_SEC (3600).
    // The two live data points prove this isn't an ordering bug:
    //   round 12: 40.800 - (-3559.200) = 3600   (was 3600 - 0 = 3600 before)
    //   round 13: 3640.800 - 40.800    = 3600   (was 40.800 - (-3559.200) before)
    // (start - in) is an INVARIANT of both createSetStartAction and
    // createSetInPointAction -- each call only translates the pair together
    // by a chosen delta; neither can ever change their difference. That
    // difference gets fixed at exactly PROBE_OFFSET_SEC the moment the clone
    // is created (timeOffset moves start+end together, leaving in/out
    // untouched) and no sequence of these two actions, any order, any count,
    // can ever bring it back to 0 -- which a plain split of this untouched
    // clip requires (its own start=in=0 shows the correct tail needs
    // start=in=cutMediaSec too). The temp-offset-park-then-reposition design
    // (rounds 11-13) is a proven dead end, not a call-order bug -- see
    // README.md for the full writeup and issue #18 for the record.
    //
    // ROUND 14 (2026-08-25): the only way to avoid the gap is to never let
    // it open -- clone with timeOffset=0 (landing on the still-full-length
    // original) instead of parking at PROBE_OFFSET_SEC, so the clone starts
    // with (start - in) = 0, same as the pristine original. From there a
    // SINGLE createSetInPointAction call derives the matching start as a
    // side effect and lands exactly on target (the same delta-shift rule,
    // just applied from a zero gap instead of a 3600s one).
    //
    // The known blocker: createCloneTrackItemAction's return is not
    // chainable (confirmed rounds 4 and 11), which is *why* rounds 11-13
    // split clone and in-point-fix across separate transactions in the first
    // place -- and a zero-offset clone left sitting between two committed
    // transactions would overlap the still-full original for real (round 5:
    // same-track clones need empty destination space). So this round tests
    // something no prior round tried: querying the track from *inside* the
    // still-open transaction, after staging the clone and the head trim but
    // before commit, to see whether a fresh, chainable reference to the
    // clone is visible pre-commit. If it is, the in-point fix can be staged
    // in the SAME transaction, so the overlap never exists as committed
    // geometry. If the query comes back short, that's the honest answer
    // too: mid-transaction state isn't queryable this way, and the
    // clone-based split design is a dead end as scoped -- record that and
    // stop, per issue #18's own instructions.
    //
    // ROUND 14 result (2026-08-25): mid-transaction query found 1 item, not
    // 2 -- aborted on the guard below. NOT proof that staged state is
    // invisible mid-transaction, though: round 4/5 already showed a
    // same-track, zero-offset, isInsert=false clone is a no-op (produces no
    // second item, staged or committed), and this result is fully
    // consistent with that recurring rather than a new phenomenon. Combined
    // with round 13's proof that timeOffset=0 is the ONLY offset for which
    // a single createSetInPointAction call can close the (start - in) gap,
    // this rules out every offset value for the "clone + one in-point-fix
    // call" recipe -- not just the temp-offset variant. DEAD END, per
    // issue #18's own "say so and stop" instruction -- see the round-14
    // result entry in README.md and the closing comment on issue #18. The
    // one unexplored lever is isInsert=true (ripples the timeline instead
    // of overwriting in place -- a different design, not a round-15 patch),
    // deliberately not attempted here.
    //
    // ROUND 15 (issue #24, 2026-08-26): first live test of isInsert=true
    // anywhere in this project. Diagnostic only -- clone alone, no trims --
    // mirroring round 4's own approach to isInsert=false exactly, with
    // isInsert as the one variable changed. timeOffset=0 (same value round 4
    // used) so any difference in outcome is attributable to isInsert alone,
    // not a second changed variable.
    //
    // Logs the FULL track item list before and after, not just the target
    // item -- round 4/5 never needed this (isInsert=false doesn't ripple by
    // definition), but whether isInsert=true ripples the rest of the track,
    // and by how much, is the central open question this round exists to
    // answer. See the file-header comment and README.md for why a full
    // split recipe is deliberately NOT attempted yet from this round's
    // result alone.
    // ROUND 15 RESULT (2026-08-26, two live clicks): timeOffset=0 under
    // isInsert=true did NOT ripple anything. Click 1 (track had 1 item,
    // [0, 2950.120)): clone landed at start=2950.120 -- the FIRST item's own
    // end, not overlapping it despite targeting 0+0=0 which fully collides
    // with that item's span. The original was byte-identical before/after
    // (no shift). Click 2 (track now had 2 items, clone from click 1
    // included): cloning freshHeadItem (still item[0], the untouched
    // original) again, same timeOffset=0, landed the new clone at
    // start=5900.240 -- past BOTH existing items, not at 2950.120 where
    // click 1's clone sits. Two consistent data points rule out "always
    // clone.start = source.end + timeOffset" (that would predict 2950.120
    // again) in favor of: same-track isInsert=true, when its computed target
    // collides with existing content, auto-relocates to the first free slot
    // past EVERYTHING currently on the track -- it does not push/ripple the
    // colliding item(s) out of the way. This directly contradicts #17's
    // working assumption that isInsert=true "ripples/shifts the rest of the
    // timeline." Chainability is unchanged from isInsert=false: still a bare
    // `[object Action] ownKeys=[] protoMethods=[]` both times.
    //
    // ROUND 16 (issue #24, 2026-08-26): both round-15 clicks targeted
    // position 0+0=0 -- the very front of occupied space, which collides
    // with an item's full span from its first frame. Untested: does the
    // same auto-relocate-to-track-end behavior hold when the collision is
    // with the MIDDLE of an item instead of its boundary -- i.e., a real cut
    // point? If Premiere's insert logic always wins by relocating regardless
    // of where inside occupied space the target lands, this round should
    // again land the clone past all existing items (same as round 15 click
    // 2). If instead colliding mid-item triggers different behavior --
    // actually splitting the collided item and shifting only what comes
    // after the collision point -- that would be the real ripple-insert
    // behavior a split needs, and genuinely new information. One variable
    // changed from round 15: timeOffset is now aSec (the sequence's own
    // marked IN point, offset from the clip's start) instead of 0 --
    // deliberately a real, meaningful cut point rather than another
    // arbitrary probe value, so a positive result here is immediately usable
    // for a real recipe, not just diagnostic.
    log(`BEFORE (full track state) -- expect 1 item if you undid round 15's clicks; if not, that's ` +
        `fine too, just note the starting item count when reading AFTER below:`);
    await logTrackItems(track, "BEFORE round 16");

    // ROUND 16 RESULT (2026-08-26): a REAL, correct native split+ripple.
    // Colliding with the MIDDLE of an item (target=aSec=50.880s, versus
    // round 15's boundary-only target=0) behaves completely differently from
    // round 15's auto-relocate-to-track-end pattern. AFTER showed 3 items:
    //   [0] start=0.000    end=50.880   in=0.000   out=50.880    -- head, correctly trimmed
    //   [1] start=50.880   end=3001.000 in=0.000   out=2950.120  -- the inserted clone itself (full dup, unwanted)
    //   [2] start=3001.000 end=5900.240 in=50.880  out=2950.120  -- the ORIGINAL's tail, correctly continuing
    // Premiere split the collided item at the target, kept the head in
    // place (auto-trimmed via the same end/out auto-derive confirmed at
    // round 10), and rippled everything from the target onward later by
    // exactly the clone's own duration -- producing a tail whose in-point
    // already lands correctly (50.880, continuing exactly where the head
    // left off) with ZERO trim/reposition calls and no invariant problem at
    // all, unlike every isInsert=false attempt in #18. Chainability
    // unchanged: still a bare Action.
    //
    // The only unwanted artifact is item[1] -- the full-duration clone
    // itself, sitting between the correct head and the correct tail.
    //
    // ROUND 17 (issue #24, 2026-08-26): if item[1] can be ripple-deleted,
    // the tail should shift back by exactly its duration, landing directly
    // adjacent to the head -- a clean split, both pieces already correctly
    // formed. The one thing that decides whether this recipe is usable for
    // #22 at all: can that ripple-delete be staged in the SAME transaction
    // as the clone? #22 requires Mark to be exactly one undo step no matter
    // how many splits it makes -- a two-transaction-per-split recipe would
    // be unusable at the ~200-400 span x N track scale #17 describes.
    //
    // Round 14 tried querying mid-transaction state once before and found
    // it invisible (1 item where 2 were expected) -- but that clone was
    // later shown to be a no-op (round 4/5's isInsert=false case), so it
    // never actually tested mid-transaction visibility for a clone that
    // does something. This round re-tests the same mid-transaction query
    // with round 16's proven-working recipe, and if the new items ARE
    // visible, immediately stages a ripple-delete of the inserted clone
    // (identified as: not reference-equal to freshHeadItem, AND its own
    // in-point is ~0 (the inserted clone always inherits the source's own
    // in-point; the real tail's in-point is aSec, nonzero, so this
    // disambiguates the two new items unambiguously) -- in the SAME
    // transaction.
    // ROUND 17 RESULT (2026-08-26, two live clicks): DEAD END, cleanly
    // conclusive. Mid-transaction getTrackItems() never reflected the staged
    // clone at all -- click 1 (2 pre-existing items) saw 2 mid-transaction
    // (no increase); click 2 (clean 1-item state) saw 1 mid-transaction (no
    // increase, not even partial). This settles what round 14 could only
    // suggest (its clone was later shown to be a no-op, confounding that
    // result): mid-transaction structural state is NEVER visible via
    // getTrackItems() in this API, independent of whether the clone actually
    // does anything on commit. Corroborated against real production code
    // (Adobe's own official sample, sequenceEditor.ts, and
    // leancoderkavy/premiere-pro-mcp): neither ever references an item
    // created earlier in the same transaction -- every clone/remove call in
    // both operates on a pre-existing, explicitly-held reference (the user's
    // live selection, or an argument from outside). No undo-grouping API
    // surfaced in either. Cleaning up round 16's leftover clone genuinely
    // needs a second, separately-committed transaction -- a structural limit
    // of the API, not a spike mistake.
    //
    // Taken back to the user as a real design fork (not an agent decision):
    // accept two undo steps per Mark CLICK as a whole (not per split) by
    // batching all of a Mark's inserts into one transaction and all of its
    // byproduct cleanups into a second. Chosen, pending live proof batching
    // actually works.
    //
    // ROUND 18 (issue #24, 2026-08-26): the subtlety that has to be tested
    // before assuming the batch works -- a SECOND cut boundary's target
    // content is itself the tail produced by the FIRST cut, exactly the kind
    // of same-transaction-byproduct reference round 17 just proved
    // unreachable. Naively chaining N dependent inserts would hit that same
    // wall N-1 times. The escape: don't reference the byproduct at all --
    // clone the SAME pristine, already-held freshHeadItem a second time,
    // targeting where the marked-out point now sits after the first insert's
    // ripple (bSec + D, D = the original's full duration, since everything
    // at/after the first cut shifts forward by exactly D). If Premiere's own
    // internal engine resolves the second collision against the state left
    // by the first -- both part of one native commit, never routed through
    // our JS -- this produces the whole head/middle/tail breakdown from two
    // calls that both source the ORIGINAL reference, no dependency chaining
    // at the JS level, no mid-transaction query needed at all.
    //
    // Predicted result if the cascade resolves correctly (worked out on
    // paper, assuming both aSec and bSec+D land inside their target items'
    // spans, not at boundaries -- round 15's edge-collision auto-relocate
    // would apply otherwise):
    //   [0] head:       [0, aSec)         in=[0, aSec)   -- KEEP, enabled
    //   [1] byproduct1: [aSec, aSec+D)    in=[0, D)      -- unwanted, remove later
    //   [2] middle:     [aSec+D, bSec+D)  in=[aSec, bSec) -- the ACTUAL silence span, disable
    //   [3] byproduct2: [bSec+D, bSec+2D) in=[0, D)      -- unwanted, remove later
    //   [4] tail:       [bSec+2D, ...)    in=[bSec, D)   -- KEEP, enabled
    // No removal attempted yet -- that's a later round, only once this
    // 5-piece cascade is confirmed live.
    const D = headInfo.endSec - headInfo.startSec;
    const secondTargetOffset = bSec + D;
    log(`ROUND 18: staging TWO clone-inserts from the SAME freshHeadItem reference in one ` +
        `transaction -- target 1 at aSec=${aSec.toFixed(3)}s (offset ${aSec.toFixed(3)}s), ` +
        `target 2 at bSec+D=${(bSec + D).toFixed(3)}s (offset ${secondTargetOffset.toFixed(3)}s, ` +
        `D=${D.toFixed(3)}s is the original's full duration).`);

    let cloneResult18aDescription = null;
    let cloneResult18bDescription = null;
    let round18TxResult = null;
    project.lockedAccess(() => {
      round18TxResult = project.executeTransaction((compoundAction) => {
        const clone18a = sequenceEditor.createCloneTrackItemAction(
          freshHeadItem,
          fromSeconds(aSec), // timeOffset -- targets absolute aSec, confirmed working in round 16
          0,
          0,
          false, // alignToVideo -- still untested; still open per issue #24
          true // isInsert
        );
        cloneResult18aDescription = describe(clone18a);
        log(`clone 1 (target ${aSec.toFixed(3)}s) call returned: ${cloneResult18aDescription}`);
        if (!compoundAction.addAction(clone18a)) {
          throw new Error("compoundAction.addAction(clone18a) returned false -- aborting.");
        }

        const clone18b = sequenceEditor.createCloneTrackItemAction(
          freshHeadItem, // SAME reference as clone 1 -- deliberately not the round-16 byproduct or tail, which we cannot reference here (round 17)
          fromSeconds(secondTargetOffset), // timeOffset -- targets absolute bSec+D, the ripple-adjusted position of the marked OUT point
          0,
          0,
          false,
          true // isInsert
        );
        cloneResult18bDescription = describe(clone18b);
        log(`clone 2 (target ${(bSec + D).toFixed(3)}s) call returned: ${cloneResult18bDescription}`);
        if (!compoundAction.addAction(clone18b)) {
          throw new Error("compoundAction.addAction(clone18b) returned false -- aborting.");
        }
      }, `CutDeck spike18/24: round18 same-transaction cascading double-insert (${kind})`);
    });
    log(`round 18 executeTransaction returned: ${describe(round18TxResult)}`);

    log("AFTER (full track state):");
    const afterItems = await logTrackItems(track, "AFTER round 18 (cascading double-insert)");

    log(`ANALYSIS -- compare AFTER above (${afterItems.length} item(s)) against the 5-piece ` +
        `prediction in the ROUND 18 comment above, and record on issue #24:\n` +
        `  (1) Did executeTransaction commit (true) or throw?\n` +
        `  (2) Item count: 5 predicted. If different, the cascade didn't resolve as predicted -- ` +
        `record the actual breakdown.\n` +
        `  (3) Does item[2] (predicted middle) read in=${aSec.toFixed(3)}s out=${bSec.toFixed(3)}s -- ` +
        `i.e. exactly the real silence span, correctly formed, with no trim calls needed?\n` +
        `  (4) Does item[0] (head) still read in=[0,${aSec.toFixed(3)}s) and item[4]/last item (tail) ` +
        `read in=[${bSec.toFixed(3)}s,${headInfo.outSec.toFixed(3)}s) -- confirming both ends of the ` +
        `original are intact and correctly split?\n` +
        `If the 5-piece breakdown matches: transaction 1 of the two-transaction batch design is proven ` +
        `for a 2-cut-boundary case -- the next round tests removing both byproducts in a SECOND, ` +
        `separately-committed transaction (using a fresh post-commit query, proven reliable, not a ` +
        `mid-transaction one). If it doesn't match, record the actual breakdown and reconsider -- do ` +
        `not layer a removal round on top of an unconfirmed cascade.`);
    log("Diagnostic finished (round 18, issue #24). Record the result, then Ctrl+Z (once, if it " +
        "committed) before trying anything else.");
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
