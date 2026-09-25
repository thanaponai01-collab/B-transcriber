const test = require("node:test");
const assert = require("node:assert/strict");

const { pickPlacementTracks } = require("../uxp/cutdeck/timeline/adjustmentLayer.js");

// Fake sequence: `tracks` is one entry per video track — an array of [start, end) tick
// pairs, or "unreadable" (every getTrackItems call throws). Counts track reads.
function fakeSeq(tracks) {
  const reads = new Array(tracks.length).fill(0);
  const seq = {
    reads,
    getVideoTrackCount: async () => tracks.length,
    getVideoTrack: async (v) => ({
      getTrackItems: async () => {
        reads[v]++;
        if (tracks[v] === "unreadable") throw new Error("track read failed");
        return tracks[v].map(([s, e], i) => ({
          name: `V${v + 1} clip ${i}`,
          getStartTime: async () => ({ ticks: String(s) }),
          getEndTime: async () => ({ ticks: String(e) }),
        }));
      },
    }),
  };
  return seq;
}

const PPRO = { Constants: { TrackItemType: { CLIP: 1 } } };
const place = (s, e) => ({ name: `AL ${s}-${e}`, startTicks: BigInt(s), endTicks: BigInt(e) });

test("track pick: empty V2 takes every non-overlapping placement", async () => {
  const seq = fakeSeq([[[0, 1000]], [], []]);
  const targets = await pickPlacementTracks(PPRO, seq, [place(100, 200), place(500, 600)]);
  assert.deepEqual(targets, [1, 1]);
});

test("track pick: footage on V2 anywhere in the lane's range moves the whole lane up", async () => {
  // V2 footage sits between the two placements — neither span touches it, but the lane's
  // union does, so the lane stays together on V3 rather than splitting.
  const seq = fakeSeq([[[0, 1000]], [[300, 400]], []]);
  const targets = await pickPlacementTracks(PPRO, seq, [place(100, 200), place(500, 600)]);
  assert.deepEqual(targets, [2, 2]);
});

test("track pick: overlapping placements stack on separate tracks, lower lane first", async () => {
  const seq = fakeSeq([[[0, 1000]], [], []]);
  const targets = await pickPlacementTracks(PPRO, seq, [place(100, 300), place(200, 400)]);
  assert.deepEqual(targets, [1, 2]);
});

test("track pick: a full timeline places on the next, not-yet-existing track", async () => {
  const seq = fakeSeq([[[0, 1000]], [[0, 1000]]]);
  const targets = await pickPlacementTracks(PPRO, seq, [place(100, 200)]);
  assert.deepEqual(targets, [2]);
});

test("track pick: an unreadable track is treated as occupied, never placed on", async () => {
  const seq = fakeSeq([[[0, 1000]], "unreadable", []]);
  const targets = await pickPlacementTracks(PPRO, seq, [place(100, 200)]);
  assert.deepEqual(targets, [2]);
});

test("track pick: footage above V1 doesn't pull a lane below it", async () => {
  // V4 has footage in range, V2/V3 free: the lane goes above the highest occupied track.
  const seq = fakeSeq([[[0, 1000]], [], [], [[150, 180]], []]);
  const targets = await pickPlacementTracks(PPRO, seq, [place(100, 200)]);
  assert.deepEqual(targets, [4]);
});

test("track pick: nothing to place reads nothing and returns no targets", async () => {
  const seq = fakeSeq([[[0, 1000]]]);
  assert.deepEqual(await pickPlacementTracks(PPRO, seq, []), []);
});

test("track pick: reads each track once, plus one re-read of the chosen track", async () => {
  // 30 cut transitions in one lane over 4 tracks. The old scan re-read the chosen
  // track once per placement (65 reads here).
  const seq = fakeSeq([[[0, 100000]], [[40000, 41000]], [], []]);
  const pl = [];
  for (let i = 0; i < 30; i++) pl.push(place(i * 3000 + 1000, i * 3000 + 1500));
  const targets = await pickPlacementTracks(PPRO, seq, pl);
  assert.deepEqual([...new Set(targets)], [2]);
  assert.deepEqual(seq.reads, [1, 1, 2, 1]);
});

test("track pick: footage appearing on the chosen track before placing aborts", async () => {
  const tracks = [[[0, 1000]], [], []];
  const seq = fakeSeq(tracks);
  const original = seq.getVideoTrack;
  seq.getVideoTrack = async (v) => {
    const track = await original(v);
    const read = track.getTrackItems;
    // After the snapshot, a clip lands on V2 under the planned AL.
    track.getTrackItems = async () => {
      if (v === 1 && seq.reads[1] >= 1) tracks[1] = [[150, 160]];
      return read();
    };
    return track;
  };
  await assert.rejects(pickPlacementTracks(PPRO, seq, [place(100, 200)]), /V2 changed while placing/);
});

test("track pick: the chosen track becoming unreadable before placing aborts", async () => {
  const tracks = [[[0, 1000]], [], []];
  const seq = fakeSeq(tracks);
  const original = seq.getVideoTrack;
  seq.getVideoTrack = async (v) => {
    const track = await original(v);
    const read = track.getTrackItems;
    track.getTrackItems = async () => {
      if (v === 1 && seq.reads[1] >= 1) tracks[1] = "unreadable";
      return read();
    };
    return track;
  };
  await assert.rejects(pickPlacementTracks(PPRO, seq, [place(100, 200)]), /Could not verify V2 is empty/);
});
