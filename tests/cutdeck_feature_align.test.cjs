const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createAlignFeature,
  describeField,
  readAlignTransform,
} = require("../uxp/cutdeck/features/align.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

test("align: describeField handles missing, animated, points, and scalars", () => {
  assert.deepEqual(describeField(null, false, null), { known: false });
  assert.deepEqual(describeField({ isTimeVarying: true }, true, { width: 1920, height: 1080 }), {
    known: true,
    animated: true,
  });

  // Scalar value (rotation / scale)
  assert.deepEqual(describeField({ isTimeVarying: false, value: 45 }, false, null), {
    known: true,
    animated: false,
    value: 45,
  });

  // Point with normalized value [0.5, 0.5] against 1920x1080
  const point = describeField({ isTimeVarying: false, value: [0.5, 0.5] }, true, {
    width: 1920,
    height: 1080,
  });
  assert.equal(point.known, true);
  assert.equal(point.animated, false);
  assert.equal(point.x, 960);
  assert.equal(point.y, 540);

  // Point without frameSize cannot be converted to pixels
  assert.deepEqual(describeField({ isTimeVarying: false, value: [0.5, 0.5] }, true, null), {
    known: false,
  });
});

test("align: readAlignTransform returns unavailable when sequence or selection is missing", async () => {
  const noSeq = await readAlignTransform(null);
  assert.equal(noSeq.available, false);
  assert.equal(noSeq.reason, "No sequence open.");

  const fakeSeq = {
    getSelection: () => [],
    videoTracks: [],
  };
  const emptySel = await readAlignTransform(fakeSeq);
  assert.equal(emptySel.available, false);
  assert.equal(emptySel.reason, "Select a clip on the timeline.");
});

test("align: onRefresh runs through controller and updates alignState", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { sequence: null, transform: null },
  });

  const align = createAlignFeature({ ppro: {}, ctl });
  await align.onRefresh();

  assert.equal(ctl.state.busy, false);
  assert.equal(ctl.state.status.level, "ready");
});

test("align: poll skips reading if isMainBusy returns true", async () => {
  let readCount = 0;
  const ctl = createController({
    render: () => {},
    initialState: { sequence: null, transform: null },
  });
  const fakePpro = {
    Project: {
      getActiveProject: () => {
        readCount++;
        return { getActiveSequence: () => null };
      },
    },
  };
  let busy = true;
  const align = createAlignFeature({
    ppro: fakePpro,
    ctl,
    isMainBusy: () => busy,
  });

  await align.poll();
  assert.equal(readCount, 0, "should not poll while main controller is busy");

  busy = false;
  await align.poll();
  assert.equal(readCount, 1, "should poll once main controller is idle");
});

