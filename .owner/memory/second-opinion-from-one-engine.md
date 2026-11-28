---
name: second-opinion-from-one-engine
status: failed
updated: 2026-11-28
---

# Can Engine A give itself a second opinion (several decodes of one file, pooled or voted)?

## What we know

No cheap way found. One decode per file stays the transcript (`file:cutdeck/timeline_transcript.py`).
Decodes of the same audio do differ: 7-8% of characters on a 96-minute file, 2-3.5% on the short gold
clips. But the differences are not errors a vote can fix: the best of three shifted decodes per clip
gains 4.3% on `cer_thai`, and a shifted decode alone is worse than the unshifted one.
The earlier self-ensemble (beam 1 against beam 5) is recorded in `file:TODO_LEDGER.md` (Phase D).
Still unexplained: why long files disagree more than short clips.

## Tried

| Date | Tried | Result | Verdict | Evidence |
|---|---|---|---|---|
| 2026-11-28 | Pool the three recordings of one session (store jobs 79, 81, 82, files of 2026-11-21) to fill speech one decode dropped | The three files carry the same voice feed (10 ms level envelopes correlate 1.0 and 0.999, median level difference 0 dB, offsets -300 and +890 ms), so there is no second microphone. Whole-text character disagreement 7.3%, 7.3%, 8.3%. At most 11 of job 79's 26 dropped-speech spans have another file's cue over them (time overlap, an upper bound). No pass line was set before the run | failed | Read-only scratch script over the `token` and `speech_span` tables of `transcriber.db` and the cached level envelopes; Levenshtein distance on text stripped of spaces and punctuation |
| 2026-11-28 | Decode each gold clip with 0, 137, 263 and 300 ms of silence prepended, and an AAC 128k copy; score the best of (0, 137, 263) per clip as the most a vote could reach. Pass line set first: at least 3% disagreement and at least 15% relative `cer_thai` gain | 4 clips with audio (Short1-3, yt t1 singapore; 2,208 Thai chars). `cer_thai`: 0 ms 0.0530, 137 ms 0.0539, 263 ms 0.0697, 300 ms 0.0661, AAC 0.0498. Disagreement between offsets 2.1%, 3.1%, 3.5%. Best of three 0.0507, a 4.3% gain | failed | Scratch script: `harness._load_goldenset`, `pipeline.run.run_file` on a scratch store with a warm engine and `word_align` off, `metrics.compute_metrics`. Production config otherwise |

## Retry when

- The voice is recorded on two different microphones (then pooling has two real signals).
- A gold set of long files exists (10 minutes or more), since long files disagree far more than the short clips this was scored on.
- The engine changes: the fragility to a start shift belongs to this checkpoint and its batched decode.

<!-- Index line in INDEX.md, under 150 characters:
- [failed] [Second opinion from one engine](second-opinion-from-one-engine.md) — shifted decodes differ but a vote gains 4%
-->
