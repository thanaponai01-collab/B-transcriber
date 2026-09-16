/* A small but honest Premiere timeline, for the issue #25 assemble probe.

   It is a separate file rather than inlined in the test so that anything else that
   needs to exercise the probe — rendering its report to see what a human will read,
   before spending a live Premiere click on it — drives the same host the tests
   assert against, instead of a second copy that could drift from it.

   The one knob that matters is `mode`: "independent" applies staged actions in the
   order they were added, "collapsed" applies every setInOut before every overwrite —
   which is exactly the failure issue #25 predicts if the shared ClipProjectItem
   resolves against the last value written. */
const PROBE_SEQUENCE_NAME = require("../../uxp/spike_assemble_probe/assembleProbe.js").PROBE_SEQUENCE_NAME;

const TPF_25 = 10160640000n;   // 25 — the rate probe()'s fallback fabricates
const TPF_2997 = 8475667200n;  // 30000/1001

const tickObj = (value) => ({ ticks: value.toString() });

function makeHost(opts = {}) {
  const tpf = opts.tpf || TPF_2997;
  const sourceFrames = opts.sourceFrames === undefined ? 120n : opts.sourceFrames;
  const mode = opts.mode || "independent";        // independent | collapsed
  const eatTicks = opts.eatTicks || 0n;           // simulate overwrite swallowing a frame
  const calls = { deleteSequence: 0, transactions: [], lockedNesting: [] };

  // The one ClipProjectItem every placement shares — the crux of unknown 2.
  const projectItem = {
    name: "source clip",
    inTicks: 0n, outTicks: sourceFrames * tpf,
    createSetInOutPointsAction(inTime, outTime) {
      if (opts.noSetInOut) throw new Error("createSetInOutPointsAction is not a function");
      const a = BigInt(inTime.ticks), b = BigInt(outTime.ticks);
      return { kind: "setInOut", apply: () => { projectItem.inTicks = a; projectItem.outTicks = b; } };
    },
  };

  const makeTrack = () => {
    const items = [];
    const wrap = (state) => ({
      name: state.name,
      getStartTime: async () => tickObj(state.start),
      getEndTime: async () => tickObj(state.end),
      getInPoint: async () => tickObj(state.mediaIn),
      getOutPoint: async () => tickObj(state.mediaIn + (state.end - state.start)),
      getProjectItem: async () => projectItem,
      isDisabled: async () => state.disabled === true,
      createSetDisabledAction(value) {
        if (opts.noDisable) throw new Error("createSetDisabledAction is not a function");
        return { kind: "disable", apply: () => { state.disabled = value; } };
      },
      _state: state,
    });
    return {
      items,
      seed(state) { items.push(wrap(state)); },
      place(state) { items.push(wrap(state)); items.sort((x, y) => (x._state.start < y._state.start ? -1 : 1)); },
      remove(victim, ripple) {
        const at = items.indexOf(victim);
        if (at < 0) throw new Error("removeItems: the item is not on this track");
        const length = victim._state.end - victim._state.start;
        items.splice(at, 1);
        if (ripple) for (const other of items) {
          if (other._state.start >= victim._state.end) { other._state.start -= length; other._state.end -= length; }
        }
      },
      end() { return items.reduce((acc, i) => (i._state.end > acc ? i._state.end : acc), 0n); },
      getTrackItems: async () => items.slice(),
    };
  };

  const sourceTrack = makeTrack();
  sourceTrack.seed({ name: "source clip", start: 0n, end: sourceFrames * tpf, mediaIn: 0n });
  const source = {
    name: "Disposable test sequence",
    getTimebase: async () => tpf.toString(),
    getSettings: async () => (opts.noSettings ? null : { timebase: tpf.toString() }),
    getEndTime: async () => tickObj(sourceTrack.end()),
    getVideoTrack: async (i) => (opts.noVideoTrack ? null : (i === 0 ? sourceTrack : null)),
  };

  const builtTrack = makeTrack();
  const selectionGroup = { picked: [], clear() { this.picked = []; }, addItem(item) { this.picked.push(item); } };
  let builtTimebase = opts.newSequenceTimebase === undefined ? TPF_25 : opts.newSequenceTimebase;
  const built = {
    name: PROBE_SEQUENCE_NAME,
    getTimebase: async () => (builtTimebase === null ? null : builtTimebase.toString()),
    getEndTime: async () => tickObj(builtTrack.end()),
    getVideoTrack: async (i) => (i === 0 ? builtTrack : null),
    getSelection: async () => selectionGroup,
    createSetSettingsAction(settings) {
      return { kind: "settings", apply: () => { if (!opts.settingsNoop) builtTimebase = BigInt(settings.timebase); } };
    },
  };

  const editor = {
    createOverwriteItemAction(item, time, videoIndex) {
      if (opts.noOverwrite) throw new Error("createOverwriteItemAction is not a function");
      const at = BigInt(time.ticks);
      return { kind: "overwrite", apply: () => {
        // Reads the SHARED project item when it applies — so the apply ORDER is
        // what decides whether three placements stay distinct.
        const length = projectItem.outTicks - projectItem.inTicks - eatTicks;
        builtTrack.place({ name: `placed@${at}`, start: at, end: at + length,
          mediaIn: projectItem.inTicks, track: videoIndex });
      } };
    },
    createRemoveItemsAction(selection, ripple) {
      if (opts.noRemove) throw new Error("createRemoveItemsAction is not a function");
      const picked = Array.isArray(selection) ? selection : selection.picked;
      return { kind: "remove", apply: () => {
        if (opts.removeThrows) throw new Error("removeItems refused");
        for (const item of picked) builtTrack.remove(item, ripple);
      } };
    },
  };

  const project = {
    getActiveSequence: async () => (opts.noSequence ? null : source),
    createSequence: opts.noCreateSequence ? undefined : async () => built,
    deleteSequence: async () => { calls.deleteSequence += 1; },
    // try/finally matters: a staged action that throws must still record the close,
    // or a later transaction would falsely read as locked and the "never called
    // bare" assertion could be satisfied by a leaked depth rather than a real wrap.
    lockedAccess(fn) {
      calls.lockedNesting.push("open");
      try { fn(); } finally { calls.lockedNesting.push("close"); }
    },
    executeTransaction(stage, label) {
      // Every transaction must arrive from inside lockedAccess, never bare.
      const depth = calls.lockedNesting.filter((e) => e === "open").length
        - calls.lockedNesting.filter((e) => e === "close").length;
      calls.transactions.push({ label, locked: depth > 0 });
      const staged = [];
      stage({ addAction: (a) => { staged.push(a); return true; } });
      const ordered = mode === "collapsed"
        ? [...staged.filter((a) => a.kind === "setInOut"), ...staged.filter((a) => a.kind !== "setInOut")]
        : staged;
      for (const action of ordered) action.apply();
      return true;
    },
  };

  const ppro = {
    Project: { getActiveProject: async () => (opts.noProject ? null : project) },
    SequenceEditor: { getEditor: (s) => (opts.noEditor ? null : editor) },
    TickTime: { createWithTicks: (s) => ({ ticks: String(s) }) },
    Constants: { TrackItemType: { CLIP: "clip" }, MediaType: { ANY: "any" } },
    TrackItemSelection: {},
  };
  return { ppro, calls, builtTrack, get builtTimebase() { return builtTimebase; } };
}


module.exports = { makeHost, tickObj, TPF_25, TPF_2997 };
