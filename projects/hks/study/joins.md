# Uncovered joins, checked by frame (overnight study)

Every join in each YT cut where `hks_gold` finds the synced studio picture on both sides at the same
framing (no cover). Each was checked by the last frame before and the first frame after, pulled
from the source with ffmpeg (`output/hks_study/study_joins.py` → `joins.tsv`; mean absolute difference
on 160x90 grey: ≥ 20 = a camera change, < 10 = same picture).

| Day | Joins | Camera change | Same picture | Unclear |
|---|---|---|---|---|
| 1001 | 23 | 21 | 0 | 2 |
| 1002 | 25 | 23 | 2 | 0 |
| 1003 | 29 | 29 | 0 | 0 |
| 1012 | 30 | 27 | 0 | 3 |
| 1020 | 39 | 35 | 3 | 1 |
| 1109 | 15 | 15 | 0 | 0 |
| 1110 | 30 | 30 | 0 | 0 |
| 1112 | 32 | 32 | 0 | 0 |
| 1117 | 17 | 17 | 0 | 0 |
| 1118 | 25 | 23 | 0 | 2 |
| 1120 | 25 | 23 | 1 | 1 |
| 1123 | 22 | 21 | 1 | 0 |

The 16 flagged joins were checked by eye:
- **Under a still, invisible:** 1002 1017.7 and 1035.4 (a flood map), 1020 155.8–159.2 (a chat
  screenshot; only the blurred TV clock ticks).
- **Unclear = a layout change:** 1001 149.6, 1012 957.96, 1118 340.7 and the rest change the inset
  box or the split layout, which is a picture change.
- **Real same-shot jumps, 2 in 12 cuts:** 1120 686.6 (0.56 s, inside Nam's own interview clip;
  already in the workflow log) and 1123 1178.9 (0.2 s on the masked three-shot near the end:
  masked guests barely move, so it hardly shows).

So the user's "no jump cuts" (rule 5) holds on 343 of 345 uncovered joins. The cuts don't need a
cover where the broadcast already changes camera. This also settles the questions the episode
studies raised (1001 598.0, 1012 and 1112 uncovered joins): all camera changes. 1001 598.04
(the possible jump on Tee in [20261001-yt.md](20261001-yt.md)) is a camera change (difference 62.5).

**Scope (pass 2, 2026-11-24):** only joins with the synced studio picture on both sides are counted.
Joins inside a VTR clip or a masked close-up are outside it: the 1003 study finds small same-shot jumps at
seq 107–115 (src 703.8–713.6, one masked close-up). "343 of 345" holds for the studio picture only.
