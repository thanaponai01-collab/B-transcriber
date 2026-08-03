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

# Blade kinds (HANDOFF_CUTDECK_WORDLEVEL.md Phase 2.3) — where a cut boundary
# came from. VAD-blade edges are trustworthy silence-edge boundaries; word-blade
# edges land inside continuous speech (filler/repeat cuts) and need the
# crossfade + review-UI attention a hard VAD cut doesn't.
BLADE_VAD = "vad"
BLADE_WORD = "word"

# Rough-cut modes (HANDOFF_CUTDECK_WORDLEVEL.md Phase 4) — ``interval`` is the
# original silence-interval-subtraction pass (rules.apply_min_clip_merge and
# its dissolve/standalone bookkeeping); ``segment`` builds keeps outward from
# segments instead, so a too-short kept island is just a short utterance, not
# a case the merge pass has to reason about.
ROUGH_CUT_INTERVAL = "interval"
ROUGH_CUT_SEGMENT = "segment"


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
    blade: str = BLADE_VAD            # BLADE_VAD | BLADE_WORD — where the edge came from
    segment_ids: list[int] = field(default_factory=list)
    # Rules-pass bookkeeping only (not serialized, see plan.to_dict): for a KEEP
    # span, how much dead air apply_min_clip_merge has already re-admitted into
    # this contiguous run. Lets the merge cap cumulative chained dissolves, not
    # just the size of the one cut being dissolved this iteration.
    dissolved_ms: int = 0

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
    # Cap on how much dead air a min-clip merge may un-cut to absorb a too-short
    # kept island. Merging across a small incidental cut is fine; merging across
    # a cut longer than this just to save a sub-min_clip_ms speech blip re-admits
    # exactly the dead air the pass exists to remove — the blip is dropped
    # instead (see apply_min_clip_merge).
    max_dissolve_ms: int = 4000

    # Stutter/duplicated-word removal (Phase 2.2) — default off until an eval
    # baseline exists, same discipline as fillers.
    repeats_enabled: bool = False
    repeat_max_ngram: int = 4
    repeat_max_gap_ms: int = 600

    # Blade contract (Phase 2.3) — audio crossfade on mid-speech word-blade cuts.
    word_blade_crossfade_ms: int = 20

    # Rough-cut pass (Phase 4). ``segment`` is new and unproven on real footage —
    # stays opt-in until it's been watched (see cutdeck/preview.py), so
    # ``apply_min_clip_merge`` and its tests stay intact behind this flag rather
    # than being deleted in the same change that introduces the replacement.
    rough_cut_mode: str = ROUGH_CUT_INTERVAL

    # Token-less speech spans (Phase 5.1) — VAD misclassifies breaths, lip
    # smacks, coughs and camera noise as speech; a "speech" span with no token
    # inside it longer than this is dead air, not content. Default off, same
    # discipline as fillers/repeats — needs an eval baseline before it can cut
    # real footage unattended.
    nonspeech_enabled: bool = False
    min_nonspeech_ms: int = 400

    # Adaptive silence threshold (Phase 5.2) — off by default; when on, the
    # fixed min_silence_ms floor is replaced by a percentile of the job's own
    # inter-speech gap distribution, floored at min_silence_ms so it can only
    # ever be more conservative (fewer cuts), never more aggressive.
    adaptive_silence: bool = False
    silence_percentile: int = 60

    # Retake/false-start classifier (Phase 6, cutdeck/takes.py) — the only
    # judgment module. Deterministic marker detection always runs (whether a
    # phrase is a marker is never the LLM's call); the LLM step that decides
    # keep/cut on the pre-filtered candidates stays off until an eval
    # baseline exists, same discipline as every other new behaviour here.
    retake_markers: tuple[str, ...] = ()
    keep_last_take: bool = True
    takes_llm_enabled: bool = False
    retake_window_segments: int = 5
    repeat_take_jaccard_threshold: float = 0.55
    false_start_max_ms: int = 2500

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
            max_dissolve_ms=int(cut.get("max_dissolve_ms", 4000)),
            repeats_enabled=bool(cut.get("repeats_enabled", False)),
            repeat_max_ngram=int(cut.get("repeat_max_ngram", 4)),
            repeat_max_gap_ms=int(cut.get("repeat_max_gap_ms", 600)),
            word_blade_crossfade_ms=int(cut.get("word_blade_crossfade_ms", 20)),
            rough_cut_mode=str(cut.get("rough_cut_mode", ROUGH_CUT_INTERVAL)),
            nonspeech_enabled=bool(cut.get("nonspeech_enabled", False)),
            min_nonspeech_ms=int(cut.get("min_nonspeech_ms", 400)),
            adaptive_silence=bool(cut.get("adaptive_silence", False)),
            silence_percentile=int(cut.get("silence_percentile", 60)),
            retake_markers=tuple(cut.get("retake_markers", []) or []),
            keep_last_take=bool(cut.get("keep_last_take", True)),
            takes_llm_enabled=bool(cut.get("llm_enabled", False)),
            retake_window_segments=int(cut.get("retake_window_segments", 5)),
            repeat_take_jaccard_threshold=float(cut.get("repeat_take_jaccard_threshold", 0.55)),
            false_start_max_ms=int(cut.get("false_start_max_ms", 2500)),
        )
