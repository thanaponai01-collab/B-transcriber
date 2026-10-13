## Native source identity
- path: uxp/cutdeck/workflow.js, uxp/cutdeck/timeline/, uxp/cutdeck/features/roughCut.js
- oracle: verification/rough-cut-retirement.md, tests/fixtures/cutdeck_native_plan_golden.json
- test: `node --test --test-reporter=spec tests/cutdeck_native_cut.test.cjs tests/cutdeck_feature_rough_cut.test.cjs tests/cutdeck_cut_plan_apply.test.cjs tests/cutdeck_workflow.test.cjs`
- fail-signal: Missing expected rejection
- fail-proof: bypass the shared source-snapshot guard; changed source audio must refuse before a transaction or copy, while fresh/enumeration-reordered audio produces the frozen golden.

## JSON analysis and XML retirement
- path: cutdeck/, transcribe/, clubfriday/
- oracle: verification/rough-cut-retirement.md, tests/sequence_fixture.py, tests/fixtures/cutdeck_native_plan_golden.json, tests/fixtures/cutdeck_recut_sample_scrubbed.xml
- test: `python -m pytest tests/test_cutdeck_rough_cut_retirement.py tests/test_cutdeck_rough_cut_cli.py tests/test_cutdeck_sequence_json.py tests/test_cutdeck_native_plan_golden.py -q -p no:cacheprovider`
- fail-signal: FAILED tests/test_cutdeck_rough_cut_cli.py::test_
- fail-proof: remove clipping of cut spans to In/Out, or omit the source snapshot in CLI output; the range/report and captured-input checks must reject the changed behavior.

## Blind spots
- Scoped offline evidence only: native Premiere transactions run against the fake host.
- GPU ASR is stubbed; real ffmpeg extraction and subprocess JSON analysis execute locally.
- Broader helper/ClubFriday/panel regressions run through scripts/check_rough_cut.py in the workspace.
