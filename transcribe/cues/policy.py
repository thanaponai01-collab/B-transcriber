"""Cue-splitting policy — the whole tuning surface of cue segmentation, in one type.

These were eight module-level constants inside the faster-whisper adapter plus six
engine constructor kwargs. Collecting them here is the point: cue segmentation owns
`cue_boundary_error_rate`, the gated signal that moves on pure-Thai shorts, so the
knobs that drive it should be readable in one place rather than hunted across a GPU
adapter. Defaults are the production values, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

# Phrase-cue grouping. ponytail: fixed heuristics — break on a speech gap, or once a
# cue reaches target length/duration. Tune here if cues read too long/short; gap_ms
# matches the pipeline's segment.gap_ms default (700 ms), target_chars/target_ms are
# subtitle-line sizing.
CUE_GAP_MS = 700
CUE_TARGET_MS = 4000
CUE_TARGET_CHARS = 42

# Whisper inserts spaces into Thai (which has none) roughly at breath/clause
# boundaries — a free segmentation signal from the acoustic model that cue
# grouping used to discard, buffering whitespace as cue-interior only. Measured
# against a hand-recut reference SRT, every space Whisper emitted inside a cue
# was a place the human either split or would have, had the cue been longer.
# So a space is a break candidate — but only once the cue already carries enough
# text to stand alone, otherwise short interjections ("โอเค โอเค") shatter into
# one-word cues. Both minima must be met.
CUE_SPACE_MIN_CHARS = 12
CUE_SPACE_MIN_MS = 700

# HANDOFF_CEILING_BREAK §5: "greedy" is the original fill above, unchanged and
# still the production default. "dp" is the cost-minimising split (see
# split.py's _split_dp) — probe it via config.yaml's
# engines.faster_whisper.cue_split_algorithm, gated with --experiment, before
# ever flipping this default.
CUE_SPLIT_ALGORITHM = "greedy"


@dataclass(frozen=True)
class CuePolicy:
    """How to cut a word-piece stream into subtitle cues.

    `lexicon` is a `transcribe.thai.atoms.BreakLexicon` (HANDOFF_THAI_BREAK_ATOMS.md):
    the break-atom set that makes STYLE_GUIDE §7's unsplittable units illegal to break
    *by construction* rather than by a veto check at each break decision. It is an
    explicit policy field so the relationship between §7 legality and cue breaking is
    visible in the interface. `None` falls back to `default_lexicon({})` — the four
    base rules, no exception-lexicon terms — matching the historic default.
    """

    gap_ms: int = CUE_GAP_MS
    target_ms: int = CUE_TARGET_MS
    target_chars: int = CUE_TARGET_CHARS
    space_min_chars: int = CUE_SPACE_MIN_CHARS
    space_min_ms: int = CUE_SPACE_MIN_MS
    algorithm: str = CUE_SPLIT_ALGORITHM
    lexicon: object | None = None
