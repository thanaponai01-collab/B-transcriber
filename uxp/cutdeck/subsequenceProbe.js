/* Probe: does Make Subsequence give a real sequence of a range, every track and effect kept?
   (docs/DERIVE_FROM_SEQUENCE.md step 1). Runs only on "CutDeck verify (scratch)": sets its In/Out
   to 1 s / 4 s, calls createSubsequence(true), reads the new sequence back, then puts the
   scratch In/Out back. The new sequence is left in the project for the user to see or delete.

   APIs, each in reference/adobe/api/premierepro.txt and reference/adobe/docs/ppro-reference/
   classes/sequence.md: Project.getActiveProject / getSequences, Sequence.createSetInPointAction /
   createSetOutPointAction / getInPoint / getOutPoint / createSubsequence (25.6; Adobe sample
   sample-panels/premiere-api/src/sequence.ts calls it with true), TickTime.createWithTicks. */

const { runTransaction } = require("./host/project.js");
const { readSequence } = require("./host/sequenceRead.js");
const { toTicks, TICKS_PER_SECOND, makeTickTime } = require("./host/ticks.js");
const { readTransform } = require("./transform/params.js");

const SCRATCH = "CutDeck verify (scratch)";
const IN_S = 1;
const OUT_S = 4;

async function clipsOf(ppro, seq) {
  const read = await readSequence(ppro, seq, { paths: true });
  const one = async (c) => {
    const t = c.kind === "video" ? await readTransform(c.item).catch(() => null) : null;
    return {
      kind: c.kind, track: c.track, start: c.start.toString(), end: c.end.toString(),
      inPoint: c.inPoint.toString(), path: c.path, colorLabel: c.colorLabel,
      scale: t && t.scale !== undefined ? t.scale : null,
    };
  };
  return {
    videoTracks: read.videoTracks, audioTracks: read.audioTracks,
    clips: await Promise.all([...read.video, ...read.audio].map(one)),
  };
}

async function probeSubsequence(ppro) {
  const project = await ppro.Project.getActiveProject();
  const seqs = await project.getSequences();
  const scratch = seqs.find((s) => s.name === SCRATCH);
  if (!scratch) throw new Error(`Refused: no sequence "${SCRATCH}" (run cdv.py scratch).`);
  const tick = makeTickTime(ppro);
  const tps = BigInt(TICKS_PER_SECOND);
  const oldIn = toTicks(await scratch.getInPoint());
  const oldOut = toTicks(await scratch.getOutPoint());
  const before = await clipsOf(ppro, scratch);

  runTransaction(project, "CutDeck probe: scratch In/Out", (compound) => {
    compound.addAction(scratch.createSetInPointAction(tick(BigInt(IN_S) * tps)));
    compound.addAction(scratch.createSetOutPointAction(tick(BigInt(OUT_S) * tps)));
  });
  const marks = { in: toTicks(await scratch.getInPoint()).toString(), out: toTicks(await scratch.getOutPoint()).toString() };

  const guidsBefore = new Set(seqs.map((s) => s.guid.toString()));
  let sub = null;
  let error = null;
  const t0 = Date.now();
  try {
    sub = await scratch.createSubsequence(true);
  } catch (e) {
    error = String((e && e.message) || e);
  }
  const ms = Date.now() - t0;
  const added = (await project.getSequences()).filter((s) => !guidsBefore.has(s.guid.toString()));
  const result = sub || added[0] || null;

  runTransaction(project, "CutDeck probe: restore scratch In/Out", (compound) => {
    compound.addAction(scratch.createSetInPointAction(tick(oldIn)));
    compound.addAction(scratch.createSetOutPointAction(tick(oldOut)));
  });

  return {
    marks, error, ms, returned: Boolean(sub), newSequences: added.map((s) => s.name),
    before,
    sub: result ? { name: result.name, ...(await clipsOf(ppro, result)) } : null,
    scratchAfter: await clipsOf(ppro, scratch),
  };
}

const formatReport = (r) => JSON.stringify(r, null, 2);

module.exports = { probeSubsequence, formatReport };
