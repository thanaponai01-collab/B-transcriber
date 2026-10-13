/* "Test Ripple Delete": can Rough Cut close its gaps with createRemoveItemsAction(ripple=true)
   instead of one createMoveAction per surviving piece (16,506 moves on a 1,735-cut run)?
   PREMIERE_FACTS lists ripple=true as UNPROBED: it may follow sync-lock state the API can't read.
   APIs: all declared in reference/adobe/api/premierepro.txt (26.5.1); copy/rename/open as in
   nativeCut.js (PREMIERE_FACTS: Sequence.createCloneAction is its own transaction).

   It copies the active sequence, runs Rough Cut's own applyPlan on the copy with two short test
   cuts and `ripple: true`, then compares the copy with the plan exactly as a real Rough Cut does
   (verifyReadBack). Your sequence is not edited.

   A ripple only closes the length of what it removes. Where a cut covers empty space on a track
   and a clip starts after it (a camera that starts late), that clip must still shift by the whole
   cut. The fake host showed per-track ripple gets this wrong (21 of 66 rows on the golden stack),
   so the first test cut is placed over such a clip's head when the sequence has one, and the
   report says whether that case was exercised. */

const { runTransaction, activeProjectAndSequence } = require("./host/project.js");
const { TICKS_PER_SECOND, toTicks } = require("./host/ticks.js");
const { applyPlan, readItems } = require("./timeline/nativeCut.js");
const { planCutApply, verifyReadBack, overlapsCut, timecode } = require("./timeline/cutPlanApply.js");

const TEST_SUFFIX = " — CutDeck ripple test";
const HALF = TICKS_PER_SECOND / 2n;

const lane = (it) => `${it.mediaType} track ${it.track + 1}`;
const covered = (items, a, b) => items.some((it) => it.startTicks <= a && it.endTicks >= b);

/* Two frame-aligned test cuts. Preferred: cut A straddles the head of a clip that starts after
   empty space on its track while another track has a clip there; cut B is inside that clip. */
function chooseCuts(items, tpf) {
  const snap = (t) => (t / tpf) * tpf;
  const late = items.find((it) => it.startTicks - HALF > 0n && it.endTicks - it.startTicks > 4n * TICKS_PER_SECOND
    && !items.some((o) => lane(o) === lane(it) && o !== it && o.endTicks > it.startTicks - HALF && o.startTicks < it.startTicks)
    && covered(items.filter((o) => lane(o) !== lane(it)), it.startTicks - HALF, it.startTicks + 3n * TICKS_PER_SECOND));
  if (late) {
    const s = late.startTicks;
    return { emptySpaceCase: true, cuts: [[snap(s - HALF), snap(s + HALF)], [snap(s + 2n * TICKS_PER_SECOND), snap(s + 2n * TICKS_PER_SECOND + HALF)]] };
  }
  const base = items.find((it) => it.endTicks - it.startTicks >= 4n * TICKS_PER_SECOND);
  if (!base) return null;
  const s = base.startTicks;
  return { emptySpaceCase: false, cuts: [[snap(s + TICKS_PER_SECOND), snap(s + TICKS_PER_SECOND + HALF)], [snap(s + 5n * HALF), snap(s + 3n * TICKS_PER_SECOND)]] };
}

async function probeRippleDelete(ppro) {
  const report = { verdict: "error", sequence: null, copyName: null, cuts: [], emptySpaceCase: false, problems: [], problemCount: 0, byLane: {} };
  try {
    const { project, sequence: source } = await activeProjectAndSequence(ppro);
    report.sequence = source.name;
    const tpf = toTicks(await source.getTimebase());
    const chosen = chooseCuts((await readItems(ppro, source, null)).items, tpf);
    if (!chosen) { report.verdict = "no-clip"; return report; }
    const { cuts } = chosen;
    report.emptySpaceCase = chosen.emptySpaceCase;
    report.cuts = cuts.map(([a, b]) => `${timecode(a)}-${timecode(b)}`);
    const before = await readItems(ppro, source, cuts);
    const refusal = planCutApply(before.transitions, cuts).refusal || planCutApply(before.items, cuts).refusal;
    if (refusal) { report.verdict = "refused"; report.problems = [refusal]; return report; }

    const beforeIds = new Set((await project.getSequences()).map((s) => s.guid.toString()));
    runTransaction(project, "CutDeck: copy sequence (ripple test)", (compound) => {
      if (!compound.addAction(source.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
    });
    const created = (await project.getSequences()).filter((s) => !beforeIds.has(s.guid.toString()));
    if (created.length !== 1) throw new Error(`Copying the sequence gave ${created.length} new sequences`);
    const copy = created[0];
    report.copyName = `${source.name}${TEST_SUFFIX}`;
    const copyItem = await copy.getProjectItem();
    runTransaction(project, "CutDeck: name ripple test", (compound) => {
      if (!compound.addAction(copyItem.createSetNameAction(report.copyName))) throw new Error("addAction(rename) returned false");
    });

    const plan = planCutApply(before.items, cuts);
    await applyPlan(ppro, project, copy, before.items, cuts, toTicks(await copy.getTimebase()), undefined, { ripple: true });
    const actual = (await readItems(ppro, copy, null)).items;
    await project.openSequence(copy);
    await project.setActiveSequence(copy);

    const problems = verifyReadBack(before.items, plan, actual);
    report.problemCount = problems.length;
    report.problems = problems.slice(0, 10);
    for (const p of problems) {
      const m = p.match(/on (\w+ track \d+)/);
      if (m) report.byLane[m[1]] = (report.byLane[m[1]] || 0) + 1;
    }
    report.lanesWithCutPieces = new Set(before.items.filter((it) => overlapsCut(it.startTicks, it.endTicks, cuts)).map(lane)).size;
    report.verdict = problems.length ? "mismatch" : "exact";
  } catch (error) {
    report.verdict = "error";
    report.error = (error && error.message) || String(error);
  }
  return report;
}

function formatRippleReport(r) {
  const lines = [];
  if (r.verdict === "exact") {
    lines.push("Ripple delete closed every gap exactly: the copy matches the Rough Cut plan.");
    lines.push(r.emptySpaceCase
      ? "Includes a cut over empty space before a later clip, the case per-track ripple gets wrong."
      : "Not tested: a cut over empty space before a later clip (no such clip found). Run it on a synced multicam sequence too.");
  } else if (r.verdict === "mismatch") {
    lines.push(`Ripple delete did NOT match the plan: ${r.problemCount} problem(s). Rough Cut keeps moving pieces itself.`);
    lines.push(`Per track: ${Object.entries(r.byLane).map(([k, n]) => `${k} ${n}`).join(", ")}`);
    for (const p of r.problems) lines.push(`  ${p}`);
  } else if (r.verdict === "refused") {
    lines.push(`Not run: ${r.problems[0]}`);
  } else if (r.verdict === "no-clip") {
    lines.push("Not run: no clip of 4 s or longer on the active sequence.");
  } else {
    lines.push(`Ripple test stopped: ${r.error}`);
  }
  if (r.cuts.length) lines.push(`Test cuts: ${r.cuts.join(", ")} on "${r.sequence}".`);
  if (r.copyName) lines.push(`Result left open as "${r.copyName}". Your sequence was not edited.`);
  return lines.join("\n");
}

module.exports = { probeRippleDelete, formatRippleReport, chooseCuts };
