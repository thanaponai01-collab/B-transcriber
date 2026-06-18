"""CutDeck — the rough-cut editing system (IMPLEMENT_CUTDECK.md Part B).

A sibling package to ``transcribe`` that consumes the same SQLite store and
inherits the same invariants: select-only decisions, eval-gated flywheel,
model-agnostic contracts. CutDeck never touches the video file — it only ever
manipulates a *timeline description* (the CutPlan). Premiere is the renderer.

The layered timeline (B.1):

    Layer 0  VAD spans   speech/silence        (speech_span table, GAP-3)
    Layer 1  tokens      word text + ms spans  (token table)
    Layer 2  segments    utterance grouping    (segment.py — Phase 1)
    Layer 3  labels      filler/retake/...     (rules.py + takes.py)
    Layer 4  cut plan    keep/cut spans        (plan.py — the output)
"""
