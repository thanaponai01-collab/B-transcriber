/* Tests for CutDeck Color Matte and Add Frame Hold features,
   as well as performance and RAM efficiency optimizations in timeline/adjustmentLayer.js and timeline/effects.js. */
const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");
const zlib = require("node:zlib");

const cmProject = require("../uxp/cutdeck/timeline/cmProject.js");

const TICKS_PER_SEC = 254016000000n;
const TPF_24FPS = 10594584000n; // 24 fps

// ============================================================================
// 1. cmProject.js (Color Matte project generator)
// ============================================================================

test("cmProject: builds valid Color Matte XML and gzip .prproj bytes", () => {
  let n = 0;
  const testUuid = () => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`;

  const { xml, name } = cmProject.buildColorMatteProject({
    width: 1920,
    height: 1080,
    ticksPerFrame: TPF_24FPS,
    uuid: testUuid,
  });

  assert.equal(name, "Color Matte 1920x1080");
  assert.match(xml, /<FrameRect>0,0,1920,1080<\/FrameRect>/);
  assert.match(xml, /<FilePath>1129270354<\/FilePath>/);
  assert.match(xml, /<ActualMediaFilePath>1129270354<\/ActualMediaFilePath>/);
  assert.match(xml, /<ImporterPrefs Encoding="base64"/);
  assert.match(xml, /<Title>Color Matte 1920x1080<\/Title>/);
  assert.match(xml, /<ClipName>Color Matte 1920x1080<\/ClipName>/);
  assert.match(xml, /<MediaFrameRate>10594584000<\/MediaFrameRate>/);

  // Crucial check: Color Matte must NOT have IsAdjustmentLayer
  assert.equal(xml.includes("<IsAdjustmentLayer>"), false, "Color Matte must not have IsAdjustmentLayer flag");

  // Verify gzip round-trip
  n = 0;
  const { bytes, name: prprojName } = cmProject.buildColorMattePrproj({
    width: 1920,
    height: 1080,
    ticksPerFrame: TPF_24FPS,
    uuid: testUuid,
  });
  assert.equal(prprojName, "Color Matte 1920x1080");
  const unzipped = zlib.gunzipSync(Buffer.from(bytes)).toString("utf8");
  assert.equal(unzipped, xml);
});

test("cmProject: generates fresh UUIDs per invocation without dangling references", () => {
  const build1 = cmProject.buildColorMatteProject({ width: 1280, height: 720 });
  const build2 = cmProject.buildColorMatteProject({ width: 1280, height: 720 });

  const uids1 = [...build1.xml.matchAll(/ObjectUID="([^"]+)"/g)].map((m) => m[1]);
  const uids2 = [...build2.xml.matchAll(/ObjectUID="([^"]+)"/g)].map((m) => m[1]);

  assert.equal(uids1.length > 0, true);
  assert.equal(uids2.length > 0, true);
  const intersection = uids1.filter((u) => uids2.includes(u));
  assert.deepEqual(intersection, [], "Each build must have unique UUIDs");

  // Check no dangling references
  const ids = new Set([...build1.xml.matchAll(/Object(?:U)?ID="([^"]+)"/g)].map((m) => m[1]));
  const refs = [...build1.xml.matchAll(/Object(?:U)?Ref="([^"]+)"/g)].map((m) => m[1]);
  const dangling = refs.filter((r) => !ids.has(r));
  assert.deepEqual(dangling, []);
});

test("cmProject: rejects invalid dimensions", () => {
  assert.throws(() => cmProject.buildColorMatteProject({ width: 0, height: 1080 }), /sides must be whole numbers/);
  assert.throws(() => cmProject.buildColorMatteProject({ width: 1920, height: -100 }), /sides must be whole numbers/);
  assert.throws(() => cmProject.buildColorMatteProject({ width: 1920.5, height: 1080 }), /sides must be whole numbers/);
});

// ============================================================================
// 2. alLibrary.js (Color Matte discovery, auto-creation, wrapper flattening)
// ============================================================================

const writtenFiles = [];
const stubs = {
  uxp: {
    storage: {
      formats: { binary: "binary" },
      localFileSystem: {
        getTemporaryFolder: async () => ({
          nativePath: "C:\\tmp\\",
          createFile: async (name) => ({
            nativePath: `C:\\tmp\\${name}`,
            write: async (buf, opts) => {
              writtenFiles.push({ name, bytes: new Uint8Array(buf), opts });
            },
          }),
        }),
      },
    },
  },
};

const realLoad = Module._load;
Module._load = function (request, ...rest) {
  if (Object.prototype.hasOwnProperty.call(stubs, request)) return stubs[request];
  return realLoad.call(this, request, ...rest);
};
test.after(() => { Module._load = realLoad; });

const alLibrary = require("../uxp/cutdeck/timeline/alLibrary.js");

function mockBin(name, items = []) {
  const b = {
    name,
    type: 2,
    items: [...items],
    getItems: async () => b.items.slice(),
    createBinAction: () => () => true,
    createMoveItemAction: (item, dest) => () => {
      b.items = b.items.filter((i) => i !== item);
      dest.items.push(item);
      return true;
    },
    createRemoveItemAction: (item) => () => {
      b.items = b.items.filter((i) => i !== item);
      return true;
    },
  };
  return b;
}

function mockProjectWithBins(rootChildren = []) {
  const root = mockBin("Root", rootChildren);
  const transactions = [];
  return {
    root,
    transactions,
    getRootItem: async () => root,
    executeTransaction: (build, label) => {
      transactions.push(label);
      let ok = true;
      try {
        build({ addAction: (action) => (typeof action === "function" ? action() : true) });
      } catch (_) {
        ok = false;
      }
      return ok;
    },
    importFiles: async (paths, suppressUI, targetBin) => {
      const fileName = paths[0].split(/[\\/]/).pop();
      // Emulate Premiere creating a wrapper bin
      const itemName = fileName.replace(/^CutDeck /, "").replace(/\.prproj$/, "");
      const child = { name: itemName, type: 1 };
      const wrapper = mockBin(fileName, [child]);
      targetBin.items.push(wrapper);
      return true;
    },
  };
}

test("alLibrary: createColorMatteForSequence imports, flattens wrapper, and returns item", async () => {
  writtenFiles.length = 0;
  const adjBin = mockBin("ADJ & FX", []);
  const cutdeckBin = mockBin("CutDeck", [adjBin]);
  const project = mockProjectWithBins([cutdeckBin]);

  const matte = await alLibrary.createColorMatteForSequence(project, 1920, 1080, TPF_24FPS);

  assert.equal(matte.name, "Color Matte 1920x1080");
  assert.equal(writtenFiles.length, 1);
  assert.equal(writtenFiles[0].name, "CutDeck Color Matte 1920x1080.prproj");

  // Verify the wrapper folder was flattened out of ADJ & FX
  assert.deepEqual(adjBin.items.map((i) => i.name), ["Color Matte 1920x1080"]);
});

test("alLibrary: findColorMatteItem finds existing color matte in CutDeck bin or project root", async () => {
  const matteItem = { name: "Color Matte 1920x1080", type: 1 };
  const adjBin = mockBin("ADJ & FX", [matteItem]);
  const cutdeckBin = mockBin("CutDeck", [adjBin]);
  const project = mockProjectWithBins([cutdeckBin]);

  const seq = {
    getSettings: async () => ({
      getVideoFrameRect: async () => ({ width: 1920, height: 1080 }),
    }),
  };

  const found = await alLibrary.findColorMatteItem(project, seq, {});
  assert.equal(found, matteItem);
});

// ============================================================================
// 3. frameHold.js (Non-destructive Freeze Frame)
// ============================================================================

const frameHold = require("../uxp/cutdeck/timeline/frameHold.js");

test("frameHold: findClipAtPlayhead identifies topmost video clip spanning playhead", async () => {
  // Mock sequence with V1 and V2:
  // V1 has clip [0s, 5s]
  // V2 has clip [1s, 3s]
  // Playhead at 2s -> should find V2 clip (highest track)
  // Playhead at 4s -> should find V1 clip
  const clipV1 = {
    startTime: { ticks: String(0n * TICKS_PER_SEC) },
    endTime: { ticks: String(5n * TICKS_PER_SEC) },
  };
  const clipV2 = {
    startTime: { ticks: String(1n * TICKS_PER_SEC) },
    endTime: { ticks: String(3n * TICKS_PER_SEC) },
  };

  const seq = {
    getVideoTrackCount: async () => 2,
    getVideoTrack: async (idx) => ({
      getTrackItems: async () => (idx === 0 ? [clipV1] : [clipV2]),
    }),
  };

  const ppro = {
    Constants: {
      TrackItemType: { CLIP: "TrackItemType.CLIP" },
      MediaType: { VIDEO: "MediaType.VIDEO" },
    },
  };

  // At 2s (spanned by both V1 and V2): V2 wins
  const found2s = await frameHold.findClipAtPlayhead(ppro, seq, 2n * TICKS_PER_SEC);
  assert.equal(found2s.item, clipV2);
  assert.equal(found2s.track, 1); // V2 (0-indexed: 1)
  assert.equal(found2s.startTicks, 1n * TICKS_PER_SEC);
  assert.equal(found2s.endTicks, 3n * TICKS_PER_SEC);

  // At 4s (spanned only by V1): V1 wins
  const found4s = await frameHold.findClipAtPlayhead(ppro, seq, 4n * TICKS_PER_SEC);
  assert.equal(found4s.item, clipV1);
  assert.equal(found4s.track, 0); // V1 (0-indexed: 0)
  assert.equal(found4s.startTicks, 0n * TICKS_PER_SEC);
  assert.equal(found4s.endTicks, 5n * TICKS_PER_SEC);

  // At 6s (past clips): returns null
  const found6s = await frameHold.findClipAtPlayhead(ppro, seq, 6n * TICKS_PER_SEC);
  assert.equal(found6s, null);
});

test("frameHold: addFrameHold executes non-destructive freeze frame on track above", async () => {
  // Scenario: 1 clip of 5 seconds on V1 (track 0). Playhead is at 2 seconds.
  // Expectation:
  // - Original clip remains untouched for all 5 seconds.
  // - Hold frame is placed on V2 (track 1) from 2s to 5s (duration 3s).
  const clipV1 = {
    startTime: { ticks: String(0n * TICKS_PER_SEC) },
    endTime: { ticks: String(5n * TICKS_PER_SEC) },
    getName: async () => "Interview_A01.mp4",
  };

  const exportedFrames = [];
  const placedActions = [];
  let setInOutCalled = null;

  const mockSeq = {
    getTimebase: async () => String(TPF_24FPS),
    getPlayerPosition: async () => ({ ticks: String(2n * TICKS_PER_SEC) }),
    getVideoTrackCount: async () => 2,
    getVideoTrack: async (idx) => ({
      getTrackItems: async () => (idx === 0 ? [clipV1] : []),
    }),
    getSettings: async () => ({
      getVideoFrameRect: async () => ({ width: 1920, height: 1080 }),
    }),
  };

  const project = {
    getActiveSequence: async () => mockSeq,
    executeTransaction: (build, label) => {
      build({
        addAction: (act) => {
          placedActions.push({ label, act });
          return true;
        },
      });
      return true;
    },
    importFiles: async (paths, suppressUI, targetBin) => {
      const fileName = paths[0].split(/[\\/]/).pop();
      const stillItem = {
        name: fileName,
        type: 1,
        createSetInOutPointsAction: (inPoint, outPoint) => {
          setInOutCalled = { inPoint, outPoint };
          return { type: "setInOut" };
        },
      };
      targetBin.items.push(stillItem);
      return true;
    },
  };

  const holdBin = mockBin("Frame Holds", []);
  const cutdeckBin = mockBin("CutDeck", [holdBin]);
  const rootBin = mockBin("Root", [cutdeckBin]);
  project.getRootItem = async () => rootBin;

  const fakePpro = {
    Project: { getActiveProject: async () => project },
    Sequence: { getActiveSequence: async () => mockSeq },
    TickTime: {
      createWithTicks: (ticks) => ({ ticks: String(ticks) }),
    },
    Exporter: {
      exportSequenceFrame: async (seq, time, fileName, folderPath, width, height) => {
        exportedFrames.push({ time, fileName, folderPath, width, height });
        return true;
      },
    },
    SequenceEditor: {
      getEditor: async () => ({
        createOverwriteItemAction: (item, time, trackIndex) => ({
          type: "overwrite",
          item,
          time,
          trackIndex,
        }),
      }),
    },
    Constants: {
      TrackItemType: { CLIP: "TrackItemType.CLIP" },
      MediaType: { VIDEO: "MediaType.VIDEO" },
    },
  };

  const res = await frameHold.addFrameHold(fakePpro);

  assert.equal(res.success, true);
  assert.equal(res.clipName, "Interview_A01.mp4");
  assert.equal(res.sourceTrack, 1); // V1 (1-based for display)
  assert.equal(res.targetTrack, 2); // V2 (1-based for display: 1 layer up)
  assert.equal(res.holdDurationTicks, 3n * TICKS_PER_SEC); // 5s - 2s = 3s
  assert.equal(res.holdSecs, "3.0");

  // Verify export happened at 2 seconds
  assert.equal(exportedFrames.length, 1);
  assert.equal(exportedFrames[0].time.ticks, String(2n * TICKS_PER_SEC));
  assert.equal(exportedFrames[0].width, 1920);
  assert.equal(exportedFrames[0].height, 1080);

  // Verify In/Out was set to 0 -> 3 seconds
  assert.ok(setInOutCalled);
  assert.equal(setInOutCalled.inPoint.ticks, "0");
  assert.equal(setInOutCalled.outPoint.ticks, String(3n * TICKS_PER_SEC));

  // Verify overwrite landed on track 1 (V2) at 2s
  const overwriteAction = placedActions.find((a) => a.label === "CutDeck: Place Frame Hold");
  assert.ok(overwriteAction);
  assert.equal(overwriteAction.act.trackIndex, 1); // V2 (0-indexed)
  assert.equal(overwriteAction.act.time.ticks, String(2n * TICKS_PER_SEC));
});

test("frameHold: handles Premiere importing file into rootItem instead of targetBin and auto-moves to Frame Holds", async () => {
  const exportedFrames = [];
  const placedActions = [];

  const mockClip = {
    startTime: { ticks: "0" },
    endTime: { ticks: String(5n * TICKS_PER_SEC) },
    getStartTime: async () => ({ ticks: "0" }),
    getEndTime: async () => ({ ticks: String(5n * TICKS_PER_SEC) }),
    getName: async () => "Clip_RootFallback.mp4",
    name: "Clip_RootFallback.mp4",
    getIsSelected: async () => false,
  };

  const mockTrack1 = {
    getTrackItems: async () => [mockClip],
    trackIndex: 0,
  };
  const mockTrack2 = {
    getTrackItems: async () => [],
    trackIndex: 1,
  };

  const mockSeq = {
    getTimebase: async () => "10594584000",
    getPlayerPosition: async () => ({ ticks: String(2n * TICKS_PER_SEC) }),
    getVideoTrackCount: async () => 2,
    getVideoTrack: async (idx) => (idx === 0 ? mockTrack1 : mockTrack2),
    getSettings: async () => ({
      getVideoFrameRect: async () => ({ width: 1920, height: 1080 }),
    }),
  };

  const holdBin = mockBin("Frame Holds", []);
  const cutdeckBin = mockBin("CutDeck", [holdBin]);
  const rootBin = mockBin("Root", [cutdeckBin]);

  const project = {
    getActiveSequence: async () => mockSeq,
    getRootItem: async () => rootBin,
    executeTransaction: (build, label) => {
      build({
        addAction: (act) => {
          placedActions.push({ label, act });
          return typeof act === "function" ? act() : true;
        },
      });
      return true;
    },
    // Emulate Premiere bug: ignores targetBin and dumps file into rootItem
    importFiles: async (paths, suppressUI, targetBin) => {
      const fileName = paths[0].split(/[\\/]/).pop();
      const stillItem = {
        name: fileName,
        type: 1,
        createSetInOutPointsAction: (inPoint, outPoint) => ({ type: "setInOut", inPoint, outPoint }),
      };
      rootBin.items.push(stillItem);
      return true;
    },
  };

  const fakePpro = {
    Project: { getActiveProject: async () => project },
    Sequence: { getActiveSequence: async () => mockSeq },
    TickTime: {
      createWithTicks: (ticks) => ({ ticks: String(ticks) }),
    },
    Exporter: {
      exportSequenceFrame: async (seq, time, fileName, folderPath, width, height) => {
        exportedFrames.push({ time, fileName, folderPath, width, height });
        return true;
      },
    },
    SequenceEditor: {
      getEditor: async () => ({
        createOverwriteItemAction: (item, time, trackIndex) => ({
          type: "overwrite",
          item,
          time,
          trackIndex,
        }),
      }),
    },
    Constants: {
      TrackItemType: { CLIP: "TrackItemType.CLIP" },
      MediaType: { VIDEO: "MediaType.VIDEO" },
    },
  };

  const res = await frameHold.addFrameHold(fakePpro);

  assert.equal(res.success, true);
  assert.equal(res.sourceTrack, 1);
  assert.equal(res.targetTrack, 2);

  // Check that the item was found and moved from root into holdBin
  const movedAction = placedActions.find((a) => a.label === "CutDeck: move Frame Hold into bin");
  assert.ok(movedAction, "Should trigger transaction to move item into Frame Holds bin");
  assert.equal(holdBin.items.length, 1, "Hold item should now be in Frame Holds bin");
  assert.equal(rootBin.items.find((i) => i.name.startsWith("CutDeck_Hold_")), undefined, "Item should no longer be in root");
});

// ============================================================================
// 4. adjustmentLayer.js (RAM and O(N) Efficiency Optimization)
// ============================================================================

const adjustmentLayer = require("../uxp/cutdeck/timeline/adjustmentLayer.js");

test("adjustmentLayer: placeMediaOnTimeline uses track item caching for high-speed O(N) verification", async () => {
  // Simulate 50 clips to verify performance and trackCache operation
  const N = 50;
  let trackClipCalls = 0;

  const mockClips = [];
  for (let i = 0; i < N; i++) {
    const s = BigInt(i * 10) * TICKS_PER_SEC;
    const e = s + 5n * TICKS_PER_SEC;
    mockClips.push({
      startTime: { ticks: String(s) },
      endTime: { ticks: String(e) },
      getStartTime: async () => ({ ticks: String(s) }),
      getEndTime: async () => ({ ticks: String(e) }),
      getTrackIndex: async () => 0,
      getIsSelected: async () => true,
      getMediaType: async () => "MediaType.VIDEO",
      isAdjustmentLayer: async () => false,
      getName: async () => `Clip_${i}`,
    });
  }

  let currentDurTicks = 5n * TICKS_PER_SEC;
  const placedALs = [];
  const mockTrack = {
    getTrackItems: async () => {
      trackClipCalls++;
      // Return placed ALs during verification
      return [...placedALs];
    },
  };

  const mockSeq = {
    getVideoTrackCount: async () => 2,
    getVideoTrack: async () => mockTrack,
    getTimebase: async () => String(TPF_24FPS),
    getSettings: async () => ({
      getVideoFrameRect: async () => ({ width: 1920, height: 1080 }),
    }),
    getPlayerPosition: async () => ({ ticks: "0" }),
    getInPoint: async () => ({ ticks: "-1" }),
    getOutPoint: async () => ({ ticks: "-1" }),
    getSelection: async () => ({
      getTrackItems: async () => mockClips,
    }),
  };

  const fakeALItem = {
    name: "Adjustment Layer 1920x1080",
    type: 1,
    createSetInOutPointsAction: (inP, outP) => {
      currentDurTicks = BigInt(outP.ticks) - BigInt(inP.ticks);
      return { type: "inout" };
    },
    createSetColorLabelAction: () => ({ type: "color" }),
  };

  const adjBin = mockBin("ADJ & FX", [fakeALItem]);
  const cutdeckBin = mockBin("CutDeck", [adjBin]);
  const rootBin = mockBin("Root", [cutdeckBin]);

  const mockProject = {
    getRootItem: async () => rootBin,
    getActiveSequence: async () => mockSeq,
    executeTransaction: (build) => {
      build({
        addAction: (act) => {
          if (act && act.type === "overwrite") {
            // Emulate placed item appearing on timeline
            placedALs.push({
              sTicks: BigInt(act.time.ticks),
              eTicks: BigInt(act.time.ticks) + currentDurTicks,
              startTime: act.time,
              endTime: { ticks: String(BigInt(act.time.ticks) + currentDurTicks) },
              getStartTime: async () => act.time,
              getEndTime: async () => ({ ticks: String(BigInt(act.time.ticks) + currentDurTicks) }),
              isAdjustmentLayer: async () => true,
            });
          }
          return true;
        },
      });
      return true;
    },
  };

  const fakePpro = {
    Project: { getActiveProject: async () => mockProject },
    Sequence: { getActiveSequence: async () => mockSeq },
    TickTime: {
      createWithTicks: (ticks) => ({ ticks: String(ticks) }),
    },
    SequenceEditor: {
      getEditor: async () => ({
        createOverwriteItemAction: (item, time, track) => ({
          type: "overwrite",
          item,
          time,
          track,
        }),
      }),
    },
    TrackItemSelection: {
      createEmptySelection: (cb) => cb({ addItem: () => true }),
    },
    Constants: {
      TrackItemType: { CLIP: "TrackItemType.CLIP" },
      MediaType: { VIDEO: "MediaType.VIDEO" },
    },
  };

  const t0 = Date.now();
  const res = await adjustmentLayer.placeMediaOnTimeline(fakePpro, {
    kind: "adj",
    mode: "per_clip",
    frames: 16,
  });
  const elapsed = Date.now() - t0;

  assert.equal(res.placedCount, N);
  // Total track queries across all 50 items is a small constant (setup + lanes + 1 cache query for target track)
  // Without trackCache, verification alone would make N queries (50 calls).
  assert.ok(trackClipCalls < 10, `Expected < 10 track queries via trackCache, got ${trackClipCalls}`);
  assert.ok(elapsed < 2000, `Execution took ${elapsed} ms, should be under 2000 ms`);
});

test("adjustmentLayer: 200 items placement benchmark runs in milliseconds with minimal calls", async () => {
  const N = 200;
  let trackClipCalls = 0;

  const mockClips = [];
  for (let i = 0; i < N; i++) {
    const s = BigInt(i * 10) * TICKS_PER_SEC;
    const e = s + 5n * TICKS_PER_SEC;
    mockClips.push({
      startTime: { ticks: String(s) },
      endTime: { ticks: String(e) },
      getStartTime: async () => ({ ticks: String(s) }),
      getEndTime: async () => ({ ticks: String(e) }),
      getTrackIndex: async () => 0,
      getIsSelected: async () => true,
      getMediaType: async () => "MediaType.VIDEO",
      isAdjustmentLayer: async () => false,
      getName: async () => `Clip_${i}`,
    });
  }

  let currentDurTicks = 5n * TICKS_PER_SEC;
  const placedALs = [];
  const mockTrack = {
    getTrackItems: async () => {
      trackClipCalls++;
      return [...placedALs];
    },
  };

  const mockSeq = {
    getVideoTrackCount: async () => 2,
    getVideoTrack: async () => mockTrack,
    getTimebase: async () => String(TPF_24FPS),
    getSettings: async () => ({
      getVideoFrameRect: async () => ({ width: 1920, height: 1080 }),
    }),
    getPlayerPosition: async () => ({ ticks: "0" }),
    getInPoint: async () => ({ ticks: "-1" }),
    getOutPoint: async () => ({ ticks: "-1" }),
    getSelection: async () => ({
      getTrackItems: async () => mockClips,
    }),
  };

  const fakeALItem = {
    name: "Adjustment Layer 1920x1080",
    type: 1,
    createSetInOutPointsAction: (inP, outP) => {
      currentDurTicks = BigInt(outP.ticks) - BigInt(inP.ticks);
      return { type: "inout" };
    },
    createSetColorLabelAction: () => ({ type: "color" }),
  };

  const adjBin = mockBin("ADJ & FX", [fakeALItem]);
  const cutdeckBin = mockBin("CutDeck", [adjBin]);
  const rootBin = mockBin("Root", [cutdeckBin]);

  const mockProject = {
    getRootItem: async () => rootBin,
    getActiveSequence: async () => mockSeq,
    executeTransaction: (build) => {
      build({
        addAction: (act) => {
          if (act && act.type === "overwrite") {
            placedALs.push({
              sTicks: BigInt(act.time.ticks),
              eTicks: BigInt(act.time.ticks) + currentDurTicks,
              startTime: act.time,
              endTime: { ticks: String(BigInt(act.time.ticks) + currentDurTicks) },
              getStartTime: async () => act.time,
              getEndTime: async () => ({ ticks: String(BigInt(act.time.ticks) + currentDurTicks) }),
              isAdjustmentLayer: async () => true,
            });
          }
          return true;
        },
      });
      return true;
    },
  };

  const fakePpro = {
    Project: { getActiveProject: async () => mockProject },
    Sequence: { getActiveSequence: async () => mockSeq },
    TickTime: {
      createWithTicks: (ticks) => ({ ticks: String(ticks) }),
    },
    SequenceEditor: {
      getEditor: async () => ({
        createOverwriteItemAction: (item, time, track) => ({
          type: "overwrite",
          item,
          time,
          track,
        }),
      }),
    },
    TrackItemSelection: {
      createEmptySelection: (cb) => cb({ addItem: () => true }),
    },
    Constants: {
      TrackItemType: { CLIP: "TrackItemType.CLIP" },
      MediaType: { VIDEO: "MediaType.VIDEO" },
    },
  };

  const t0 = Date.now();
  const res = await adjustmentLayer.placeMediaOnTimeline(fakePpro, {
    kind: "adj",
    mode: "per_clip",
    frames: 16,
  });
  const elapsed = Date.now() - t0;

  assert.equal(res.placedCount, 200);
  assert.ok(trackClipCalls < 10, `Expected < 10 track queries for 200 items, got ${trackClipCalls}`);
  // 200 items should complete in well under 100ms
  assert.ok(elapsed < 500, `200 items took ${elapsed} ms, expected under 500 ms`);
});

// ============================================================================
// 5. features/adjust.js (Color Matte & Frame Hold UI handlers)
// ============================================================================

const { createAdjustFeature } = require("../uxp/cutdeck/features/adjust.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

test("adjust feature: onColorMatte triggers placeColorMattesOnTimeline and updates status", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { settings: { frames: 16, clamp: true, color: "Cerulean" } },
  });

  let calledWith = null;
  const fakeTimeline = {
    placeColorMattesOnTimeline: async (ppro, opts) => {
      calledWith = opts;
      return {
        placedCount: 3,
        targetTrack: 2,
        sequenceWidth: 1920,
        sequenceHeight: 1080,
      };
    },
  };

  const adjust = createAdjustFeature({
    ppro: {},
    ctl,
    timeline: fakeTimeline,
  });

  await adjust.onColorMatte("per_clip");

  assert.equal(calledWith.mode, "per_clip");
  assert.equal(calledWith.frames, 16);
  assert.equal(calledWith.color, "Cerulean");
  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /Added 3 separate Color Mattes \(1 per clip\) on V2/);
});

test("adjust feature: onAddFrameHold triggers addFrameHold and updates status", async () => {
  const ctl = createController({
    render: () => {},
    initialState: {},
  });

  const fakeFrameHold = {
    addFrameHold: async () => ({
      success: true,
      sourceTrack: 1,
      targetTrack: 2,
      holdSecs: "3.5",
    }),
  };

  const adjust = createAdjustFeature({
    ppro: {},
    ctl,
    frameHold: fakeFrameHold,
  });

  await adjust.onAddFrameHold();

  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /Placed Frame Hold on V2 \(3\.5s hold, original clip untouched\)!/);
});
