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
const selectionItems = new WeakMap(); // selection -> its items, for the fake remove action
const TrackItemSelection = {
  createEmptySelection(callback) {
    let live = true;
    const items = [];
    const selection = {
      addItem(item) { if (!live) throw new Error(SCRIPT_OBJECT_INVALID); items.push(item); return true; },
      getTrackItems() { if (!live) throw new Error(SCRIPT_OBJECT_INVALID); return Promise.resolve([...items]); },
    };
    selectionItems.set(selection, items);
    try { callback(selection); } finally { live = false; }
    return true;
  },
};

/* A project whose sequences can be read, copied, renamed, cleared and placed into: enough for
   timeline/buildSequence.js. `media`: [{ path, video, audio, duration }] (which sides an overwrite
   places; ticks as BigInt). `sequences`: [{ name, video: [[clip]], audio: [[clip]] }], clip =
   { media: path, start, end, in } in BigInt ticks. Rules modelled (PREMIERE_FACTS "Placing"):
   - createOverwriteItemAction takes the plain ProjectItem; the ClipProjectItem.cast of it is
     refused with "Invalid parameter." ("the item passed");
   - it places the project item's In/Out span as read when the Action is made, so marks set in the
     same compound are not seen ("State inside one compound");
   - a track index equal to the track count creates the track; a larger one is unproven: refused.
   Overlaps are not modelled: tests place into gaps.
   `place(n)` runs as the n-th overwrite (from 1) is created: return a tick offset to land it off
   its time, or throw to refuse it. Hidden state lives in closures and WeakMaps, never on the
   objects, so FAKE_SHAPE can check every member. */
function createTimelineHost({ path = "", media = [], sequences = [], place = () => 0n } = {}) {
  const { project: core, undoSteps } = createProject();
  const marks = new Map(); // media path -> { in, out }
  const projectItems = new Map(); // media path -> ProjectItem
  const mediaOf = new WeakMap(); // ProjectItem -> media
  const clipOf = new WeakMap(); // ProjectItem -> ClipProjectItem
  for (const m of media) {
    marks.set(m.path, { in: 0n, out: m.duration });
    // `name`: what Premiere calls an imported file's item (its file name); default the path.
    const item = { name: m.name || m.path, getId: () => `item:${m.path}`, createSetNameAction: () => action(() => {}) };
    const clip = {
      name: m.path,
      getMediaFilePath: async () => m.path,
      getInPoint: async () => tickTime(marks.get(m.path).in),
      getOutPoint: async () => tickTime(marks.get(m.path).out),
      createSetInOutPointsAction: (inPoint, outPoint) =>
        action(() => marks.set(m.path, { in: BigInt(inPoint.ticks), out: BigInt(outPoint.ticks) })),
    };
    projectItems.set(m.path, item);
    mediaOf.set(item, m);
    clipOf.set(item, clip);
  }

  const items = new WeakMap(); // raw clip -> track item
  const selected = new Set(); // raw clips selected on the timeline
  const rawOf = new WeakMap(); // track item -> raw clip
  const trackItem = (raw) => {
    if (!items.has(raw)) {
      const item = {
        getStartTime: async () => tickTime(raw.start),
        getEndTime: async () => tickTime(raw.end),
        getInPoint: async () => tickTime(raw.in),
        getOutPoint: async () => tickTime(raw.in + raw.end - raw.start),
        getProjectItem: async () => projectItems.get(raw.media.path),
        isDisabled: async () => Boolean(raw.disabled),
        createSetDisabledAction: (disabled) => action(() => { raw.disabled = disabled; }),
        createMoveAction: (dt) => action(() => { raw.start += BigInt(dt.ticks); raw.end += BigInt(dt.ticks); }),
        createSetOutPointAction: (t) => action(() => { raw.end = raw.start + BigInt(t.ticks) - raw.in; }),
        getName: async () => raw.name || raw.media.path,
        getSpeed: async () => 1,
        getIsSelected: async () => selected.has(raw),
        createSetNameAction: (name) => action(() => { raw.name = name; }),
        // Head trim: start and media In move together, end stays (PREMIERE_FACTS "createSetInPointAction(t)").
        createSetInPointAction: (t) => action(() => { raw.start += BigInt(t.ticks) - raw.in; raw.in = BigInt(t.ticks); }),
      };
      items.set(raw, item);
      rawOf.set(item, raw);
    }
    return items.get(raw);
  };
  const track = (list) => ({ name: "", getTrackItems: () => list.map(trackItem) });

  let guids = 0;
  const raws = [];
  const addSequence = (seq) => { raws.push(seq); return seq; };
  for (const seq of sequences) {
    const tracks = (list) => list.map((t) => t.map((c) => ({ ...c, media: media.find((m) => m.path === c.media) })));
    addSequence({ name: seq.name, guid: `seq${guids++}`, video: tracks(seq.video), audio: tracks(seq.audio), frame: seq.frame || null });
  }
  const wrappers = new WeakMap(); // raw sequence -> Sequence
  const rawSeq = new WeakMap(); // Sequence -> raw sequence
  const wrap = (s) => {
    if (!wrappers.has(s)) {
      const item = { name: s.name, getId: () => `item:${s.guid}`, createSetNameAction: (name) => action(() => { s.name = name; }) };
      const copy = (list) => list.map((t) => t.map((c) => ({ ...c })));
      const seq = {
        get name() { return s.name; },
        guid: { toString: () => s.guid },
        getVideoTrackCount: async () => s.video.length,
        getAudioTrackCount: async () => s.audio.length,
        getVideoTrack: async (i) => track(s.video[i]),
        getAudioTrack: async (i) => track(s.audio[i]),
        getProjectItem: async () => item,
        createCloneAction: () => action(() => addSequence({ name: `${s.name} Copy`, guid: `seq${guids++}`, video: copy(s.video), audio: copy(s.audio), marks: { ...(s.marks || {}) } })),
        getSettings: async () => ({ frame: s.frame || null }),
        createSetSettingsAction: (settings) => action(() => { s.frame = settings.frame; }),
        getInPoint: async () => tickTime((s.marks || {}).in || 0n),
        getOutPoint: async () => tickTime((s.marks || {}).out || 0n),
        createSetInPointAction: (t) => action(() => { s.marks = { ...(s.marks || {}), in: BigInt(t.ticks) }; }),
        createSetOutPointAction: (t) => action(() => { s.marks = { ...(s.marks || {}), out: BigInt(t.ticks) }; }),
        getFrameSize: async () => ({ width: 1920, height: 1080 }),
        getTimebase: async () => "8475667200",
        getEndTime: async () => tickTime([...s.video, ...s.audio].flat().reduce((m, c) => (c.end > m ? c.end : m), 0n)),
        getPlayerPosition: async () => tickTime(s.playhead || 0n),
        setPlayerPosition: async (t) => { s.playhead = BigInt(t.ticks); return true; },
        clearSelection: async () => { selected.clear(); return true; },
        // Called inside createEmptySelection's callback: the selection dies after it.
        setSelection: (selection) => { for (const item of selectionItems.get(selection)) selected.add(rawOf.get(item)); return true; },
      };
      wrappers.set(s, seq);
      rawSeq.set(seq, s);
    }
    return wrappers.get(s);
  };

  let placed = 0;
  const editor = (s) => ({
    createOverwriteItemAction(projectItem, time, videoTrack, audioTrack) {
      const m = mediaOf.get(projectItem);
      if (!m) throw new Error("Invalid parameter.");
      const span = { ...marks.get(m.path) };
      const at = BigInt(time.ticks) + place(++placed);
      return action(() => {
        const land = (tracks, i) => {
          if (i > tracks.length) throw new Error("fake: a track index past the track count is unproven");
          if (i === tracks.length) tracks.push([]);
          tracks[i].push({ media: m, start: at, end: at + span.out - span.in, in: span.in });
        };
        if (m.video) land(s.video, videoTrack);
        if (m.audio) land(s.audio, audioTrack);
      });
    },
    // Same-track clone by an offset (PREMIERE_FACTS: overwrites what is there; unlinked; effects kept).
    createCloneTrackItemAction(item, timeOffset, videoOffset, audioOffset, alignToVideo, isInsert) {
      const raw = rawOf.get(item);
      const dt = BigInt(timeOffset.ticks);
      return action(() => {
        for (const tracks of [s.video, s.audio]) {
          const t = tracks.find((list) => list.includes(raw));
          if (!t) continue;
          const copy = { ...raw, start: raw.start + dt, end: raw.end + dt };
          for (let i = t.length - 1; i >= 0; i--) if (t[i].start < copy.end && t[i].end > copy.start) t.splice(i, 1);
          t.push(copy);
        }
      });
    },
    createRemoveItemsAction(selection, ripple, mediaType) {
      const chosen = [...selectionItems.get(selection)].map((item) => rawOf.get(item));
      const sides = [[s.video, Constants.MediaType.VIDEO], [s.audio, Constants.MediaType.AUDIO]]
        .filter(([, type]) => mediaType === Constants.MediaType.ANY || mediaType === type);
      return action(() => {
        for (const [tracks] of sides) for (const t of tracks) for (const raw of chosen) if (t.includes(raw)) t.splice(t.indexOf(raw), 1);
      });
    },
  });

  // Bins and import, enough for timeline/buildSequence.js `import: true` items: a bin lists its
  // children and can create a child bin; importFiles([path], suppressUI, bin) puts that media's
  // ProjectItem (the media must be in `media`) into the bin. `imports` counts importFiles calls.
  const children = new WeakMap(); // bin -> its items
  const makeBin = (binName) => {
    const bin = {
      name: binName, type: 2,
      getItems: async () => [...children.get(bin)],
      createBinAction: (child) => action(() => children.get(bin).push(makeBin(child))),
      // Removing a sequence's item deletes the sequence, as in Premiere.
      createRemoveItemAction: (item) => action(() => {
        children.get(bin).splice(children.get(bin).indexOf(item), 1);
        const at = raws.findIndex((r) => r.name === item.name);
        if (at >= 0 && item.isSequenceItem) raws.splice(at, 1);
      }),
    };
    children.set(bin, []);
    return bin;
  };
  const root = makeBin("root");
  const imports = [];

  let saves = 0;
  const project = {
    ...core,
    path,
    getSequences: async () => raws.map(wrap),
    getActiveSequence: async () => (raws.length ? wrap(raws[0]) : null),
    save: async () => { saves++; return true; },
    getRootItem: async () => root,
    importFiles: async (paths, suppressUI, bin) => {
      for (const p of paths) {
        if (!projectItems.has(p)) return false;
        imports.push(p);
        children.get(bin || root).push(projectItems.get(p));
      }
      return true;
    },
  };
  const ppro = {
    Project: { getActiveProject: async () => project },
    ClipProjectItem: { cast: (projectItem) => clipOf.get(projectItem) || null },
    SequenceEditor: { getEditor: (seq) => editor(rawSeq.get(seq)) },
    TickTime, TrackItemSelection, Constants, PointF,
    Markers: { getMarkers: async () => ({ getMarkers: () => [], createRemoveMarkerAction: () => action(() => {}) }) },
  };
  const clipsOf = (s, kind) => s[kind].flatMap((t, i) => t.map((c) => ({ track: i, start: c.start, end: c.end, in: c.in, media: c.media.path, ...(c.disabled ? { disabled: true } : {}) })));
  return {
    ppro, project, undoSteps,
    get saves() { return saves; },
    imports,
    // Files a sequence's project item in bin `path` (names from the root), making the bins.
    fileSequence: (path, name) => {
      let bin = root;
      for (const binName of path) {
        let next = children.get(bin).find((it) => it.name === binName);
        if (!next) { next = makeBin(binName); children.get(bin).push(next); }
        bin = next;
      }
      children.get(bin).push({ name, type: 1, isSequenceItem: true });
    },
    marks: (mediaPath) => ({ ...marks.get(mediaPath) }),
    // Every sequence by name, as plain clips per side.
    sequence: (name) => { const s = raws.find((r) => r.name === name); return s && { video: clipsOf(s, "video"), audio: clipsOf(s, "audio"), frame: s.frame || null, marks: s.marks || null }; },
    // One of each fake object, for FAKE_SHAPE.
    samples: () => {
      const s = raws[0];
      return { sequence: wrap(s), projectItem: projectItems.get(media[0].path), clip: clipOf.get(projectItems.get(media[0].path)),
        videoTrack: track(s.video[0]), audioTrack: track(s.audio[0]), videoItem: trackItem(s.video[0][0]),
        audioItem: trackItem(s.audio[0][0]), editor: editor(s) };
    },
  };
}

const sampleHost = createTimelineHost({
  media: [{ path: "a.mp4", video: true, audio: true, duration: 10n }],
  sequences: [{ name: "s", video: [[{ media: "a.mp4", start: 0n, end: 1n, in: 0n }]], audio: [[{ media: "a.mp4", start: 0n, end: 1n, in: 0n }]] }],
});
const sample = sampleHost.samples();

// Adobe class each fake member stands for; checked against the typings index by
// tests/cutdeck_fake_premiere.test.cjs. "static" = the class's static side (FooStatic).
const FAKE_SHAPE = [
  { adobe: "TickTime", side: "static", fake: TickTime },
  { adobe: "TrackItemSelection", side: "static", fake: TrackItemSelection },
  { adobe: "PointF", side: "instance", fake: new PointF() },
  { adobe: "Project", side: "instance", fake: sampleHost.project },
  { adobe: "Project", side: "static", fake: sampleHost.ppro.Project },
  { adobe: "Sequence", side: "instance", fake: sample.sequence },
  { adobe: "Guid", side: "instance", fake: sample.sequence.guid },
  { adobe: "ProjectItem", side: "instance", fake: sample.projectItem },
  { adobe: "ClipProjectItem", side: "instance", fake: sample.clip },
  { adobe: "ClipProjectItem", side: "static", fake: sampleHost.ppro.ClipProjectItem },
  { adobe: "VideoTrack", side: "instance", fake: sample.videoTrack },
  { adobe: "AudioTrack", side: "instance", fake: sample.audioTrack },
  { adobe: "VideoClipTrackItem", side: "instance", fake: sample.videoItem },
  { adobe: "AudioClipTrackItem", side: "instance", fake: sample.audioItem },
  { adobe: "SequenceEditor", side: "static", fake: sampleHost.ppro.SequenceEditor },
  { adobe: "SequenceEditor", side: "instance", fake: sample.editor },
  { adobe: "CompoundAction", side: "instance", fake: { addAction() {} } },
  { adobe: "Markers", side: "static", fake: sampleHost.ppro.Markers },
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
  createTimelineHost,
  FAKE_SHAPE,
};
