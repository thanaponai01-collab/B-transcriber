# Current work

Foundation refresh, 2026-10-11: existing ClubFriday progress is retained in
[ClubFriday work history](work/clubfriday-history.md); read it for live-run details,
unfinished caption/graphics integration and evidence paths.

Foundation scope: repository overview, with the ClubFriday backend as the selected
requirement-backed path. Subsequent owner-authorized Rough Cut work is recorded below.
13 backend tests and 3 panel tests passed. Offset mutation caused 3 failures; the
isolated backend recipe finished strict green (verification/foundation.md).
Historical Python 3.11.9 runtime remains
required for the GPU setup. See [commands](docs/commands.md) and [verification](VERIFY.md).

## Blockers and limits
- Repository-wide current strict green is not established by the selected checks.
- Real Premiere, browser interactions, range extraction and GPU ASR were not run.
- Historical deferred styled graphic insertion remains blocked by the text-write API
  evidence in the linked work record; Rough Cut live confirmation is the current priority.

## Rough Cut reliability - 2026-10-11
Owner priority supersedes the earlier transcription CLI foundation next step.
- Proof: `node --test tests/cutdeck_native_cut.test.cjs tests/cutdeck_cut_plan_apply.test.cjs tests/cutdeck_feature_rough_cut.test.cjs` must pass exact golden output, fresh-handle recovery, bounded failure and unchanged-source assertions.
- First-action stale failure reproduced: 14 passed / 4 failed before the fix.
- Bounded recovery implemented in existing split/move transaction loops; 37 targeted
  checks and all 635 panel checks passed. Committed with this recovery record;
  source map: docs/rough-cut.md.
- Evidence: output/rough-cut-reliability/; scoped mutation challenge caught all four
  original failure cases; .verify-evidence/rough-cut-reliability finished strict green.
  Details and limits: verification/rough-cut-reliability.md.

## Rough Cut XML retirement - 2026-10-11
Owner approved the review's three steps: separate shared services, retire XML-file
entry points, and strengthen the existing native architecture. RUN.json owns execution.
- Complete and pushed to origin/master: `afa8dc76dd42446cf541698b9894f8be35c089db`.
- Shared helper: cutdeck/helper.py; JSON analysis: cutdeck/rough_cut.py; audio extraction:
  cutdeck/audio_extract.py; exact timing: cutdeck/sequence_timing.py.
- FCP7 parsing/writing and the XML-file MCP tool are retired. Old commands explain the
  replacement; old prepared/ready XML jobs fail clearly. JSON job storage is preserved.
- Newly analysed cuts retain their source audio snapshot. Both panel and agent apply paths
  compare it before cloning; stale results clear the panel job so the next cut can analyse.
- Current architecture and instructions: docs/rough-cut.md and uxp/cutdeck/README.md.
- Local checks completed before commit; command, results and strict proof:
  [retirement evidence](verification/rough-cut-retirement-evidence.md).

## Aggressive Rough Cut Sound Guard & Tight Trim - 2026-10-12
Owner requested aggressive silence trimming without cutting any audible sound (speech, held vowels, music, laughter, SFX, breaths):
- Loudness energy guard (transcribe/pipeline/ingest.py: `sound_runs`): detects audible runs above noise floor and protects them against silence cutting and min-clip drops.
- Aggressive preset tuning (transcribe/config.aggressive_cut.yaml):
  - Pre-roll: 40 ms before each sound (`pad_pre_ms: 40`).
  - Post-roll: 60 ms after each sound (`pad_post_ms: 60`).
  - Silence threshold: cuts any silence >= 120 ms (`min_silence_ms: 119`, `vad_min_silence_ms: 120`, `rms_gate_min_gap_ms: 120`).
  - Sensitive energy floor for breaths/SFX: `sound_guard_db: 10`, `sound_guard_tail_db: 5`, `sound_guard_min_ms: 40`, `min_clip_ms: 60`.
  - Default preset remains `aggressive` in the panel, helper and MCP tools.
- Verification: `python -m pytest tests/test_cutdeck_sound_guard.py -v` (9 passed); full suite `python -m pytest tests/ -k "not live"` (1033 passed); `node --test tests/*.cjs` (644 passed).

## Next
Run the repaired Rough Cut on the previously failing sequence in live Premiere;
verify playable audio, exact read-back, retained original and changed-source refusal.
Last read-only readiness attempt failed because Premiere was not running; readiness
has not been rechecked. Reload the panel and restart the helper for protocol cutdeck-6.
No real-host success is claimed from the offline tests.
