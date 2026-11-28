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

After trials 1-5:
1. The snap's knobs are where the frames are. One search moved 26 tune edges into a frame for 4
   moved out, and it held on heldout (+8.2 pts). Cause-ranked: ends (end snap found nothing / put
   the edge wrong) were 55 of 119 tune misses.
2. Operations that only rescale levels do nothing to the snap, whose thresholds are relative to
   the local floor and peak (AGC: 0 edges moved).
3. Spectral flux is a worse onset cue than loudness on this audio (room noise, music beds): it
   fires on non-speech changes.
4. A tune gain whose better/worse edge counts are close (22/19) did not replicate on heldout;
   one with a lopsided count (26/4) did. Read the edge counts, not only the CI.
5. Three T5 knobs sit at their search bounds (start reach 38/40, start pause 3/3, end reach
   79/80): the next search should widen them.

Ranked next: T6 wider snap search; T7 bounded cue windows on the new baseline; T8 high-pass
before Whisper (Engine A re-run + CER gate); T9 loudness normalisation before VAD (VAD cuts are 6
of 119 tune misses: low).

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

Within-1-frame share of all marked edges (starts + ends); delta = paired, CI = 95% clip bootstrap.

| # | Hypothesis (cause targeted) | Change | Tune | Heldout | Verdict |
|---|---|---|---|---|---|
| T1 | Starts the loudness snap declines or misplaces (26 tune) land better on a spectral-flux onset backtracked to its energy minimum | `snap_method: flux` | 56.1 → 48.3 (−7.7, CI −11.9…−3.3; 6 better / 20 worse) | not run | **reverted** |
| T2 | CTC placement: a second Thai CTC checkpoint places first/last letters closer to the sound | `model: models/wav2vec2-th-ctc-airesearch.pt` (airesearch/wav2vec2-large-xlsr-53-th) | 56.1 → 59.4 (+3.3, CI +0.4…+6.5; 22/19) | 70.97 → 71.3 (+0.4, CI −2.1…+3.0; 16/15): no regression, gate passes | **kept** (weak: tune gain did not replicate) |
| T3 | Cue-window collisions (6 tune misses; 1 ms words) | `pad_into_neighbours: false` | 56.1 → 58.3 (+2.2, CI −0.4…+5.4; 11/8) | not run | no frame gain; hygiene: 1 ms words 254 → 82 of 5296, text identical, w1 not worse. **User's call** |
| T4 | Snap misses from level differences between loud and soft passages (loudness normalisation before the snap) | `level_norm: agc` (3 s rolling peak) | 59.4 → 59.0 (−0.4, CI −1.1…0; 0/0) | not run | **reverted** (no effect: snap thresholds are relative) |
| T5 | End snap finds nothing / misplaces (55 tune misses) and start snap declines (13): its thresholds are mis-set | Optuna, 40 evaluations on tune, CTC cached: `start_snap {reach 38, pause 3, quiet_db 7.09, range_db 17.73}`, `end_snap {reach 79, pause 6, quiet_db 10.67, below_peak_db 34.05, tail_db 25.61, hold_db 2.0}` | 59.4 → 70.5 (+11.1, CI +5.3…+17.8; 26/4); starts 66.7 → 76.3, ends 52.2 → 64.7; start median unchanged (−18 ms) | 71.3 → 79.6 (+8.2, CI +4.4…+12.1; 26/10); starts 76.6 → 86.5, ends 65.9 → 72.5 | **kept** |
| T6 | The T5 search stopped at its bounds; wider bounds find more of the end-snap misses | Optuna, 40 evaluations, wider bounds: start reach 51, pause 1; end reach 111, tail_db 31.6 | 70.5 → 70.8 (+0.4, CI 0…+1.2; 2/0) | not run | **reverted** (converged; start pause pinned at a 10 ms bound) |
| T7 | Cue-window collisions, re-tested on the T5 baseline | `pad_into_neighbours: false` | 70.5 → 70.5 (0.0, CI −1.1…+1.0; 9/6) | not run | no frame gain; hygiene as T3. **User's call** |
| T8 | Low-frequency rumble makes Whisper misplace or miss words (missing text 7, no edge matched 13) | zero-phase 80 Hz high-pass on Engine A's input only (Whisper re-run) | 70.5 → 69.4 (−1.1, CI −3.6…+1.5; 14/11) | CER_thai 0.0530 → 0.0562 (Δ CI 0…+0.0082, UNRESOLVED); cue_BER 0.333 → 0.302 | **reverted** (CER worse, no timing gain; code removed) |
| T9 | VAD cuts (6 tune misses): a lower engine VAD threshold keeps soft onsets | `engines.faster_whisper.vad_threshold: 0.25` (Whisper re-run) | 70.5 → 70.5 (0.0; 2/0) | CER: pending | no timing gain |
| T10 | VAD cuts: shorter minimum silence splits windows at real pauses | `vad_min_silence_ms: 300` (Whisper re-run) | 70.5 → 70.5 (0.0; 0/0) | CER: pending | no timing gain |
| T11 | Beam width: a narrower beam changes word boundaries little and is faster | `beam_size: 3` (Whisper re-run) | 70.5 → 70.8 (+0.4, CI −1.6…+2.2; 9/4) | CER: pending; speed: pending | no timing gain |

T1-T7: text identical (`same_text: true`), so CER is unchanged by construction. The kept
config (T2 + T5) through the harness on a copy of the eval DB (experiment run, vs eval_run 8):
CER_thai 0.0530 → 0.0530 (Δ CI 0…0), cue_BER 0.333 → 0.310 (Δ CI −0.093…+0.049): UNRESOLVED
(small gold set), not a regression.
