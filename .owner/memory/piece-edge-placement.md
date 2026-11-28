---
name: piece-edge-placement
status: mixed
updated: 2026-11-29
---

# Where should the planner put a piece's In and Out so they match the user's own cuts?

## What we know

The ruler is `file:scripts/timeline_listen/edge_ruler.py` over `file:scripts/timeline_listen/edge_set.json`:
10 of the user's hand cuts (projects with no CutDeck rough cut), 864 edges, halves split by recording
day (tune 4 days, heldout 3). Reference rank 1. Pass lines and results are in
`file:scripts/timeline_listen/EDGE_RULER.md`. With 30 ms of pause before the In and 60 ms after the
Out (`branch:loop/rsi-20261129`, not merged; live Premiere proof pending), 58.6% of heldout edges sit
within one 30 fps frame of the user's. Out edges are centred but spread (median 0, about half within
a frame), and about 10% of edges miss by more than 200 ms, mostly where the user cut inside a word.

## Tried

| Date | Tried | Result | Verdict | Evidence |
|---|---|---|---|---|
| 2026-11-29 | Grow the edge ruler from 2 cuts (150 edges) to 10 cuts: transcribe 8 pre-CutDeck hand-cut sources into a worktree copy of the store | 864 edges; pad 60 vs 120 resolves on heldout +29.0 pts [+12.5, +38.5], 122 better / 4 worse | worked | `edge_ruler.py run --pads 60,120`, then `compare 120/0 60/0 --split heldout` |
| 2026-11-29 | Pause before the In apart from the Out: In picked on tune from {0, 20, 30, 40, 50}, Out kept at 60 | Tune best 30 (In hits 121 → 152 of 222). Heldout scored once: 42.6% → 58.6% within a frame, +16.0 pts [+10.6, +20.0], 65 better / 0 worse. Out unchanged, planned In edges in sound 42 → 42 | worked (live proof pending) | `edge_ruler.py run --pads 60:60,30:60 ...`, `compare 60/60/0 30/60/0`; `branch:loop/rsi-20261129` |
| 2026-11-29 | Out pause search {40, 50, 80, 100} against 60, In at 30 | Tune best 40, +0.9 pts (114 vs 110 of 222 Out hits); under the 2-point bar set first, so heldout not scored | failed | `edge_ruler.py run --pads 30:60,30:40,30:50,30:80,30:100` |

## Retry when

- Out pause: the set grows (HKS finals once G: is mounted, or more hand-cut days), so a 1-point
  change can resolve; or the Out rule changes shape (for example, by the length of the pause after
  the last word: where the next word follows within 100 ms, the user's Out runs a median 60 ms past
  where the planner stops, but the two halves disagree on whether that edge is in sound).

<!-- Index line in INDEX.md, under 150 characters:
- [mixed] [Piece edge placement](piece-edge-placement.md) — 10-cut ruler; In pad 30 ms +16 pts heldout; Out pad search no gain
-->
