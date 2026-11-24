from __future__ import annotations

from dataclasses import dataclass

CUE_GAP_MS = 700
CUE_TARGET_MS = 4000
CUE_TARGET_CHARS = 42

CUE_SPACE_MIN_CHARS = 12
CUE_SPACE_MIN_MS = 700

CUE_SPLIT_ALGORITHM = "greedy"


@dataclass(frozen=True)
class CuePolicy:
    """How to cut a word-piece stream into subtitle cues.

    `lexicon` is a `transcribe.thai.atoms.BreakLexicon` (HANDOFF_THAI_BREAK_ATOMS.md):
    the break-atom set that makes STYLE_GUIDE §7's unsplittable units illegal to break
    *by construction* rather than by a veto check at each break decision. `None` falls
    back to `default_lexicon({})` — the four base rules, no exception-lexicon terms.
    """

    gap_ms: int = CUE_GAP_MS
    target_ms: int = CUE_TARGET_MS
    target_chars: int = CUE_TARGET_CHARS
    space_min_chars: int = CUE_SPACE_MIN_CHARS
    space_min_ms: int = CUE_SPACE_MIN_MS
    algorithm: str = CUE_SPLIT_ALGORITHM
    lexicon: object | None = None
