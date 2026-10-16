## Preset Adjustment Layer selection
- path: uxp/cutdeck/features/adjust.js, uxp/cutdeck/host/trackItems.js
- test: `"C:/Users/thana/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe" --test tests/cutdeck_preset_adjustment_selection.test.cjs tests/cutdeck_feature_adjust.test.cjs tests/cutdeck_component_access.test.cjs`
- fail-signal: selected Adjustment Layer must receive the preset
- fail-proof: original helper excludes selected Adjustment Layers; both presets reproduce the reported error.

