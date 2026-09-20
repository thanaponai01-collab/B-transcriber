/* Phase 0 mutation probe for issue #25 — the three-point assemble route.

   Host mocks cannot establish Premiere's real behavior; that is what the human
   click is for (handoff section 10). What they establish is that the probe can
   TELL THE VERDICTS APART and survives every way the host can disappoint it — a
   probe that cannot distinguish "collapsed" from "independent", or that dies on a
   missing method, would burn a live click and come back with nothing.

   The host they run against (tests/fixtures/cutdeck_assemble_host.cjs) is a real
   little timeline: a shared ClipProjectItem with mutable in/out, actions that
   apply in order, and an overwrite that reads the project item when it applies.
   Its "collapsed" mode differs by one thing only — every setInOut applies before
   every overwrite — which is exactly the failure issue #25 predicts if the shared
   ClipProjectItem resolves against the last value written. */
const test = require("node:test");
const assert = require("node:assert/strict");
const probe = require("../uxp/cutdeck/assembleProbe.js");
const { runAssembleProbe, formatReport, planSpans, PROBE_SEQUENCE_NAME } = probe;

const TPS = 254016000000n;
const TPF_2997 = 8475667200n;   // 30000/1001
const TPF_25 = 10160640000n;    // 25
const TPF_5994 = 4237833600n;   // 60000/1001

const answer = (report, id) => (report.findings.find((f) => f.id === id) || {}).answer;
const evidence = (report, id) => (report.findings.find((f) => f.id === id) || {}).evidence || {};

/* The mock host lives in tests/fixtures/cutdeck_assemble_host.cjs so that the report
   rendered for a human is produced by the same timeline these tests assert against. */
const { makeHost } = require("./fixtures/cutdeck_assemble_host.cjs");

const run = (opts) => {
  const host = makeHost(opts);
  return runAssembleProbe(host.ppro, () => {}).then((report) => ({ report, host }));
};

/* The "executeTransaction is never called bare" assertion below is only worth
   anything if the fixture cannot leak a lock depth across a failed transaction —
   otherwise a later bare call would inherit a stale "locked" reading. No probe path
   throws and then commits again, so this is checked on the fixture directly. */
test("the fixture balances its lock even when a staged action throws", async () => {
  const { ppro, calls } = makeHost({});
  const project = await ppro.Project.getActiveProject();
  assert.throws(() => project.lockedAccess(() => project.executeTransaction(() => {
    throw new Error("staged action blew up");
  }, "throwing")), /staged action blew up/);
  const opens = calls.lockedNesting.filter((e) => e === "open").length;
  assert.equal(opens, calls.lockedNesting.filter((e) => e === "close").length);
  project.lockedAccess(() => project.executeTransaction(() => {}, "after the throw"));
  assert.deepEqual(calls.transactions.map((t) => t.locked), [true, true]);
});

/* ------------------------------------------------- the span plan, before any host */

test("the three spans have distinct starts AND distinct lengths, and tile back to back", () => {
  const plan = planSpans(0n, 120n * TPF_2997, TPF_2997, 0n);
  assert.equal(plan.ok, true);
  assert.equal(plan.unitFrames, 10n);
  assert.deepEqual(plan.spans.map((s) => s.lengthFrames), [10n, 20n, 30n]);
  assert.equal(new Set(plan.spans.map((s) => s.sourceInTicks.toString())).size, 3, "starts must differ");
  assert.equal(new Set(plan.spans.map((s) => s.lengthTicks.toString())).size, 3, "lengths must differ");
  for (let i = 1; i < plan.spans.length; i++) {
    assert.equal(plan.spans[i].destinationTicks, plan.spans[i - 1].destinationTicks + plan.spans[i - 1].lengthTicks,
      "placements must share a boundary tick exactly — a gap here is a black flash");
  }
  assert.equal(plan.predictedEndFrames, 60n);
  // Never reads past the source clip.
  assert.ok(plan.spans[2].sourceOutTicks <= 120n * TPF_2997);
});

test("every span boundary is an exact whole frame at every rate this project has met", () => {
  for (const tpf of [TPF_2997, TPF_25, TPF_5994, 10594584000n]) {
    const plan = planSpans(0n, 120n * tpf, tpf, 7n * tpf);
    assert.equal(plan.ok, true);
    for (const span of plan.spans) {
      assert.equal(span.sourceInTicks % tpf, 0n);
      assert.equal(span.lengthTicks % tpf, 0n);
      assert.equal(span.destinationTicks % tpf, 0n);
    }
  }
});

test("a clip too short for three distinct spans is refused before anything is created", async () => {
  assert.equal(planSpans(0n, 11n * TPF_2997, TPF_2997, 0n).ok, false);
  const { report, host } = await run({ sourceFrames: 11n });
  assert.equal(answer(report, "spans"), "no");
  assert.equal(report.builtSequenceName, null, "no sequence may exist after a refusal");
  assert.equal(report.cleanup, "Nothing was created.");
  assert.equal(host.calls.transactions.length, 0);
});

/* ----------------------------------------------------- unknown 1: timebase settings */

test("a build that carries the source timebase across reads as INHERITED and continues", async () => {
  const { report, host } = await run({ tpf: TPF_2997 });
  assert.equal(report.verdicts.settings, "inherited");
  assert.match(answer(report, "settings"), /INHERITED/);
  assert.equal(evidence(report, "settings").sourceRate, "29.97");
  assert.equal(host.builtTimebase, TPF_2997);
  assert.notEqual(report.verdicts.placement, null, "an inherited timebase must not stop the probe");
});

test("a fabricated 25 fps destination is caught and stops the probe — issue #25's silent corruption", async () => {
  const { report } = await run({ tpf: TPF_2997, settingsNoop: true, newSequenceTimebase: TPF_25 });
  assert.equal(report.verdicts.settings, "fabricated");
  assert.match(answer(report, "settings"), /FABRICATED/);
  assert.match(answer(report, "settings"), /REFUSE and stop/);
  assert.equal(evidence(report, "settings").sourceRate, "29.97");
  assert.equal(evidence(report, "settings").newRate, "25");
  // Measuring placement against a wrong-rate destination would produce a number
  // worth nothing, so it is not measured at all.
  assert.equal(report.verdicts.placement, null);
  assert.equal(answer(report, "stopped"), "no");
  assert.equal(report.complete, true, "stopping on a real answer is a complete probe, not a crash");
});

test("59.94 is checked as carefully as 29.97 — both rates a fabricated 25 would corrupt", async () => {
  const good = await run({ tpf: TPF_5994 });
  assert.equal(good.report.verdicts.settings, "inherited");
  assert.equal(evidence(good.report, "settings").newRate, "59.94");
  const bad = await run({ tpf: TPF_5994, settingsNoop: true, newSequenceTimebase: TPF_25 });
  assert.equal(bad.report.verdicts.settings, "fabricated");
});

test("a destination whose timebase cannot be read is UNREADABLE, not assumed good", async () => {
  const { report } = await run({ newSequenceTimebase: null, settingsNoop: true });
  assert.equal(report.verdicts.settings, "unreadable");
  assert.equal(report.verdicts.placement, null);
});

/* ------------------------------------------------------- unknown 2: N=3 placements */

test("three distinct ranges in one transaction reads as INDEPENDENT — the cheap path lives", async () => {
  const { report, host } = await run({});
  assert.equal(report.verdicts.placement, "independent");
  assert.match(answer(report, "placement"), /YES — three distinct ranges/);
  assert.equal(evidence(report, "placement").seams, "none");
  // Three at the moment placement was judged. The track itself is down to two by
  // the end of the probe, because unknown 3 ripples one out.
  assert.equal(evidence(report, "placement").items.length, 3);
  // Both transactions of the placement stage arrived from inside lockedAccess.
  assert.ok(host.calls.transactions.length >= 2);
  assert.ok(host.calls.transactions.every((t) => t.locked), "executeTransaction must never be called bare");
});

test("a shared ClipProjectItem resolving against the last setInOut reads as COLLAPSED", async () => {
  const { report, host } = await run({ mode: "collapsed" });
  assert.equal(report.verdicts.placement, "collapsed");
  assert.match(answer(report, "placement"), /COLLAPSED/);
  assert.match(answer(report, "placement"), /one transaction per span/);
  // The signature is real, not asserted: all three items share one media In and length.
  const states = host.builtTrack.items.map((i) => i._state);
  assert.equal(new Set(states.map((s) => s.mediaIn.toString())).size, 1);
  assert.equal(new Set(states.map((s) => (s.end - s.start).toString())).size, 1);
  assert.equal(report.verdicts.removal, null, "removal is not measured on a collapsed assembly");
});

test("an overwrite that silently eats a frame is caught as a seam, not passed as success", async () => {
  const { report } = await run({ eatTicks: TPF_2997 });
  assert.equal(report.verdicts.placement, "distinct but wrong");
  const seams = evidence(report, "placement").seams;
  assert.equal(seams.length, 2, "both interior boundaries should report a gap");
  assert.match(seams[0], /1 frame\(s\) GAP/);
  assert.equal(report.verdicts.removal, null);
});

test("a placement transaction that throws is recorded, and the probe still reports", async () => {
  const { report } = await run({ noOverwrite: true });
  assert.equal(report.verdicts.placement, "threw");
  assert.match(answer(report, "placement"), /NO — it threw/);
  assert.match(evidence(report, "placement").meaning, /one transaction per span/);
  assert.equal(report.complete, true);
});

test("a missing createSetInOutPointsAction is a finding, not an unhandled rejection", async () => {
  const { report } = await run({ noSetInOut: true });
  assert.equal(report.verdicts.placement, "threw");
  assert.match(evidence(report, "placement").error, /createSetInOutPointsAction/);
});

/* ------------------------------ linked audio: the rough-cut route's own question ----
   createOverwriteItemAction takes a video AND an audio track index, and the probe
   passes (0, 0). Whether audio actually lands decides whether the handoff's "Add to
   Rough Cut" needs one call per range or two, and whether issue #25's silence cut
   keeps its dialogue. Free to ask in the same click. ---- */

test("audio landing on the video's exact boundaries reads as LINKED", async () => {
  const { report, host } = await run({ audio: "linked" });
  assert.equal(report.verdicts.audio, "linked");
  assert.match(answer(report, "linkedAudio"), /YES — 3 audio item\(s\) on A1/);
  // The alignment is real in the fixture, not just asserted in the message.
  const v = host.builtTrack.items.map((i) => i._state.start.toString());
  const a = host.builtAudioTrack.items.map((i) => i._state.start.toString());
  assert.deepEqual(a, v);
});

test("a video-only overwrite is called out as a route question, not a detail", async () => {
  const { report, host } = await run({ audio: "none" });
  assert.equal(report.verdicts.audio, "video only");
  assert.match(answer(report, "linkedAudio"), /NO — A1 is empty/);
  assert.match(answer(report, "linkedAudio"), /without dialogue is useless/);
  assert.equal(host.builtAudioTrack.items.length, 0);
  // Not a stop: unknown 3 is still worth measuring, so the one click still pays.
  assert.equal(report.verdicts.removal, "exact");
  // And the ripple question must not claim orphaned audio when there was none.
  assert.match(answer(report, "removalAudio"), /not applicable — A1 was empty/);
});

test("audio that lands but drifts is MISALIGNED — sync cannot be assumed", async () => {
  const { report } = await run({ audio: "misaligned" });
  assert.equal(report.verdicts.audio, "misaligned");
  assert.match(answer(report, "linkedAudio"), /PARTIALLY/);
  assert.equal(evidence(report, "linkedAudio").audioItemCount, 3);
});

test("a destination with no audio track is recorded, not treated as silence", async () => {
  const { report } = await run({ audio: "noTrack" });
  assert.equal(report.verdicts.audio, "no audio track");
  assert.match(answer(report, "linkedAudio"), /no audio track 0/);
  assert.equal(report.verdicts.removal, "exact", "a video-only destination still answers unknown 3");
});

test("the audio question is still asked when the placement collapsed", async () => {
  const { report } = await run({ mode: "collapsed" });
  assert.equal(report.verdicts.placement, "collapsed");
  assert.notEqual(report.verdicts.audio, null, "a collapsed assembly still shows whether A1 got anything");
});

test("a ripple that leaves the audio behind is caught — orphaned dialogue", async () => {
  const clean = await run({});
  assert.match(answer(clean.report, "removalAudio"), /yes — A1 went from 3 to 2 items/);
  assert.equal(clean.host.builtAudioTrack.items.length, 2);

  // The video length is still exactly right here, which is precisely the trap: a
  // length-only check calls this a success. The verdict has to carry the failure.
  const orphaned = await run({ removeLeavesAudio: true });
  assert.equal(orphaned.report.verdicts.removal, "exact, but audio orphaned");
  assert.match(answer(orphaned.report, "removal"), /LEFT BEHIND/);
  assert.match(answer(orphaned.report, "removalAudio"), /NO — A1 still has 3 item\(s\)/);
  assert.match(answer(orphaned.report, "removalAudio"), /worse than not cutting at all/);
  assert.equal(orphaned.host.builtAudioTrack.items.length, 3);
  assert.match(formatReport(orphaned.report), /removal:\s+exact, but audio orphaned/,
    "the verdict block is what a human reads first — the orphan must be visible there");
});

/* --------------------------------------------- unknown 3: disable then ripple-remove */

test("ripple-remove shrinks the assembly by exactly the disabled span", async () => {
  const { report, host } = await run({});
  assert.equal(report.verdicts.removal, "exact");
  assert.match(answer(report, "removal"), /shrank by exactly the disabled span \(20 frames\)/);
  assert.equal(evidence(report, "removal").before, (60n * TPF_2997).toString());
  assert.equal(evidence(report, "removal").after, (40n * TPF_2997).toString());
  // And the remaining two spans really did close up, rather than leaving a hole.
  assert.equal(host.builtTrack.items.length, 2);
  assert.equal(host.builtTrack.items[0]._state.end, host.builtTrack.items[1]._state.start);
});

test("the disable step is verified by reading isDisabled back, not by the commit returning", async () => {
  const { report } = await run({});
  assert.match(answer(report, "disable"), /isDisabled\(\) confirms it/);
  assert.equal(evidence(report, "disable").isDisabled, true);
});

test("a missing createSetDisabledAction stops before removal and says so", async () => {
  const { report } = await run({ noDisable: true });
  assert.match(answer(report, "disable"), /NO — it threw/);
  assert.equal(report.verdicts.removal, "not reached — disable failed");
});

test("a removal that refuses is reported as the blocker it is — Apply rests on that call", async () => {
  const { report } = await run({ removeThrows: true });
  assert.equal(report.verdicts.removal, "threw");
  assert.match(evidence(report, "removal").meaning, /Apply is built entirely on this call/);
});

test("a missing createRemoveItemsAction is a finding, and the selection route used is recorded", async () => {
  const { report } = await run({ noRemove: true });
  assert.equal(report.verdicts.removal, "threw");
  assert.equal(evidence(report, "removal").selectionVia, "getSelection().addItem");
  assert.equal(answer(report, "selection"), "Sequence.getSelection() + addItem(item, false)");
});

/* ------------------------------------------------------------------ error paths */

test("no host, no project, no sequence, no track and no clip each stop cleanly", async () => {
  const none = await runAssembleProbe(null, () => {});
  assert.equal(answer(none, "host"), "no");
  assert.equal(none.complete, false);
  assert.equal(none.cleanup, "Nothing was created.");

  assert.equal(answer((await run({ noProject: true })).report, "project"), "no");
  assert.equal(answer((await run({ noSequence: true })).report, "sequence"), "no");
  assert.equal(answer((await run({ noVideoTrack: true })).report, "sourceClip"), "no video track 0");

  const noEditor = await run({ noEditor: true });
  assert.equal(answer(noEditor.report, "editor"), "no");
  assert.equal(noEditor.report.verdicts.placement, null);
});

test("a build with no createSequence stops before claiming anything was built", async () => {
  const { report } = await run({ noCreateSequence: true });
  assert.equal(answer(report, "createSequence"), "no");
  assert.equal(report.builtSequenceName, null);
  assert.equal(report.verdicts.settings, null);
});

/* Named because several of these carry BigInts, which a template literal cannot
   stringify — the assertion message has to survive the case it is describing. */
const BUILT_CASES = [
  ["the happy path", {}],
  ["a collapsed assembly", { mode: "collapsed" }],
  ["a fabricated timebase", { settingsNoop: true }],
  ["a placement that threw", { noOverwrite: true }],
  ["a removal that refused", { removeThrows: true }],
  ["an overwrite that ate a frame", { eatTicks: TPF_2997 }],
  ["a video-only overwrite", { audio: "none" }],
  ["a destination with no audio track", { audio: "noTrack" }],
  ["a ripple that orphaned the audio", { removeLeavesAudio: true }],
];

test("the probe NEVER deletes what it built — a partial build is the evidence", async () => {
  for (const [label, opts] of BUILT_CASES) {
    const { report, host } = await run(opts);
    assert.equal(host.calls.deleteSequence, 0, `deleteSequence was called for ${label}`);
    assert.equal(report.builtSequenceName, PROBE_SEQUENCE_NAME, label);
    assert.match(report.cleanup, /DELETE IT BY HAND/);
  }
});

test("a source with no readable settings still stops on the timebase, not on a crash", async () => {
  const { report } = await run({ noSettings: true, newSequenceTimebase: TPF_25 });
  assert.equal(report.verdicts.settings, "fabricated");
  assert.match(JSON.stringify(evidence(report, "settings").applied), /getSettings/);
});

/* --------------------------------------------------------------------- reporting */

test("every report serializes to JSON — the panel logs them, and a stray BigInt would throw", async () => {
  const cases = [...BUILT_CASES, ["a clip too short to probe", { sourceFrames: 11n }],
    ["a build with no createRemoveItemsAction", { noRemove: true }]];
  for (const [label, opts] of cases) {
    const { report } = await run(opts);
    assert.doesNotThrow(() => JSON.stringify(report), `BigInt leaked for ${label}`);
  }
});

test("the formatted report names all four verdicts and the cleanup the human owes", async () => {
  const { report } = await run({});
  const text = formatReport(report);
  assert.match(text, /issue #25/);
  assert.match(text, /settings:\s+inherited/);
  assert.match(text, /placement: independent/);
  assert.match(text, /audio:\s+linked/);
  assert.match(text, /removal:\s+exact/);
  assert.match(text, /DELETE IT BY HAND/);
  const stopped = formatReport((await run({ settingsNoop: true })).report);
  assert.match(stopped, /placement: not reached/);
});

test("the tick grid the probe rounds against divides every rate it claims to know", () => {
  assert.equal(TPS * 1001n / 30000n, TPF_2997);
  assert.equal(TPS * 1001n / 60000n, TPF_5994);
  assert.equal(TPS / 25n, TPF_25);
  assert.equal(probe.identifyRate(TPF_5994), "59.94");
  assert.equal(probe.identifyRate(12345n), null);
});

test("inexact tick values from the host are refused rather than silently rounded", () => {
  assert.throws(() => probe.toTicks({ ticks: "12.5" }, "x"), /not a tick value/);
  assert.throws(() => probe.toTicks(2 ** 53 + 2, "x"), /not an exact tick count/);
  assert.throws(() => probe.toTicks(null, "x"), /absent/);
  assert.equal(probe.toTicks({ ticks: "8475667200" }, "x"), TPF_2997);
});
