"""CutDeck contracts — the layered-timeline data structures (IMPLEMENT_CUTDECK.md §B.2).

These are the durable boundary types for the rough-cut system, mirroring the
discipline of ``transcribe/contracts.py``:

  * ``Segment``   — Layer 2: an utterance grouping of tokens.
  * ``Label``     — Layer 3: a keep/cut judgement on a segment (rule or LLM).
  * ``CutSpan``   — Layer 4: one contiguous keep|cut region of the timeline.
  * ``CutPlan``   — Layer 4: the versioned artifact; spans are contiguous and
    exhaustive over the media duration (a cut is *represented, not deleted*).
  * ``CutConfig`` — the ``cut:`` / ``segment:`` policy block from ``config.yaml``.

``Timebase`` is re-exported from ``transcribe.timebase`` so frame math has exactly
one authority across both packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Single frame-math authority — re-exported, never reimplemented (GAP-1).
from transcribe.timebase import Timebase  # noqa: F401  (re-export)

PLAN_VERSION = "1.0"

# Layer-4 actions. A span is exactly one of these.
KEEP = "keep"
CUT = "cut"

# Label kinds (Layer 3). Deterministic rules emit 'silence' / 'filler'; the LLM
# classifier (Phase 5) emits the judgement kinds. Listed here so the vocabulary
# has one home even though Phase 1 only produces the first two.
LABEL_SILENCE = "silence"
LABEL_FILLER = "filler"
LABEL_FALSE_START = "false_start"
LABEL_RETAKE = "retake"
LABEL_MISTAKE = "mistake"
LABEL_KEEP_WORTHY = "keep_worthy"

# Sources — who decided a cut. The flywheel attributes corrections by this.
SOURCE_RULE = "rule"
SOURCE_LLM = "llm"


@dataclass(frozen=True)
class Segment:
    """Layer 2 — a contiguous run of tokens forming one utterance.

    ``token_ids`` are the *idx* values of the underlying tokens (stable across the
    job), not row ids. ``text`` is the joined token text, for the LLM/review UI.
    """
    id: int
    start_ms: int
    end_ms: int
    token_ids: list[int]
    text: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class Label:
    """Layer 3 — a keep/cut judgement attached to a segment.

    ``source`` is one of SOURCE_RULE | SOURCE_LLM. ``kind`` is the reason vocabulary
    above (silence/filler/retake/...). Phase 1 only produces rule labels.
    """
    segment_id: int
    action: str           # KEEP | CUT
    kind: str             # LABEL_* — why
    source: str           # SOURCE_RULE | SOURCE_LLM
    reason: Optional[str] = None


@dataclass
class CutSpan:
    """Layer 4 — one contiguous region of the source timeline.

    Spans tile the whole media duration with no gaps and no overlaps; a cut is
    kept in the plan (action=CUT) rather than dropped, so the review UI and the
    diff both see the full picture.
    """
    idx: int
    src_in_ms: int
    src_out_ms: int
    action: str                       # KEEP | CUT
    reason: Optional[str] = None      # 'silence', 'filler', 'min_clip_merge', ...
    source: Optional[str] = None      # SOURCE_RULE | SOURCE_LLM
    segment_ids: list[int] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return self.src_out_ms - self.src_in_ms


@dataclass
class CutPlan:
    """Layer 4 — the system's contract artifact (serialized to ``cut_plan.plan_json``)."""
    job_id: int
    media_sha256: str
    timebase: Timebase
    spans: list[CutSpan]
    plan_version: str = PLAN_VERSION

    @property
    def keep_spans(self) -> list[CutSpan]:
        return [s for s in self.spans if s.action == KEEP]

    @property
    def duration_ms(self) -> int:
        return self.spans[-1].src_out_ms if self.spans else 0


# ── config ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CutConfig:
    """The ``cut:`` and ``segment:`` policy from config.yaml, with defaults.

    Built from the parsed yaml dict via :meth:`from_yaml` so the rule modules take
    a plain typed object and stay decoupled from file IO (testable in isolation).
    """
    # Segmentation (Layer 2)
    gap_ms: int = 700                     # token gap that starts a new segment
    segment_vad_silence_ms: int = 500     # VAD silence between tokens that splits

    # Silence cuts (rules §1)
    min_silence_ms: int = 900             # VAD silence longer than this becomes a cut
    pad_pre_ms: int = 250                 # kept pre-roll before following speech
    pad_post_ms: int = 120                # kept post-roll after preceding speech

    # Filler removal (rules §2) — default off until the first eval baseline
    fillers_enabled: bool = False
    filler_lexicon: tuple[str, ...] = ()
    filler_lexicon_contextual: tuple[str, ...] = ()
    contextual_isolation_ms: int = 200    # silence both sides to cut a contextual filler

    # Min-clip merge (rules §3)
    min_clip_ms: int = 1200

    @classmethod
    def from_yaml(cls, cfg: dict) -> "CutConfig":
        cut = (cfg or {}).get("cut", {}) or {}
        seg = (cfg or {}).get("segment", {}) or {}
        return cls(
            gap_ms=int(seg.get("gap_ms", 700)),
            segment_vad_silence_ms=int(seg.get("vad_silence_ms", 500)),
            min_silence_ms=int(cut.get("min_silence_ms", 900)),
            pad_pre_ms=int(cut.get("pad_pre_ms", 250)),
            pad_post_ms=int(cut.get("pad_post_ms", 120)),
            fillers_enabled=bool(cut.get("fillers_enabled", False)),
            filler_lexicon=tuple(cut.get("filler_lexicon", []) or []),
            filler_lexicon_contextual=tuple(cut.get("filler_lexicon_contextual", []) or []),
            contextual_isolation_ms=int(cut.get("contextual_isolation_ms", 200)),
            min_clip_ms=int(cut.get("min_clip_ms", 1200)),
        )
