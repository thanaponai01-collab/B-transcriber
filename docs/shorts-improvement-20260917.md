# CFD 95 subtitle improvement and Engine B probe

Reference: user-supplied `shorts_mine.srt`, paired with `shorts.mp3` from
`F:/Me/Works/20260917 - CFD 95/5. EXPORTS/audio`. Recognition cache: job 44,
Engine A `faster_whisper`. No reference text was passed to an ASR model.

## Confirmed defect and fix

Replaying saved word timestamps through the production splitter reproduced all
66 original cues and the isolated 240ms `อีก`, 380ms `แม่`, and 280ms `เรา`.
Removing the sizing limits eliminated these splits. Text concatenation was
unchanged: the missing/garbled speech is already present in the ASR output.

The greedy splitter now looks ahead before a size-driven split. It keeps a
tail shorter than 500ms and at most eight characters attached, allowing only
eight characters / 500ms beyond the sizing targets. Sentence boundaries and
real pauses remain hard boundaries. Recognition text and word timings are
preserved. This does not attempt to identify speakers or correct spelling.

On the supplied clip, short captions fall from four to one. The remaining
`อันนี้ก็` is separated by a pause and requires acoustic timing work; it is not
automatically merged. Cue-boundary error (1-F1, 300ms tolerance) improves from
0.213793 to 0.197183. The change produces 63 cues, versus the reference's 79;
removing bad boundaries does not recover all missing good boundaries.

Replay of the latest available raw-word caches for four other reference clips:
Short1, Short2, and Short3 have unchanged cue-boundary scores; the finance clip
improves from 0.779487 to 0.777778. All five replays preserve recognition text.
This is a cached segmentation comparison, not a fresh full-corpus ASR gate run.

## Engine B results

Measured on this clip using the installed Qwen adapter, CUDA, Thai language
hint, batch size 2 and no vocabulary hints. Scores below are raw hypotheses,
before normalization/conform; do not compare raw timing overlaps with final SRTs.

| Candidate | Thai character error | Cue count | Load + recognition time |
|---|---:|---:|---:|
| Cached Engine A | 7.2455% | 66 | not remeasured |
| Qwen3-ASR-1.7B, 8s windows | 8.5106% | 17 | 104.5s |
| Qwen3-ASR-1.7B, 25s windows | 8.9132% | 6 | 54.0s |

Both A+B reconciliations return Engine A's text unchanged. The fallback chooses
Thai A when B has no confidence; the one-to-one aligner also compares short A
cues with much longer B spans. Activating B alone therefore does not repair
this clip. Production remains `engine_b: passthrough`.

Qwen is a reasonable development candidate, not a validated production upgrade.
Its [official model card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) lists Thai
recognition support, but its companion forced aligner does **not** list Thai.
Do not assume that adding that aligner solves Thai caption timing.

The next dual-engine experiment needs comparable audio spans and evidence that
selection recovers correct alternatives without importing B's mistakes. A
language-model fluency preference alone cannot establish what the speaker said.
No English or code-switch benefit can be inferred from this all-Thai clip.

## Reproduction and artifacts

- `python -m tools.compare_subtitles REFERENCE.srt CANDIDATE.srt --output report.json`
  separates recognition/cue metrics from multiline and short-caption counts.
- `python -m tools.probe_engine_b --audio AUDIO --reference REFERENCE.srt
  --engine-a-json CACHE.json --output OUTPUT_DIR --max-span-s 8`
  probes the existing adapter without changing production config or database.
  The cache is an object with a `tokens` list of RecognizedToken dictionaries.
- Local measurements are in `output/shorts-investigation/`: original-report.json,
  replay-report.json, qwen-probe.json, and qwen-25s/report.json.
- `shorts.improved.srt` and improved-report.json contain the new splitter's
  output after the normal refinement stages. Recognition errors remain.
- `transcribe/eval/goldenset/shorts.json` is the corrected regression reference;
  its paired audio is local and gitignored. The source is recorded in SOURCES.md.
  Since this sample guided the fix, it is not an untouched holdout. Compare any
  future full-corpus baseline and candidate on the same expanded corpus.

Validation: 75 affected tests passed (splitter, subtitle I/O, conform, comparison,
gold authoring). Three warnings concern deprecated audio-library imports.
