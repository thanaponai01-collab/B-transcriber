const test = require('node:test');
const assert = require('node:assert/strict');
const { createAdjustFeature } = require('../uxp/cutdeck/features/adjust.js');
const { createController } = require('../uxp/cutdeck/features/controller.js');

for (const name of ['Transform Zoom', 'Invert']) {
  test(`Alt preset ${name} applies to selected Adjustment Layers and excludes linked audio`, async () => {
    const layer = { getName: async () => 'Grade', isAdjustmentLayer: async () => true };
    const audio = { mediaType: 'Audio' };
    const seq = {
      getSelection: async () => ({ getTrackItems: async () => [layer, audio] }),
      getVideoTrackCount: async () => 1,
      getVideoTrack: async () => ({ getTrackItems: async () => [layer] }),
    };
    const project = { getActiveSequence: async () => seq };
    const preset = { id: 'preset', name };
    const ctl = createController({ render: () => {}, initialState: { customPresets: [preset] } });
    let applied;
    const feature = createAdjustFeature({
      ctl, ppro: { Project: { getActiveProject: async () => project } },
      timeline: { placeAdjustmentLayersOnTimeline: async () => assert.fail('must not place a layer') },
      effects: { applyCapturedPresetToAll: async (_p, proj, items, captured) => {
        assert.equal(proj, project);
        assert.equal(captured, preset);
        applied = items;
        return { warnings: [] };
      } },
    });
    await feature.onApplyPreset('preset', 'selected');
    assert.deepEqual(applied, [layer], 'selected Adjustment Layer must receive the preset');
    assert.equal(ctl.state.status.level, 'ready');
  });
}
