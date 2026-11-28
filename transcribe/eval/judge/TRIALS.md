# Caption timing trials

The judge (`transcribe/eval/judge/`): hand-marked onsets and offsets (Praat), scored in frames at
each clip's sequence fps by `score.py`, locked by `judge.lock`. The lockbox labels live outside
the repo and are scored once, at the milestone.

## Rules for every trial

1. Read this log (lessons first).
2. Write a one-line hypothesis that names the cause it targets (from `causes.py`).
3. Make one change.
4. Score on tune: `python -m transcribe.eval.judge.score run --split tune --label <trial>`, then
   `score compare <baseline.json> <trial.json>`. Budget: one tune run (~1 min on cached Engine A);
   an Optuna search gets 40 tune runs.
5. Gain = the paired-bootstrap 95% CI of the within-1-frame change is above 0 on tune, or CER
   improves outside its CI. Only then check heldout, through the same compare and the gate:
   heldout must not drop (CI above -0.02 = `regression_tolerance`), and CER must not regress.
   A change downstream of Engine A must leave the text identical (`same_text: true`); one
   upstream of it (VAD, high-pass, loudness, beam) runs the full harness gate.
6. Keep or revert, then log the hypothesis, the diff, the numbers and the verdict below.
7. After every 5 trials, update Lessons and re-rank the remaining candidates.
8. Stop after 8 trials in a row with no kept gain.

## Judge (locked 2026-11-28, commit df43b52)

Reference: **provisional agent marks** (six blind agents reading spectrograms, no pipeline output;
the user chose this over waiting for Praat marks). Tune 271 edges (9 clips), heldout 279 (11),
lockbox 176 (4, outside the repo). Repeat noise between agents: onsets 94-100% within one 30 fps
frame (median 2-3 ms), offsets 81-100% (median 5-10 ms, p90 up to 45 ms on noisy clips).
Known weak spot: the two vlog clips have a music bed throughout, where "pause" is ambiguous and
the marks themselves are doubtful (overlay audit); results are also reported without them.

**Lockbox exposure:** the reports of the agents that marked the lockbox files listed some edge
times (files 29 and 33), and their marks and PNGs sat in the shared agent folder until moved to
the lockbox folder. The loop never reads them; marker briefs from now on return counts only.

## Baseline and where the misses are (Phase 1)

Speed, 600 s benchmark (2026-09-05 quali stream), two runs: 27.4 / 27.1 s total (~22x realtime).
Engine A transcribe 15.1 s, VAD 4.4 s, Whisper load 2.1 s, CTC align 2.2 s, decode 1.7 s,
CTC load 1.3 s, cue split 0.4 s, snap + retime 0.02 s, other 0.4 s.

Timing, share of marked edges within 1 frame (2 frames):

| split | starts | ends | all | placed (CutDeck nearest frame) | raw SRT import (Premiere 30 fps floor) |
|---|---|---|---|---|---|
| tune | 64% (72%) | 49% (59%) | 56% (65%) | 55% | 47% |
| heldout | 78% (91%) | 64% (73%) | 71% (82%) | 71% | 50% |

Tune misses by cause (119 of 271; ranking comes from tune only):

| cause | starts | ends |
|---|---|---|
| end snap found nothing: engine end kept | | 30 |
| snap put the edge wrong (late into the tail, or walked back mid-word) | 2 (+3 broke a right CTC start) | 25 (+1) |
| snap declined although CTC was within its 200 ms reach | 13 | |
| CTC start out of the snap's reach | 13 | |
| no word edge matched although a word covers the mark | 8 | 5 |
| missing text (no word covers the speech) | 4 | 3 |
| VAD cut | 4 | 2 |
| cue-window collision | 2 | 4 |
| wrong text | not measured (no reference transcript; the confidence proxy never fired) | |

- Premiere frame rounding costs only on a raw SRT import (+34 tune / +66 heldout misses);
  CutDeck's `srt_subtitles` snaps to the nearest frame and costs ~nothing (placed ≈ raw).
- Cue ends are within a frame of the sound only 11-26%: cues are kept gapless by design (gap
  closing), which is the user's reading-rule choice, not a trial target.
- The user's finished captions (CFD 90 Shorts, singapore) start 85-117 ms before the sound and end
  50-250 ms after it: reading rules (lead-in, tail), not sound-following.

## Lessons

(none yet)

## Prepared candidates (built, off, not yet scored: the reference is not marked yet)

| Candidate | Switch | Mechanism check (no timing score) |
|---|---|---|
| Cue windows padded into neighbours (1 ms words) | `word_align.pad_into_neighbours: false` | 1 ms words on tune+heldout clips 254 → 82 of 5296; the 82 left are words Whisper gave zero length (85 before) |
| Spectral-flux onset with backtracking | `word_align.snap_method: flux` | built (`flux_onsets`, `snap_to_flux`, same pause gate as the loudness snap) |
| Second Thai CTC checkpoint | `word_align.model: models/wav2vec2-th-ctc-airesearch.pt` | airesearch/wav2vec2-large-xlsr-53-th exported (72-symbol vocab) |
| High-pass before Whisper | Engine A cache tag `.hpf` | not built (needs a Whisper re-run per clip) |
| Loudness normalisation before VAD and snap | | not built |
| Optuna over VAD, snap, tail_db, beam | | not built |

## Trials

(none yet)
