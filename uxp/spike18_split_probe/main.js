/*
 * CutDeck spike #18 -- split probe.
 *
 * Best-effort implementation of the split recipe issue #18 itself proposes:
 * "trim the original's end back to the cut point first, then clone, then
 * correct the clone's in-point and start." The one genuinely unknown step is
 * what createCloneTrackItemAction() hands back -- a chainable TrackItem, or
 * just an Action descriptor with no item reference until the transaction
 * commits. This file checks which one it got (duck-typing the return value)
 * and logs the answer loudly instead of assuming. See README.md.
 *
 * All frame math here is plain JS seconds arithmetic (offset-from-clip-start
 * in, offset-from-clip-start out), not transcribe/timebase.py's tick-exact
 * rounding -- this file is throwaway spike code with no Python dependency,
 * never wired into cutdeck/mark_export.py or bridge.py. It also assumes
 * speed=1 on the target clip; it does not check for speed changes or VFR
 * (out of scope for a one-button spike against a known test clip).
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

// Reads whichever of getStart()/start, getEnd()/end, getInPoint()/inPoint,
// getOutPoint()/outPoint the live object actually has, trying the getter
// spelling first (matches the rest of issue #17's documented API) and
// falling back to a bare property.
async function readTimes(item, label) {
  async function readOne(getterName, propName) {
    if (typeof item[getterName] === "function") return await item[getterName]();
    if (item[propName] !== undefined) return item[propName];
    throw new Error(`neither ${getterName}() nor .${propName} exists on ${label}`);
  }
  const start = await readOne("getStart", "start");
  const end = await readOne("getEnd", "end");
  const inPoint = await readOne("getInPoint", "inPoint");
  const outPoint = await readOne("getOutPoint", "outPoint");
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

async function getFirstItem(sequence, kind) {
  // kind: "video" | "audio"
  const track =
    kind === "video" ? await sequence.getVideoTrack(0) : await sequence.getAudioTrack(0);
  if (!track) throw new Error(`sequence has no ${kind} track 0`);
  const count = await (track.getTrackItemCount ? track.getTrackItemCount() : track.trackItemCount);
  if (!count || count < 1) throw new Error(`${kind} track 0 has no clips`);
  const item = await track.getTrackItem(0);
  if (!item) throw new Error(`${kind} track 0, item 0 came back empty`);
  return { track, item };
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
 */
function stageSplit(compoundAction, headItem, headInfo, offsetSec, label) {
  log(`--- staging split "${label}" at +${offsetSec}s from clip start ---`);

  const cloneResult = ppro.TrackItem.createCloneTrackItemAction(
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
    // calls onto directly.
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
  const aSec = parseFloat(document.getElementById("timeA").value);
  const bSec = parseFloat(document.getElementById("timeB").value);
  if (!(aSec >= 0) || !(bSec > aSec)) {
    log("ERROR: need 0 <= A < B (in seconds from clip start).");
    return;
  }
  if (!ppro) {
    log("ERROR: require('premierepro') failed -- not running inside a Premiere UXP host?");
    return;
  }

  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error("no active project");
    const sequence = await project.getActiveSequence();
    if (!sequence) throw new Error("no active sequence");

    const { item: headItem } = await getFirstItem(sequence, kind);
    log(`found first ${kind} clip:`);
    const headInfo = await readTimes(headItem, "original clip");

    let splitAInfo = null;
    let splitBInfo = null;

    const ok = await project.executeTransaction((compoundAction) => {
      splitAInfo = stageSplit(compoundAction, headItem, headInfo, aSec, "A");
      if (!splitAInfo || !splitAInfo.tailItem) {
        throw new Error('split "A" did not produce a chainable tail item -- aborting ' +
          'before B/disable so this transaction commits nothing rather than a half-cut state.');
      }

      // headInfo for the second split is the tail-of-A's own current state,
      // expressed the same way (start/in as read before ANY split ran --
      // computed here since we can't re-read from Premiere mid-transaction).
      const tailAInfo = {
        startSec: splitAInfo.cutAbsSec,
        endSec: splitAInfo.tailEndSec,
        inSec: splitAInfo.cutMediaSec,
        outSec: splitAInfo.tailOutSec,
      };
      splitBInfo = stageSplit(compoundAction, splitAInfo.tailItem, tailAInfo, bSec - aSec, "B");
      if (!splitBInfo || !splitBInfo.tailItem) {
        throw new Error('split "B" did not produce a chainable tail item -- aborting.');
      }

      // The "middle" piece is what tailA (splitAInfo.tailItem) became after
      // split B trimmed it down to [A, B] -- disable that object directly.
      const middleItem = splitAInfo.tailItem;
      if (typeof middleItem.createSetDisabledAction !== "function") {
        throw new Error("middle item has no createSetDisabledAction -- aborting.");
      }
      compoundAction.addAction(middleItem.createSetDisabledAction(true));
      log("staged: disable middle piece [A, B]");
    }, `CutDeck spike18: split ${kind} clip at ${aSec}s/${bSec}s`);

    log(`executeTransaction returned: ${describe(ok)}`);
    log("Transaction attempt finished. Check the sequence now, and press " +
        "Ctrl+Z once to see if it reverses everything in one step.");
  } catch (e) {
    log(`FAILED: ${e && e.message ? e.message : e}`);
    if (e && e.stack) log(e.stack);
  }
}

document.getElementById("runVideo").addEventListener("click", () => runSpike("video"));
document.getElementById("runAudio").addEventListener("click", () => runSpike("audio"));
