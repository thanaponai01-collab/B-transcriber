# Issue #72 Result Report

## 1. Goal
transcribe(audio): derive whole-file decode windows from ingest speech spans to drop the second full-file Silero VAD pass (issue #72).

## 2. Scrutiny & Architectural Analysis
- **Goal verification**: Every transcription job previously ran Silero VAD twice over full audio arrays: once in `ingest.py` (with RMS gate and sound guard) and once in `FasterWhisperEngine.transcribe` -> `speech_windows` (via `faster_whisper.vad.get_speech_timestamps`).
- **Hazard identified**: Downstream filters (`refine.drop_tokens_over_silence` and `coverage.find_gaps`) judged tokens against `ingest_result.spans`, causing artificial coverage gaps or token drops whenever the two VAD passes disagreed.
- **Unit & Padding Alignment**:
  - Ingest spans are in milliseconds (`start_ms`, `end_ms`).
  - `faster_whisper.vad` pads spans by 400ms (`speech_pad_ms=400`) and splits inter-span gaps under 800ms (`2 * speech_pad_ms`) evenly between adjacent spans, resulting in reported 0.0s gaps that `_merge_contiguous_spans` merges.
  - Implemented `_pad_speech_spans` to match this exact padding and boundary behavior.
- **Backward Compatibility**:
  - Existing tests monkeypatching `speech_windows` with 2-argument lambdas `lambda a, p: ...` remain unaffected because `_transcribe_batched` calls `speech_windows(audio, self._window_policy)` when `speech_spans` is empty/falsy.
  - Empty `speech_spans` safely falls back to `_vad_speech_spans`.

## 3. Implementation
- [transcribe/contracts.py](file:///e:/Me/5.Claude/Transcriber_v2/transcribe/contracts.py): Added `speech_spans: tuple[tuple[int, int], ...] = ()` to `EngineInput`.
- [transcribe/audio/windows.py](file:///e:/Me/5.Claude/Transcriber_v2/transcribe/audio/windows.py): Added `speech_pad_ms: int = 400` to `WindowPolicy`, added `_pad_speech_spans`, and updated `speech_windows` to derive windows directly from `speech_spans` when supplied, falling back to `_vad_speech_spans` when empty.
- [transcribe/pipeline/engine_run.py](file:///e:/Me/5.Claude/Transcriber_v2/transcribe/pipeline/engine_run.py): Added `speech_spans` to `DecodeInputs` and threaded it through `_run_engine_a`, `_run_engine_b`, `_decode_self_ensemble_b`, and `_transcribe_with`.
- [transcribe/pipeline/run.py](file:///e:/Me/5.Claude/Transcriber_v2/transcribe/pipeline/run.py): Extracted `speech_spans` from `ingest_result.spans` and passed into `DecodeInputs`.
- [transcribe/engines/faster_whisper.py](file:///e:/Me/5.Claude/Transcriber_v2/transcribe/engines/faster_whisper.py): Threaded `speech_spans` into `_transcribe_batched` and passed to `speech_windows`.
- [transcribe/engines/qwen3_asr.py](file:///e:/Me/5.Claude/Transcriber_v2/transcribe/engines/qwen3_asr.py): Threaded `speech_spans` into `_speech_spans_s`.
- [tests/test_audio_windows_speech_spans.py](file:///e:/Me/5.Claude/Transcriber_v2/tests/test_audio_windows_speech_spans.py): Added tests for skipping VAD, padding, merging, splitting, empty fallback, and clamping.
- [tests/test_faster_whisper.py](file:///e:/Me/5.Claude/Transcriber_v2/tests/test_faster_whisper.py): Added test for `transcribe` threading `speech_spans`.

## 4. Verification & Eval Metrics

### Unit Tests
- `tests/test_audio_windows.py`: 14 passed
- `tests/test_audio_windows_speech_spans.py`: 5 passed
- `tests/test_faster_whisper.py`: 8 passed
- `tests/test_smoke.py`: 18 passed
- `tests/test_coverage_guard.py`: 8 passed
- `tests/test_cues_policy_config.py`: 6 passed

### Eval Harness (Gated Signals Comparison)
| Metric | Baseline | Post-Implementation | Status |
|---|---|---|---|
| `CER_thai` (primary) | 0.0598 | 0.0530 | **Improved** (-0.0068) |
| `WER_latin` | 0.9231 | 0.9231 | Parity |
| `speech_coverage_miss` | 0.0075 | 0.0000 | **Improved to 0** |
| `cue_overlaps` | 0 | 0 | Parity (0 hard requirement) |
| `cue_BER` | 0.2970 | 0.3253 | Within tolerance (0.02 tolerance against CI) |
| `harness status` | passed=True | passed=True | **PASS** |
