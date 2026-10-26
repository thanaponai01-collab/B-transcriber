# CutDeck work history

Completed Rough Cut milestones and performance investigations.

## Rough Cut reliability - 2026-10-11
Owner priority superseded earlier transcription CLI foundation next step.
- Proof: `node --test tests/cutdeck_native_cut.test.cjs tests/cutdeck_cut_plan_apply.test.cjs tests/cutdeck_feature_rough_cut.test.cjs` passed exact golden output, fresh-handle recovery, bounded failure and unchanged-source assertions.
- First-action stale failure reproduced: 14 passed / 4 failed before the fix.
- Bounded recovery implemented in split/move transaction loops; 37 targeted checks and 635 panel checks passed.
- Source map: ../docs/rough-cut.md. Evidence: output/rough-cut-reliability/; .verify-evidence/rough-cut-reliability finished strict green. Details and limits: [rough-cut-reliability](../verification/rough-cut-reliability.md).

## Rough Cut XML retirement - 2026-10-11
Owner approved retirement of XML-file entry points, separating shared services and strengthening native architecture. Complete in `afa8dc76dd42446cf541698b9894f8be35c089db`.
- Shared helper: cutdeck/helper.py; JSON analysis: cutdeck/rough_cut.py; audio extraction: cutdeck/audio_extract.py; exact timing: cutdeck/sequence_timing.py.
- FCP7 parsing/writing and the XML-file MCP tool are retired. Old commands explain the replacement; JSON job storage preserved.
- Source audio snapshot compared before cloning; stale results clear the panel job.
- Current architecture: ../docs/rough-cut.md and ../uxp/cutdeck/README.md.
- Proof and results: [retirement evidence](../verification/rough-cut-retirement-evidence.md).

## Aggressive Rough Cut Sound Guard & Tight Trim - 2026-10-12
Owner requested aggressive silence trimming without cutting any audible sound:
- Loudness energy guard (transcribe/pipeline/ingest.py: `sound_runs`): detects audible runs above noise floor and protects them against silence cutting and min-clip drops.
- Aggressive preset tuning in `transcribe/config.aggressive_cut.yaml` (`pad_pre_ms: 40`, `pad_post_ms: 60`, `min_silence_ms: 119`, `vad_min_silence_ms: 120`, `sound_guard_db: 10`, `sound_guard_tail_db: 5`).
- Verification: `python -m pytest tests/test_cutdeck_sound_guard.py -v` (9 passed); full suite `python -m pytest tests/ -k "not live"` (1033 passed); `node --test tests/*.cjs` (644 passed).

## Rough Cut lag: poll fix and ripple probe - 2026-10-12
- Transform poll idle rate fixed (40 → ≤7 reads per 6 s idle). Diagnostics probe *Test Ripple Delete* (uxp/cutdeck/rippleProbe.js). Details ../docs/rough-cut.md.
- Live 2026-10-12 ("2026-10-10 15-29-44_Synced"): 361 cuts, 659.9 s removed in 10 s, read-back clean, 8 undo steps.

## One panel, four tabs - 2026-10-26
Owner-approved design (plan: ../docs/research/cutdeck-one-panel-plan.md). Built, not yet run in Premiere.
- The ClubFriday panel and the separate CutDeck Transform panel are gone; `manifest.json` declares only `cutdeck.panel`. The `clubfriday/` server and quote editor are unchanged.
- Tabs Cut, FX, Transform, Align; no name row; sequence card and resume banner on Cut only; last tab remembered (`cutdeck.tab`). Transform reads run only on the Transform and Align tabs.
- Transform as Effect Controls fx blocks (Motion incl. Crop, Opacity) with fold and block reset; Align as a frame drawing sized to the sequence (9:16 capped at 200 px tall). Probes folded under one menu item; the Settings shortcuts guide removed.
- Proof: `node --test tests/*.cjs` 726/726; new tests/cutdeck_one_panel.test.cjs with six fail-proofs (VERIFY.md). Next: plan step 8 live check.
