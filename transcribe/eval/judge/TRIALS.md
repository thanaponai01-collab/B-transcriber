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

## Trials

(none yet)
