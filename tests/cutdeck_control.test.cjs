/* General Premiere control (uxp/cutdeck/timeline/control.js) on the shared Premiere fake, whose
   rules follow docs/PREMIERE_FACTS.md. Fake-tested only: live status is in
   docs/PREMIERE_CONTROL_MAP.md. */
const test = require("node:test");
const assert = require("node:assert/strict");
const { controlHandlers, parseClipId, clipId } = require("../uxp/cutdeck/timeline/control.js");
const fake = require("./fakes/premiere.cjs");

const S = 254016000000n; // ticks per second

function setup() {
  const h = fake.createTimelineHost({
    media: [{ path: "D:\\a.mp4", video: true, audio: true, duration: 60n * S }, { path: "D:\\b.mp4", video: true, audio: true, duration: 60n * S }],
    sequences: [{
      name: "Edit",
      video: [[{ media: "D:\\a.mp4", start: 0n, end: 10n * S, in: 0n }, { media: "D:\\a.mp4", start: 10n * S, end: 20n * S, in: 30n * S }]],
      audio: [[{ media: "D:\\a.mp4", start: 0n, end: 10n * S, in: 0n }, { media: "D:\\a.mp4", start: 10n * S, end: 20n * S, in: 30n * S }]],
    }],
  });
  return { h, run: controlHandlers(h.ppro) };
}

test("clip ids are V/A, 1-based track, @ start ticks", () => {
  assert.deepEqual(parseClipId("V2@254016000000"), { kind: "video", track: 1, start: "254016000000" });
  assert.equal(clipId("audio", 0, "5"), "A1@5");
  for (const bad of ["V0@1", "X1@0", "V1@-5", "V1", ""]) assert.throws(() => parseClipId(bad));
});

test("read_timeline lists every track and clip with ids the edits accept", async () => {
  const { run } = setup();
  const t = await run.read_timeline({});
  assert.equal(t.name, "Edit");
  assert.equal(t.active, true);
  assert.deepEqual(t.tracks.map((x) => x.id), ["V1", "A1"]);
  assert.deepEqual(t.tracks[0].clips.map((c) => c.id), ["V1@0", `V1@${10n * S}`]);
  assert.equal(t.tracks[0].clips[1].in_ticks, String(30n * S));
  assert.equal(t.tracks[0].clips[0].disabled, false);
});

test("edit_clips moves, trims, disables and removes in ONE undo step", async () => {
  const { h, run } = setup();
  const before = h.undoSteps.length;
  await run.edit_clips({ edits: [
    { clip: `V1@${10n * S}`, op: "move", dt_ticks: String(5n * S) },
    { clip: `A1@${10n * S}`, op: "move", dt_ticks: String(5n * S) },
    { clip: "V1@0", op: "trim_in", in_ticks: String(2n * S) },
    { clip: "A1@0", op: "remove", ripple: false },
  ] });
  assert.equal(h.undoSteps.length, before + 1);
  const seq = h.sequence("Edit");
  assert.deepEqual(seq.video.map((c) => [c.start, c.end, c.in]), [[2n * S, 10n * S, 2n * S], [15n * S, 25n * S, 30n * S]]);
  assert.deepEqual(seq.audio.map((c) => c.start), [15n * S]);
});

test("edit_clips refuses a clip id that names nothing, before editing", async () => {
  const { h, run } = setup();
  const before = h.undoSteps.length;
  await assert.rejects(run.edit_clips({ edits: [{ clip: "V1@0", op: "disable" }, { clip: "V1@7", op: "disable" }] }), /no clip starts at 7/);
  assert.equal(h.undoSteps.length, before);
  assert.equal(h.sequence("Edit").video[0].disabled, undefined);
});

test("select_clips replaces the selection and read_timeline shows it", async () => {
  const { run } = setup();
  const out = await run.select_clips({ clips: ["V1@0", "A1@0"] });
  assert.deepEqual(out.selected, ["V1@0", "A1@0"]);
  const t = await run.read_timeline({});
  assert.deepEqual(t.tracks.flatMap((x) => x.clips.filter((c) => c.selected).map((c) => c.id)), ["V1@0", "A1@0"]);
  assert.deepEqual((await run.select_clips({ clips: [] })).selected, []);
});

// Live 2026-11-26: about a second after make_subsequence, one read of a track came back without its
// clips, and select_clips refused "A1@…: no clip starts at" a clip that was there (paste_pieces soak).
test("select_clips reads again when a track read comes back without its clips", async () => {
  const { h, run } = setup();
  const project = await h.ppro.Project.getActiveProject();
  const seq = await project.getActiveSequence();
  const getAudioTrack = seq.getAudioTrack.bind(seq);
  let bad = 1;
  seq.getAudioTrack = async (i) => {
    const t = await getAudioTrack(i);
    return Object.assign(Object.create(t), {
      getTrackItems: (...a) => (bad-- > 0 ? [] : t.getTrackItems(...a)),
    });
  };
  const out = await run.select_clips({ clips: ["V1@0", "A1@0"] });
  assert.deepEqual(out.selected, ["V1@0", "A1@0"]);
});

test("select_clips still refuses a clip that is missing from every read", async () => {
  const { run } = setup();
  await assert.rejects(run.select_clips({ clips: ["A1@7"] }), /no clip starts at 7 ticks on that track, in 4 reads/);
});

test("set_playhead and set_in_out read back what they set", async () => {
  const { h, run } = setup();
  assert.equal((await run.set_playhead({ ticks: String(3n * S) })).playhead_ticks, String(3n * S));
  const marks = await run.set_in_out({ in_ticks: String(S), out_ticks: String(9n * S) });
  assert.deepEqual([marks.in_ticks, marks.out_ticks], [String(S), String(9n * S)]);
  assert.deepEqual(h.sequence("Edit").marks, { in: S, out: 9n * S });
});

test("place_media overwrites a project item at a time and reports what landed", async () => {
  const { h, run } = setup();
  const out = await run.place_media({ media: "D:\\b.mp4", at_ticks: String(30n * S), v: 1, a: 1 });
  assert.deepEqual(out.placed.map((c) => c.id), [`V2@${30n * S}`, `A2@${30n * S}`]);
  assert.equal(h.sequence("Edit").video.find((c) => c.track === 1).media, "D:\\b.mp4");
});

test("a named sequence that does not exist is refused", async () => {
  const { run } = setup();
  await assert.rejects(run.read_timeline({ sequence: "Nope" }), /No sequence named "Nope"/);
});

test("read_timeline can read one track and one span at a time", async () => {
  const { run } = setup();
  const t = await run.read_timeline({ tracks: ["V1"], from_ticks: String(12n * S), to_ticks: String(15n * S) });
  assert.deepEqual(t.tracks.map((x) => x.id), ["V1"]);
  assert.deepEqual(t.tracks[0].clips.map((c) => c.id), [`V1@${10n * S}`]);
});

/* Component chains in Premiere's shape (PREMIERE_FACTS "Effects, components, keyframes"):
   index 0 Opacity, 1 Motion; a point value must be a PointF; keyframes need time-varying on first;
   a new effect is appended. Attached to the fake's cached track items. */
function chainFor(h) {
  const param = (displayName, value) => {
    const p = { displayName, value, varying: false, keys: [] };
    return Object.assign(p, {
      getStartValue: async () => ({ value: { value: p.value } }),
      isTimeVarying: () => p.varying,
      getKeyframeListAsTickTimes: () => p.keys.map((k) => fake.tickTime(k)),
      createKeyframe: (v) => ({ value: { value: v }, position: null }),
      createSetValueAction: (k) => fake.action(() => { p.value = k.value.value; }),
      createSetTimeVaryingAction: (on) => fake.action(() => { p.varying = on; }),
      createAddKeyframeAction: (k) => {
        if (!p.varying) throw new Error("fake: keyframe on a param that is not time-varying");
        return fake.action(() => { p.keys.push(k.position.ticks); p.value = k.value.value; });
      },
    });
  };
  const component = (matchName, params) => ({
    getMatchName: async () => matchName, getDisplayName: async () => matchName,
    getParamCount: () => params.length, getParam: (i) => params[i],
  });
  const chains = new Map();
  return (item) => {
    if (!chains.has(item)) {
      const comps = [component("AE.ADBE Opacity", [param("Opacity", 100)]),
        component("AE.ADBE Motion", [param("Position", new fake.PointF(0.5, 0.5)), param("Scale", 100)])];
      chains.set(item, {
        comps,
        getComponentCount: () => comps.length,
        getComponentAtIndex: (i) => comps[i],
        createAppendComponentAction: (c) => fake.action(() => comps.push(c)),
      });
    }
    return chains.get(item);
  };
}

async function withChains(h) {
  const chainOf = chainFor(h);
  const seq = (await h.project.getSequences())[0];
  for (const tr of [await seq.getVideoTrack(0), await seq.getAudioTrack(0)]) {
    for (const item of tr.getTrackItems()) item.getComponentChain = async () => chainOf(item);
  }
  return chainOf;
}

test("set_param writes a value, and a point as a PointF, in one undo step each", async () => {
  const { h, run } = setup();
  await withChains(h);
  const before = h.undoSteps.length;
  const out = await run.set_param({ clip: "V1@0", component: "AE.ADBE Motion", param: 0, value: [0.25, 0.75] });
  assert.ok(out.value instanceof fake.PointF);
  assert.deepEqual([out.value.x, out.value.y], [0.25, 0.75]);
  assert.equal((await run.set_param({ clip: "V1@0", component: 1, param: 1, value: 150 })).value, 150);
  assert.equal(h.undoSteps.length, before + 2);
  await assert.rejects(run.set_param({ clip: "V1@0", component: 1, param: 9, value: 1 }), /has 2 params/);
});

test("set_param at_ticks turns keyframing on first, then adds the keyframe", async () => {
  const { h, run } = setup();
  await withChains(h);
  const out = await run.set_param({ clip: "V1@0", component: 0, param: 0, value: 40, at_ticks: String(S) });
  assert.deepEqual(out.keyframes_ticks, [String(S)]);
  assert.deepEqual(h.undoSteps.slice(-2), ["CutDeck: keyframe Opacity on", "CutDeck: keyframe Opacity"]);
});

test("add_effect appends a video effect by match name and refuses an unknown one", async () => {
  const { h, run } = setup();
  await withChains(h);
  h.ppro.VideoFilterFactory = { createComponent: async (m) => (m === "AE.ADBE Gaussian Blur 2"
    ? { getMatchName: async () => m, getDisplayName: async () => "Gaussian Blur", getParamCount: () => 0, getParam: () => null } : null) };
  const out = await run.add_effect({ clips: ["V1@0"], effect: "AE.ADBE Gaussian Blur 2" });
  assert.deepEqual(out.clips[0].effects.map((e) => e.match_name), ["AE.ADBE Opacity", "AE.ADBE Motion", "AE.ADBE Gaussian Blur 2"]);
  const before = h.undoSteps.length;
  await assert.rejects(run.add_effect({ clips: ["V1@0"], effect: "Nope" }), /no video effect "Nope"/);
  assert.equal(h.undoSteps.length, before);
});

test("add_transition builds the options inside the transaction and refuses audio clips", async () => {
  const { h, run } = setup();
  const added = [];
  class AddTransitionOptions {
    setApplyToStart(v) { this.start = v; return this; }
    setDuration(t) { this.duration = t.ticks; return this; }
  }
  h.ppro.AddTransitionOptions = AddTransitionOptions;
  h.ppro.TransitionFactory = { createVideoTransition: async (m) => ({ m }) };
  const seq = (await h.project.getSequences())[0];
  for (const item of (await seq.getVideoTrack(0)).getTrackItems()) {
    item.createAddVideoTransitionAction = (tr, opts) => fake.action(() => added.push({ m: tr.m, start: opts.start, duration: opts.duration }));
  }
  await run.add_transition({ clips: ["V1@0"], transition: "AE.ADBE Cross Dissolve New", duration_ticks: String(S), at_start: true });
  assert.deepEqual(added, [{ m: "AE.ADBE Cross Dissolve New", start: true, duration: String(S) }]);
  await assert.rejects(run.add_transition({ clips: ["A1@0"], transition: "x" }), /video clips only/);
});

test("list_project lists sequences and the media in bins", async () => {
  const { run } = setup();
  await run.import_files({ paths: ["D:\\b.mp4"] });
  const out = await run.list_project({});
  assert.deepEqual(out.sequences, [{ name: "Edit", sequence_id: "seq0", active: true }]);
  assert.deepEqual(out.items, [{ name: "D:\\b.mp4", media: "D:\\b.mp4" }]);
});

test("a ripple remove is ONE action over video and audio (per-type ripples shifted twice live)", async () => {
  const { h, run } = setup();
  const calls = [];
  const getEditor = h.ppro.SequenceEditor.getEditor;
  h.ppro.SequenceEditor = { getEditor: (seq) => {
    const ed = getEditor(seq);
    return { ...ed, createRemoveItemsAction: (sel, ripple, type) => { calls.push([ripple, type]); return ed.createRemoveItemsAction(sel, ripple, type); } };
  } };
  await run.edit_clips({ edits: [{ clip: "V1@0", op: "remove", ripple: true }, { clip: "A1@0", op: "remove", ripple: true },
    { clip: `V1@${10n * S}`, op: "remove" }] });
  assert.deepEqual(calls, [[false, fake.Constants.MediaType.VIDEO], [true, fake.Constants.MediaType.ANY]]);
});

test("place_media fails when Premiere commits but nothing lands", async () => {
  const h = fake.createTimelineHost({
    media: [{ path: "D:\\a.mp4", video: true, audio: true, duration: 10n * S }],
    sequences: [{ name: "Edit", video: [[]], audio: [[]] }],
    place: () => 1n, // lands one tick off the asked time
  });
  await assert.rejects(controlHandlers(h.ppro).place_media({ media: "D:\\a.mp4", at_ticks: "0", v: 0, a: 0 }), /nothing landed/);
});

test("remove_rough_cuts deletes only copies in CutDeck > Rough Cuts, never the active one", async () => {
  const clip = [[{ media: "D:\a.mp4", start: 0n, end: 10n * S, in: 0n }]];
  const h = fake.createTimelineHost({
    media: [{ path: "D:\a.mp4", video: true, audio: true, duration: 60n * S }],
    sequences: ["Edit", "Edit cut", "Mine"].map((name) => ({ name, video: clip, audio: clip })),
  });
  const run = controlHandlers(h.ppro);
  await assert.rejects(run.remove_rough_cuts({ sequences: ["Edit cut"] }), /No bin "CutDeck"/);
  for (const name of ["Edit", "Edit cut"]) h.fileSequence(["CutDeck", "Rough Cuts"], name);
  h.fileSequence(["Sequences"], "Mine");
  await assert.rejects(run.remove_rough_cuts({ sequences: ["Edit cut", "Mine"] }), /"Mine" is not one sequence in CutDeck > Rough Cuts/);
  await assert.rejects(run.remove_rough_cuts({ sequences: ["Edit"] }), /active sequence/);
  assert.equal((await h.project.getSequences()).length, 3, "a refusal removes nothing");
  assert.deepEqual(await run.remove_rough_cuts({ sequences: ["Edit cut"] }), { removed: ["Edit cut"], still_there: [] });
  assert.deepEqual((await h.project.getSequences()).map((s) => s.name), ["Edit", "Mine"]);
});

// importSequences is unproven live (issue #130), so it lives in this test, not in the shared fake.
test("import_sequences passes Guids and reports only the sequences it added", async () => {
  const { h, run } = setup();
  const before = await h.project.getSequences();
  const calls = [];
  h.ppro.Guid = { fromString: (s) => ({ s }) };
  h.project.importSequences = async (path, ids) => {
    calls.push([path, ids.map((g) => g.s)]);
    h.project.getSequences = async () => [...before, { name: "Donor", guid: { toString: () => "g1" } }];
    return true;
  };
  const out = await run.import_sequences({ path: "D:\d.prproj", sequence_ids: ["g1"] });
  assert.deepEqual(calls, [["D:\d.prproj", ["g1"]]]);
  assert.deepEqual(out, { imported: true, sequences: [{ name: "Donor", sequence_id: "g1" }] });
});

test("make_subsequence cuts the range to a new named sequence and puts the source marks back", async () => {
  const { h, run } = setup();
  await run.set_in_out({ in_ticks: String(S), out_ticks: String(2n * S) });
  const out = await run.make_subsequence({ in_ticks: String(5n * S), out_ticks: String(15n * S), result_name: "Q1 (CutDeck piece)" });
  assert.deepEqual([out.name, out.clips], ["Q1 (CutDeck piece)", 4]);
  const sub = h.sequence("Q1 (CutDeck piece)");
  assert.deepEqual(sub.video.map((c) => [c.start, c.end, c.in]), [[0n, 5n * S, 5n * S], [5n * S, 10n * S, 30n * S]]);
  assert.deepEqual(h.sequence("Edit").marks, { in: S, out: 2n * S });
  assert.equal(h.sequence("Edit").video.length, 2);
  await assert.rejects(run.make_subsequence({ in_ticks: "0", out_ticks: String(S), result_name: "Q1 (CutDeck piece)" }), /already exists/);
});

// Premiere is shared by sessions, and the subsequence may become active: the marks go back on the
// source the command started from, never on whatever is active by then.
test("make_subsequence with no sequence named puts the marks back on its source when the active sequence changed", async () => {
  const { h, run } = setup();
  await run.set_in_out({ in_ticks: String(S), out_ticks: String(2n * S) });
  const all = h.project.getSequences.bind(h.project), active = h.project.getActiveSequence.bind(h.project);
  h.project.getActiveSequence = async () => (await all()).find((s) => s.name === "Q1 (CutDeck piece)" || s.name.startsWith("Edit_Sub_")) || active();
  await run.make_subsequence({ in_ticks: String(5n * S), out_ticks: String(15n * S), result_name: "Q1 (CutDeck piece)" });
  assert.deepEqual(h.sequence("Edit").marks, { in: S, out: 2n * S });
});

// A stale throw on the read after the remove committed must not run the remove again and report
// a piece it removed as not removed.
test("remove_piece reports a removal when the read after it went stale", async () => {
  const { h, run } = setup();
  await run.make_subsequence({ in_ticks: "0", out_ticks: String(S), result_name: "Q1 (CutDeck piece)" });
  const all = h.project.getSequences.bind(h.project);
  let thrown = false;
  h.project.getSequences = async () => {
    if (!thrown && h.undoSteps.includes("CutDeck: remove piece")) { thrown = true; throw new Error(fake.SCRIPT_OBJECT_INVALID); }
    return all();
  };
  assert.deepEqual(await run.remove_piece({ name: "Q1 (CutDeck piece)" }), { removed: true });
});

test("make_subsequence and remove_piece fetch fresh handles when one was stale, and refuse when every one is", async () => {
  const { h, run } = setup();
  fake.staleHandles(h);
  assert.equal((await run.make_subsequence({ in_ticks: "0", out_ticks: String(S), result_name: "Q1 (CutDeck piece)" })).name, "Q1 (CutDeck piece)");
  fake.staleHandles(h);
  assert.deepEqual(await run.remove_piece({ name: "Q1 (CutDeck piece)" }), { removed: true });
  const again = setup();
  fake.staleHandles(again.h, { persistent: true });
  await assert.rejects(again.run.make_subsequence({ in_ticks: "0", out_ticks: String(S), result_name: "Q2 (CutDeck piece)" }), /no longer valid/);
  assert.equal(again.h.sequence("Q2 (CutDeck piece)"), undefined);
});

test("remove_piece deletes only a CutDeck piece", async () => {
  const { h, run } = setup();
  await run.make_subsequence({ in_ticks: "0", out_ticks: String(S), result_name: "Q1 (CutDeck piece)" });
  await assert.rejects(run.remove_piece({ name: "Edit" }), /not a CutDeck piece/);
  assert.deepEqual(await run.remove_piece({ name: "Q1 (CutDeck piece)" }), { removed: true });
  assert.equal(h.sequence("Q1 (CutDeck piece)"), undefined);
});

test("remove_style_bin deletes only the root bin a restyle imported", async () => {
  const { h, run } = setup();
  const name = "CutDeck restyle 1a2b3c.prtextstyle";
  h.fileSequence([name], "CutDeck restyle 1a2b3c");
  h.fileSequence(["CFD SUBTITLE.prtextstyle"], "CFD SUBTITLE");
  await assert.rejects(run.remove_style_bin({ name: "CFD SUBTITLE.prtextstyle" }), /not a CutDeck restyle bin/);
  await assert.rejects(run.remove_style_bin({ name: "CutDeck restyle ffffff.prtextstyle" }), /0 root bins/);
  assert.deepEqual(await run.remove_style_bin({ name }), { removed: true });
  const left = (await (await h.project.getRootItem()).getItems()).map((it) => it.name);
  assert.deepEqual(left, ["CFD SUBTITLE.prtextstyle"]);
  assert.ok(h.undoSteps.includes("CutDeck: remove restyle bin"));
});

test("make_subsequence of a range that starts in a gap starts on its first clip (as Premiere does)", async () => {
  const { h, run } = setup();
  await run.edit_clips({ edits: [{ clip: "V1@0", op: "trim_in", in_ticks: String(2n * S) }, { clip: "A1@0", op: "trim_in", in_ticks: String(2n * S) }] });
  await run.make_subsequence({ in_ticks: String(S), out_ticks: String(5n * S), result_name: "gap (CutDeck piece)" });
  assert.deepEqual(h.sequence("gap (CutDeck piece)").video.map((c) => [c.start, c.end, c.in]), [[0n, 3n * S, 2n * S]]);
});
