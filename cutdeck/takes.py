"""takes.py — the LLM classifier (IMPLEMENT_CUTDECK.md §B.3 ``takes.py``).

The only judgment module in CutDeck; every other pass in ``rules.py`` is
deterministic, no LLM, ever (HANDOFF_CUTDECK_WORDLEVEL.md Phase 6). Inherits
``transcribe.pipeline.reconcile``'s select-only discipline exactly: the LLM
never sees or emits timecodes, never rewrites text, and can only choose
keep/cut on the segment ids it was shown — enforced by an explicit raise
(``HallucinatedIdError``, mirroring ``ReconcilerViolation``), not an assert,
so it survives ``python -O``.

Three patterns, all pre-filtered deterministically before the LLM sees
anything:

  * **repeated takes** — char-Jaccard > ``cfg.repeat_take_jaccard_threshold``
    (0.55) between segments within a ``cfg.retake_window_segments``-wide
    window (``find_repeat_take_clusters``). ``keep_last_take`` is the
    *default instruction* handed to the model, not a bypass — the parsed LLM
    answer always wins, same as every select-only boundary in this codebase.
  * **false starts** — a segment shorter than ``cfg.false_start_max_ms``
    (2.5s) immediately followed by a longer segment sharing a text prefix
    (``find_false_start_pairs``).
  * **explicit mistakes / retake markers** — ``rules.retake_marker_segments``
    is the deterministic pre-pass; a marker phrase either is or isn't in the
    text, and that is never the LLM's call. The LLM here only resolves *how
    far back* the retake reaches, over the window of segments preceding the
    marker.

``llm_fn`` is injected exactly like ``reconcile.py``/``llm_reconcile.py``:
``label_takes`` calls it with a plain structured candidate list (no
timestamps) and expects a parsed ``[{"id": int, "action": "keep"|"cut",
"reason": str}, ...]`` list back. Building an actual prompt and calling a
real model (Ollama, Anthropic, whatever) is a separate adapter — the same
split ``llm_reconcile.py`` uses for the reconciler — and isn't built here:
no eval baseline exists yet to gate it on (``cut.takes_llm_enabled`` stays
``false``), same discipline as every other new CutDeck behaviour in this
handoff. See CLAUDE.md's 2026-07-16 LLM-reconciler note before wiring one:
randomize candidate order from day one, and gate activation on the eval
harness, not a spot check.
"""

from __future__ import annotations

from typing import Callable, Optional

from cutdeck.contracts import (
    CUT,
    KEEP,
    LABEL_FALSE_START,
    LABEL_KEEP_WORTHY,
    LABEL_MISTAKE,
    LABEL_RETAKE,
    SOURCE_LLM,
    SOURCE_RULE,
    CutConfig,
    Label,
    Segment,
)
from cutdeck.rules import retake_marker_segments

# callable(candidates, bias_terms) -> [{"id": int, "action": "keep"|"cut", "reason": str}]
LlmFn = Callable[[list[dict], list[str]], list[dict]]


class HallucinatedIdError(RuntimeError):
    """The LLM classifier emitted/omitted a segment id — a select-only breach."""


# ── deterministic pre-filters ───────────────────────────────────────────────

def _char_jaccard(a: str, b: str) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_repeat_take_clusters(segments: list[Segment], cfg: CutConfig) -> list[list[Segment]]:
    """Adjacent near-duplicate segments within a sliding window → clusters.

    Char-Jaccard > ``cfg.repeat_take_jaccard_threshold`` within
    ``cfg.retake_window_segments`` segments of each seed. Clusters never
    overlap: once a segment joins one, it can't seed or join another.
    """
    n = len(segments)
    used = [False] * n
    clusters: list[list[Segment]] = []
    for i in range(n):
        if used[i]:
            continue
        cluster = [segments[i]]
        members = [i]
        for j in range(i + 1, min(n, i + cfg.retake_window_segments)):
            if used[j]:
                continue
            if _char_jaccard(segments[i].text, segments[j].text) > cfg.repeat_take_jaccard_threshold:
                cluster.append(segments[j])
                members.append(j)
        if len(cluster) > 1:
            for k in members:
                used[k] = True
            clusters.append(cluster)
    return clusters


def find_false_start_pairs(
    segments: list[Segment], cfg: CutConfig,
) -> list[tuple[Segment, Segment]]:
    """A short segment (< ``cfg.false_start_max_ms``) immediately followed by
    a longer segment that echoes most of its text — the classic false start
    ("ผม... ผมคิดว่า...")."""
    pairs: list[tuple[Segment, Segment]] = []
    for a, b in zip(segments, segments[1:]):
        if a.duration_ms >= cfg.false_start_max_ms:
            continue
        if b.duration_ms <= a.duration_ms:
            continue
        if not a.text:
            continue
        shared = 0
        for ca, cb in zip(a.text, b.text):
            if ca != cb:
                break
            shared += 1
        if shared / len(a.text) >= 0.5:
            pairs.append((a, b))
    return pairs


# ── LLM call + select-only validation ───────────────────────────────────────

def _candidate_payload(segments: list[Segment], gap_before_ms: dict[int, int]) -> list[dict]:
    """No timestamps in the decision space — duration and gap-before only."""
    return [
        {
            "id": seg.id,
            "text": seg.text,
            "duration_ms": seg.duration_ms,
            "gap_before_ms": gap_before_ms.get(seg.id, 0),
        }
        for seg in segments
    ]


def _validate_coverage(reply: list[dict], valid_ids: set[int]) -> dict[int, dict]:
    decided: dict[int, dict] = {}
    for item in reply:
        sid = item.get("id")
        if sid not in valid_ids:
            raise HallucinatedIdError(
                f"LLM classifier emitted id {sid!r} not in candidate set "
                f"{sorted(valid_ids)!r}. This violates the select-only rule."
            )
        decided[sid] = item
    missing = valid_ids - decided.keys()
    if missing:
        raise HallucinatedIdError(
            f"LLM classifier left ids {sorted(missing)!r} uncovered out of "
            f"candidate set {sorted(valid_ids)!r} — every id must be covered."
        )
    return decided


def classify_cluster(
    segments: list[Segment],
    kind: str,
    llm_fn: LlmFn,
    gap_before_ms: dict[int, int],
    bias_terms: Optional[list[str]] = None,
) -> list[Label]:
    """Ask the LLM to keep/cut every segment in one cluster.

    ``ids`` the LLM is shown are exactly this cluster's segment ids — the
    no-generation guard (``_validate_coverage``) enforces the answer covers
    exactly this set, never more, never fewer, mirroring
    ``reconcile._pick``'s ``ReconcilerViolation``.
    """
    valid_ids = {seg.id for seg in segments}
    payload = _candidate_payload(segments, gap_before_ms)
    reply = llm_fn(payload, bias_terms or [])
    decided = _validate_coverage(reply, valid_ids)
    return [
        Label(
            segment_id=sid,
            action=CUT if decided[sid].get("action") == "cut" else KEEP,
            kind=kind,
            source=SOURCE_LLM,
            reason=decided[sid].get("reason"),
        )
        for sid in sorted(decided)
    ]


# ── orchestration ────────────────────────────────────────────────────────────

def label_takes(
    segments: list[Segment],
    cfg: CutConfig,
    llm_fn: Optional[LlmFn] = None,
    bias_terms: Optional[list[str]] = None,
) -> list[Label]:
    """Layer 3 labels for the three retake/false-start/mistake patterns.

    Deterministic base: every segment keeps (mirrors ``rules.label_segments``).
    Off unless both ``llm_fn`` is supplied *and* ``cfg.takes_llm_enabled`` —
    the marker pre-pass (``rules.retake_marker_segments``) still runs
    unconditionally since it is deterministic, not a judgment call, but with
    the LLM off a bare marker hit is left KEEP: false-cutting a real sentence
    that happens to echo a retake phrase is worse than missing a real retake
    (this handoff's prime directive).
    """
    by_id: dict[int, Label] = {
        seg.id: Label(segment_id=seg.id, action=KEEP, kind=LABEL_KEEP_WORTHY, source=SOURCE_RULE)
        for seg in segments
    }
    if not segments or llm_fn is None or not cfg.takes_llm_enabled:
        return [by_id[seg.id] for seg in segments]

    gap_before_ms = {
        seg.id: (seg.start_ms - segments[i - 1].end_ms if i > 0 else 0)
        for i, seg in enumerate(segments)
    }

    for marker_id in retake_marker_segments(segments, cfg):
        idx = next(i for i, s in enumerate(segments) if s.id == marker_id)
        window_start = max(0, idx - cfg.retake_window_segments)
        window = segments[window_start:idx + 1]
        for label in classify_cluster(window, LABEL_MISTAKE, llm_fn, gap_before_ms, bias_terms):
            by_id[label.segment_id] = label

    for cluster in find_repeat_take_clusters(segments, cfg):
        for label in classify_cluster(cluster, LABEL_RETAKE, llm_fn, gap_before_ms, bias_terms):
            by_id[label.segment_id] = label

    for a, b in find_false_start_pairs(segments, cfg):
        for label in classify_cluster([a, b], LABEL_FALSE_START, llm_fn, gap_before_ms, bias_terms):
            by_id[label.segment_id] = label

    return [by_id[seg.id] for seg in segments]
