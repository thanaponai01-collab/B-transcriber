# Current work

History: [ClubFriday history](work/clubfriday-history.md), [CutDeck history](work/cutdeck-history.md).
Current execution state owned by [RUN.json](RUN.json) (status: complete at issue #76).

## Pipeline Evolution & Robustness (Issues #69-#76) - 2026-10-20
- **#69:** Reset `last_speech_timestamp` on segment breaks, filter silent/empty segments (`tests/test_faster_whisper.py`).
- **#70:** Added `TranscribeService` (`transcribe/service.py`) orchestrator with atomic jobs, metrics v4, batch long_runs windows (`tests/test_service.py`, `tests/test_metrics_v4.py`).
- **#71:** Warm Engine A instance residency across `coverage_guard` (`tests/test_coverage_guard.py`).
- **#72:** Whole-file decode windows derived from ingest speech spans, dropping duplicate Silero VAD pass (`tests/test_audio_windows_speech_spans.py`).
- **#73:** Enforce `resume_fingerprint` in `find_finished_job` and strip prompt/hotwords on tail retries (`tests/test_faster_whisper.py`).
- **#74:** Warm Engine A across harness clips and drop duplicate audio decode + hashes (`tests/test_phase6_evalperf.py`).
- **#75:** Deduplicate 3x PyThaiNLP `word_tokenize`, scope compression_ratio, spoken-Thai lexicon cache (`tests/test_review.py`).
- **#76:** Synchronize `SYSTEM_SPEC.md` with `METRICS_VERSION=4`, service.py, coverage.py, review.py, qwen3_asr.py (`tests/test_system_spec_sync.py`).

## Spikes and Live Probes (CutDeck)
- **Transform & Text Bounds (2026-10-19):** Blue text box snapping implemented for Align/Distribute (`6a3661e`, `5b344c0`, `a662187`); live textcanvas probe documented in `docs/research/cutdeck-native-text-bounds-2026-10-19.md`.
- **Native Cutter Spike (2026-10-16):** Read-only Control Surface plugin spike (`tools/native-cutter-spike/`); pending live host command catalog.

## Blockers and limits
- Real GPU ASR and full gold-set eval harness remain manual (VERIFY.md blind spot).
- Live Premiere host checks require running Premiere with active sequence; offline tests use `tests/fakes/premiere.cjs`.
- UXP direct text editing/writing remains unsupported by Premiere APIs (PREMIERE_FACTS.md).

## Next
Run live verification in Premiere: test Transform blue text box alignment and Rough Cut on a live sequence; alternatively run full GPU evaluation harness (`python -m transcribe.eval.harness --config transcribe/config.yaml`).
Completion check: `node --test tests/*.cjs` (panel suites) and `python -m pytest tests/test_smoke.py tests/test_system_spec_sync.py -v`.
