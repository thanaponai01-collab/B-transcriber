/* Shared fake Premiere building blocks for panel tests. Each piece behaves the way Premiere was
   PROVEN to behave (docs/PREMIERE_FACTS.md: the row is cited next to each rule), so a test using
   it fails where the real host would fail, not only where the code's author expected.

   Every member here carries an Adobe class name (FAKE_SHAPE at the bottom), and
   tests/cutdeck_fake_premiere.test.cjs checks each one exists on that class in
   reference/adobe/api/premierepro.txt: the fake cannot grow a method Premiere does not have.

   Enum values: only the ones proven live are real numbers. The rest are sentinel strings, so
   panel code that hardcodes a number instead of reading ppro.Constants at runtime breaks here. */

const TICKS_PER_SECOND = 254016000000n; // PREMIERE_FACTS "Time"
const SCRIPT_OBJECT_INVALID = "The script object is no longer valid.";

const tickTime = (ticks) => ({ ticks: String(ticks) });

const TickTime = {
  createWithTicks: (ticks) => {
    if (typeof ticks !== "string") throw new Error("Illegal Parameter type"); // declared (ticks: string)
    return tickTime(ticks);
  },
  createWithSeconds: (seconds) => tickTime(BigInt(Math.round(seconds * Number(TICKS_PER_SECOND)))),
};

class PointF {
  constructor(x = 0, y = 0) { this.x = x; this.y = y; }
}

const Constants = {
  // PREMIERE_FACTS "Effects": runtime values from the Check Keyframes probe, NOT the typings' order.
  InterpolationMode: { LINEAR: 0, HOLD: 4, BEZIER: 5, TIME: "InterpolationMode.TIME",
    TIME_TRANSITION_START: "InterpolationMode.TIME_TRANSITION_START", TIME_TRANSITION_END: "InterpolationMode.TIME_TRANSITION_END" },
  TrackItemType: { EMPTY: "TrackItemType.EMPTY", CLIP: "TrackItemType.CLIP", TRANSITION: "TrackItemType.TRANSITION",
    PREVIEW: "TrackItemType.PREVIEW", FEEDBACK: "TrackItemType.FEEDBACK" },
  MediaType: { ANY: "MediaType.ANY", DATA: "MediaType.DATA", VIDEO: "MediaType.VIDEO", AUDIO: "MediaType.AUDIO" },
};

/* A keyframe value for a point param must be a real PointF; a plain [x, y] array throws
   (PREMIERE_FACTS "Effects": createKeyframe for point params). */
function assertPointValue(value) {
  if (!(value instanceof PointF)) throw new Error("Illegal Parameter type");
  return value;
}

/* Premiere's transaction rules (PREMIERE_FACTS "Transactions and Actions"):
   - an Action must be created inside executeTransaction's callback, or adding it throws;
   - actions apply only at commit, after the callback returns, so nothing the callback does is
     visible to reads made inside it;
   - one executeTransaction = one undo step (recorded in `undoSteps`).
   `action(run)` makes an Action: use it in every fake create*Action method. Transactions are
   synchronous, so one module-level flag covers every fake project. */
let inCallback = false;
const action = (run) => ({ run, valid: inCallback });

function createProject() {
  const undoSteps = [];
  const project = {
    executeTransaction(callback, undoString) {
      const pending = [];
      const compound = {
        addAction(a) {
          if (!a || !a.valid) throw new Error(SCRIPT_OBJECT_INVALID);
          pending.push(a);
          return true;
        },
      };
      inCallback = true;
      try { callback(compound); } finally { inCallback = false; }
      for (const a of pending) a.run();
      undoSteps.push(undoString);
      return true;
    },
    lockedAccess(callback) { callback(); },
  };
  return { project, undoSteps };
}

/* TrackItemSelection whose selection is valid only inside createEmptySelection's callback
   (PREMIERE_FACTS "Placing": createEmptySelection). `trackItems` of a used-up selection throws. */
const TrackItemSelection = {
  createEmptySelection(callback) {
    let live = true;
    const items = [];
    const selection = {
      addItem(item) { if (!live) throw new Error(SCRIPT_OBJECT_INVALID); items.push(item); return true; },
      getTrackItems() { if (!live) throw new Error(SCRIPT_OBJECT_INVALID); return Promise.resolve([...items]); },
    };
    try { callback(selection); } finally { live = false; }
    return true;
  },
};

// Adobe class each fake member stands for; checked against the typings index by
// tests/cutdeck_fake_premiere.test.cjs. "static" = the class's static side (FooStatic).
const FAKE_SHAPE = [
  { adobe: "TickTime", side: "static", fake: TickTime },
  { adobe: "TrackItemSelection", side: "static", fake: TrackItemSelection },
  { adobe: "PointF", side: "instance", fake: new PointF() },
  { adobe: "Project", side: "instance", fake: createProject().project },
  { adobe: "CompoundAction", side: "instance", fake: { addAction() {} } },
  { adobe: "Constants", side: "enums", fake: Constants },
];

module.exports = {
  TICKS_PER_SECOND,
  SCRIPT_OBJECT_INVALID,
  tickTime,
  action,
  TickTime,
  PointF,
  Constants,
  assertPointValue,
  createProject,
  TrackItemSelection,
  FAKE_SHAPE,
};
