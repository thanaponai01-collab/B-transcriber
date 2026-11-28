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
