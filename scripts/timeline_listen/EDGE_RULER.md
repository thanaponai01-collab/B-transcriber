# Cut-edge ruler: the planner's piece edges against the user's own hand cuts

Reference rank 1: cuts the user made by hand. A cut counts only when its project has no CutDeck
rough cut (so no edge can be the Rough Cut's) and its edges are on a speech source.

## Round 1 (ruler round, 2026-11-29): pass line, written before any run

Hypothesis: the edge ruler can grow from 2 independent cuts (150 edges) to a set big enough to
separate two planner settings on a held-out half, using the user's hand cuts from before CutDeck.

- Set: every cut in `E:/Me/2.Tasks` whose project has no CutDeck rough cut and whose audio-track-1
  source is speech. Sources are transcribed into a worktree copy of the store, never the shared one.
- Split: by source file (one source never in both halves), fixed by sorted source name before scoring.
- Pass line: at least 500 scored edges in at least 6 cuts, at least 3 sources in each half; and the
  known contrast (pad 60 ms against pad 120 ms, share of edges within one 30 fps frame) resolves on
  the held-out half: the 95% bootstrap interval over sources excludes 0, same sign as on the two
  original cuts (pad 60 better).
- Wrong if: fewer edges than that, or the contrast's interval contains 0 or flips sign on held-out.
  Then the ruler cannot tell these settings apart, and that is the result.

### Result (2026-11-29): pass

`python scripts/timeline_listen/edge_ruler.py run --pads 60,120`, then `compare 120/0 60/0 --split heldout`.
The 8 new sources were transcribed into a worktree copy of the store (jobs 125-132; 20260808's three
iPhone files are VFR). Each edge is planned from its own edge word, as `keep_ranges` does, because a
piece the user kept may hold a pause of more than a second, which `plan_pieces` refuses as one stretch.

| half | days (files) | edges | pad 60: within 1 frame / 100 ms / off >200 ms | pad 120 |
|---|---|---|---|---|
| tune | 4 (6) | 444 | 52.0% / 85.1% / 43 | 26.4% / 70.7% / 43 |
| heldout | 3 (4) | 420 | 42.6% / 83.1% / 42 | 13.8% / 57.6% / 43 |

Contrast pad 120 → 60, within one frame, bootstrap over days: heldout +29.0 pts [+12.5, +38.5]
(122 better, 4 worse; 407 paired edges), tune +24.9 [+10.3, +42.5]. The two original cuts score as
before (16/46, 31/104). Caveats: 3 heldout days make a coarse bootstrap; the 0712 and 0713 sources
were both recorded on 2026-07-12 and sit in different halves.

Where pad 60 misses on tune: In edges are planned a median 33 ms early (66 of 222 more than a frame
early, 22 late); Out edges are centred (median 0; 37 early, 45 late). 43 edges are off by more than
200 ms, mostly cuts inside a word.

## Round 2 (system round, 2026-11-29): pass line, written before any run

Hypothesis: the user starts a piece closer to its first word than they end it after its last, so
a shorter pause before the In (the Out keeps 60 ms) puts more In edges within a frame of theirs.

- Change: `plan_pieces` takes the pause before the In apart from the pause after the Out. The In
  value is picked on tune only from {0, 20, 30, 40, 50} ms; heldout is scored once, with that value.
- Ruler: this edge ruler, reference rank 1 (the user's hand cuts), heldout half.
- Pass line: on heldout, the within-one-frame share of all edges rises, with a 95% bootstrap
  interval over days above 0; Out edges are unchanged; and the share of planned In edges that land
  in sound (level over the quiet threshold) rises by no more than 2 points.
- Wrong if: the heldout interval contains 0, or In edges move into sound by more than 2 points.
