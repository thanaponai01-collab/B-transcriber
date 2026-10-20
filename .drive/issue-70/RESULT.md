# Drive Result: Issue #70

## Goal
transcribe(faster_whisper): batch long-run windows and truncated-tail recoveries, and record segment stats on long runs (issue #70)

## Evidence & Playbook
- **Playbook:** `evolve-maintain` + `correctness-gate` + `scrutinize`.
- **Model Routing:** Current coordinator session (Gemini 3.8 Flash) executed directly without subagent delegation overhead.
- **Run Contract:** Frozen in `.drive/issue-70/contract.json` and executed via `run.py`.

## What Changed
1. **Batched Sub-Windows in `long_runs`:**
   In `FasterWhisperEngine._transcribe_batched`, multi-window continuous speech spans (`long_runs`) are now gathered into a single `long_clip` and decoded via a single batched GPU forward pass `self._decode(audio, long_clip, False, common, bs)` (`batch_size=bs`) instead of looping sequentially over each 25s window with `batch_size=1`.
2. **Segment Statistics Recorded on `long_runs`:**
   `self._note_segments(segments)` is now invoked on `long_runs` segments as well as `normal` spans, populating `engine_result.raw_segments_json` and `service.review_flags` with global `start_ms` and `end_ms` for all continuous monologues >25s.
3. **Batched Tail-Recovery Retries:**
   Candidate tail recovery intervals are planned and batched via `_batch_recover_tails` into a single batched decode pass when multiple candidate tails exist, eliminating serial `batch_size=1` GPU calls.
4. **Overlapping Clip Padding Safeguard:**
   Addressed faster-whisper upstream assertion failure in `BatchedInferencePipeline.transcribe` (`assert duration >= duration_after_vad`) by padding `audio_arr` with zeros when the sum of overlapping clip durations exceeds raw audio length, ensuring non-negative timestamps in faster-whisper's internal VAD logger.

## Verification
- `tests/test_faster_whisper.py`: 7/7 unit tests passed, including `test_long_runs_batched_clip_timestamps_and_seam_stitching`, `test_segment_stats_recorded_for_both_normal_and_long_runs`, and `test_long_runs_batched_tail_recoveries`.
- All Faster Whisper tests (31 items): 31 passed in 2.50s.
- `VERIFY.md` Engines suite (98 items): 98 passed.
- `VERIFY.md` Audio Ingest suite (56 items): 56 passed.
- CutDeck node test suite (714 tests): 714 passed, 0 failed.
- Eval harness: `python -m transcribe.eval.harness --config transcribe/config.yaml --experiment` — `passed=True`, `CER_thai=0.0598`, `cue_overlaps=0`, `rtf=0.144`.
