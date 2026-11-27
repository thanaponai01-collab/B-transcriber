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
