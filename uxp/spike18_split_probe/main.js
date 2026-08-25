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
    const cutAbsSec = headInfo.startSec + bSec;
    const cutMediaSec = headInfo.inSec + bSec;

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
    log(`clone (offset 0, on top of the original) + trim original's end to ` +
        `${cutAbsSec.toFixed(3)}s + fix the clone's in-point to ${cutMediaSec.toFixed(3)}s -- ` +
        `all staged in ONE transaction (no temp park, no separate reposition step)`);

    let round14TxResult = null;
    project.lockedAccess(() => {
      round14TxResult = project.executeTransaction((compoundAction) => {
        const cloneResult14 = sequenceEditor.createCloneTrackItemAction(
          freshHeadItem,
          fromSeconds(0), // timeOffset -- zero this round, deliberately (see ROUND 14 comment above)
          0,
          0,
          false,
          false // isInsert -- overwrite; lands directly on the still-full original for now
        );
        log(`clone call returned: ${describe(cloneResult14)}`);
        if (!compoundAction.addAction(cloneResult14)) {
          throw new Error("compoundAction.addAction(cloneResult14) returned false -- aborting.");
        }

        const trimEndAction = freshHeadItem.createSetEndAction(fromSeconds(cutAbsSec));
        if (!compoundAction.addAction(trimEndAction)) {
          throw new Error("compoundAction.addAction(trimEndAction) returned false -- aborting.");
        }

        // The untested question this round exists to answer: is a fresh,
        // chainable item visible from a track query made *inside* the still-
        // open transaction, before it commits? No prior round tried this --
        // every earlier re-query happened after commit. A read-only query
        // should be safe to attempt even if the answer turns out to be "no."
        let liveItems;
        try {
          liveItems = track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
        } catch (e) {
          throw new Error(`track.getTrackItems() threw inside the open transaction: ` +
              `${e && e.message ? e.message : e} -- mid-transaction query not viable, aborting.`);
        }
        log(`mid-transaction query: ${liveItems ? liveItems.length : 0} item(s) visible ` +
            `(1 before this transaction opened)`);
        if (!liveItems || liveItems.length < 2) {
          throw new Error(`expected 2 items mid-transaction, found ${liveItems ? liveItems.length : 0} ` +
              `-- staged-but-uncommitted state is not visible via getTrackItems(). Aborting; the ` +
              `zero-offset-clone-plus-mid-transaction-fix approach does not work as tried.`);
        }

        // Identify the clone by reference: it's whichever item in the query
        // is NOT freshHeadItem (the one item we already hold a handle to).
        // If every item fails that check (e.g. UXP hands back a fresh
        // wrapper object per call, making !== unreliable), fall back to the
        // last array entry and say so plainly rather than guessing silently.
        let tailCandidate = liveItems.find((it) => it !== freshHeadItem);
        let pickedBy = "reference inequality vs freshHeadItem";
        if (!tailCandidate) {
          tailCandidate = liveItems[liveItems.length - 1];
          pickedBy = "fallback: last array entry (reference-equality check found nothing distinct)";
        }
        log(`picked mid-transaction clone candidate by: ${pickedBy}`);

        const setInAction = tailCandidate.createSetInPointAction(fromSeconds(cutMediaSec));
        if (!compoundAction.addAction(setInAction)) {
          throw new Error("compoundAction.addAction(setInAction) returned false -- aborting.");
        }
      }, `CutDeck spike18: round14 single-transaction clone(offset0)+trim+inpoint-fix (${kind})`);
    });
    log(`round 14 executeTransaction returned: ${describe(round14TxResult)}`);

    await logTrackItems(track, "AFTER round 14 (single-transaction attempt)");
    log(`ANALYSIS: if round 14 committed, the tail item should now read ` +
        `start=${cutAbsSec.toFixed(3)}s in=${cutMediaSec.toFixed(3)}s ` +
        `end=${headInfo.endSec.toFixed(3)}s out=${headInfo.outSec.toFixed(3)}s -- note end/out are ` +
        `the TRUE original values this time, not an offset placeholder, since there was never a ` +
        `temp park spot to leave behind. If executeTransaction threw instead (see the error above), ` +
        `that is the answer too: record which step failed (clone, mid-transaction query, or the ` +
        `in-point fix) on issue #18 -- if it's the mid-transaction query, the clone-based split ` +
        `design is a dead end as scoped, per the issue's own "say so and stop" instruction.`);
    log("Diagnostic finished. Record the result on issue #18, then Ctrl+Z (once per transaction " +
        "that actually committed, per the log above) to undo before trying anything else.");
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
