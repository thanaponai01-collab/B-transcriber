## Rough Cut recovery
- path: uxp/cutdeck/timeline/, uxp/cutdeck/features/roughCut.js
- oracle: docs/rough-cut.md, tests/fixtures/cutdeck_native_plan_golden.json
- test: `node --test tests/cutdeck_native_cut.test.cjs tests/cutdeck_cut_plan_apply.test.cjs tests/cutdeck_feature_rough_cut.test.cjs`
- fail-signal: # fail 4
- fail-proof: reinstate the first-action exclusion in stale-handle recovery; both split and move recovery and bounded-failure tests reject it.

## Blind spots
- Tests execute the native edit entry point against a fake Premiere; real host commit/handle behavior and GPU analysis are unproven by this recipe.
