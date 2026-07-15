"""Flywheel — learn from a fully hand-corrected final .srt (e.g. re-timed and
re-cut in an NLE like Premiere Pro), not just edits made through the web editor.

The web editor's correction path (diff.py) matches original and corrected
tokens by `idx` — valid only when the human edited text in place without
retiming or re-cutting cues. A final NLE export breaks that assumption: cues
can be merged, split, retimed, deleted, or inserted, so there is no longer a
1:1 `idx` correspondence to diff against.

This module re-establishes correspondence by *time overlap* instead of `idx`:
original tokens and final cues are both non-overlapping interval sequences
over the same audio, so any two intervals that share time almost certainly
describe the same underlying speech. Connected components over that overlap
graph naturally express merges (N originals -> 1 final), splits (1 original
-> N final), deletions (1 original -> 0 final), and insertions (0 original ->
1 final) without needing separate cases for each.

Once grouped, correction rows are written through the same `correction` table
and `update_bias_index` promotion path as the web editor — this module's only
job is producing valid `CorrectionPair`s from a time-shuffled cue list.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from transcribe.db import store
from transcribe.flywheel.diff import CorrectionPair, extract_changed_span

# Below this, an "overlap" is almost certainly float/rounding noise at a cut
# boundary, not real shared speech (see align_hyp.py's _MATCH_PROX_MS for the
# analogous constant in the two-engine alignment problem).
_MIN_OVERLAP_MS = 50

# If more than this fraction of the original job's total speech-time has zero
# overlap with any final cue, the two almost certainly don't correspond at all
# (wrong file, or a re-encode that shifted the timebase) — this repo has prior
# VFR/timebase bugs (media.fps_num/fps_den/is_vfr in schema.sql), so silently
# aligning garbage is worse than refusing. Measuring *matched coverage* rather
# than raw min/max span deliberately tolerates a normal edit that adds a title
# card or outro well past the last real token — that alone shouldn't look like
# a mismatch just because it stretches the final SRT's outer timestamp.
_MAX_UNMATCHED_MASS_FRAC = 0.5

# Tags these rows as flywheel-imported-from-NLE, distinct from web-editor saves,
# using the existing GAP-7 `reason` column — useful provenance, no schema change.
_REASON_TAG = "srt_reimport"


class TimebaseMismatch(Exception):
    """Raised when the final SRT's time range diverges too far from the
    original job's — almost always a paired-wrong-file or re-encode mistake."""


@dataclass
class AlignSummary:
    matched_original: int = 0
    matched_final: int = 0
    unmatched_original: int = 0
    unmatched_final: int = 0
    unmatched_final_texts: list[str] = field(default_factory=list)


@dataclass
class AlignmentResult:
    pairs: list[CorrectionPair]
    summary: AlignSummary


class _UnionFind:
    def __init__(self, n: int):
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _check_timebase(original: list[dict], overlap_pairs: list[tuple[int, int]]) -> None:
    """Refuse to align when most of the original job's speech-time finds no
    overlapping final cue at all — see _MAX_UNMATCHED_MASS_FRAC for why this is
    measured as matched coverage, not raw min/max span."""
    if not original:
        return
    matched_orig = {i for i, _j in overlap_pairs}
    total_ms = sum(t["end_ms"] - t["start_ms"] for t in original)
    if total_ms <= 0:
        return
    unmatched_ms = sum(
        original[i]["end_ms"] - original[i]["start_ms"]
        for i in range(len(original)) if i not in matched_orig
    )
    frac = unmatched_ms / total_ms
    if frac > _MAX_UNMATCHED_MASS_FRAC:
        raise TimebaseMismatch(
            f"{frac:.0%} of the original job's speech has no overlapping cue in "
            f"the final SRT — this usually means the .srt was exported against a "
            f"different source (wrong file, or a re-encode that changed the "
            f"timebase), not a normal edit. Check the pairing before retrying."
        )


def _find_overlapping_pairs(original: list[dict], final: list[dict]) -> list[tuple[int, int]]:
    """Two-pointer sweep over both sorted, non-overlapping-within-list interval
    sequences. Standard "intersect two sorted interval lists" algorithm — O(n+m),
    and correctly reports a merge/split (an interval matching more than one on
    the other side) because it only advances whichever pointer's interval ends
    first, keeping the other in play for the next comparison."""
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < len(original) and j < len(final):
        o, f = original[i], final[j]
        lo = max(o["start_ms"], f["start_ms"])
        hi = min(o["end_ms"], f["end_ms"])
        if hi - lo > _MIN_OVERLAP_MS:
            pairs.append((i, j))
        if o["end_ms"] < f["end_ms"]:
            i += 1
        elif f["end_ms"] < o["end_ms"]:
            j += 1
        else:
            i += 1
            j += 1
    return pairs


def _plurality_source_engine(group_original: list[dict]) -> str:
    """Most common source_engine among a merged group's original tokens; ties
    break toward whichever appears first in time order (stable, deterministic —
    not dict-iteration-order dependent)."""
    counts = Counter(t["source_engine"] for t in group_original)
    best_count = max(counts.values())
    for t in group_original:
        if counts[t["source_engine"]] == best_count:
            return t["source_engine"]
    return group_original[0]["source_engine"]  # unreachable, satisfies type-checkers


def align_tokens_to_cues(original_tokens: list[dict], final_cues: list[dict]) -> AlignmentResult:
    """Align an ASR job's original tokens against a hand-corrected final cue
    list (e.g. parsed from an NLE-exported .srt via transcribe.srt_io.parse_srt)
    and produce the CorrectionPairs a Premiere-style re-timed/re-cut pass implies.

    original_tokens: [{idx, text, start_ms, end_ms, source_engine}, ...]
    final_cues:      [{text, start_ms, end_ms}, ...]  (script key, if present, is ignored)
    """
    if not original_tokens:
        raise ValueError("no original tokens for this job — nothing to align against")

    original = sorted(original_tokens, key=lambda t: t["start_ms"])
    final = sorted(final_cues, key=lambda c: c["start_ms"])

    overlap_pairs = _find_overlapping_pairs(original, final)
    _check_timebase(original, overlap_pairs)

    n_orig, n_final = len(original), len(final)
    uf = _UnionFind(n_orig + n_final)
    for i, j in overlap_pairs:
        uf.union(i, n_orig + j)

    components: dict[int, dict[str, list[int]]] = {}
    for i in range(n_orig):
        root = uf.find(i)
        components.setdefault(root, {"orig": [], "final": []})["orig"].append(i)
    for j in range(n_final):
        root = uf.find(n_orig + j)
        components.setdefault(root, {"orig": [], "final": []})["final"].append(j)

    pairs: list[CorrectionPair] = []
    summary = AlignSummary()

    for comp in components.values():
        orig_idxs, final_idxs = comp["orig"], comp["final"]
        if not orig_idxs:
            # Pure insertion (e.g. a title card) — no source token to attribute
            # a correction to, so it is reported, not synthesized.
            for j in final_idxs:
                summary.unmatched_final += 1
                summary.unmatched_final_texts.append(final[j]["text"])
            continue

        group_original = [original[i] for i in orig_idxs]
        summary.matched_original += len(orig_idxs)
        if not final_idxs:
            summary.unmatched_original += len(orig_idxs)  # deletion
        else:
            summary.matched_final += len(final_idxs)

        raw_text = " ".join(t["text"] for t in group_original).strip()
        final_text = " ".join(final[j]["text"] for j in final_idxs).strip()
        if raw_text == final_text:
            continue  # no correction where nothing changed

        token_idx = min(t["idx"] for t in group_original)  # row-ownership: lowest idx owns the row
        pairs.append(CorrectionPair(
            token_idx=token_idx,
            raw_text=raw_text,
            corrected_text=final_text,
            source_engine=_plurality_source_engine(group_original),
            reason=_REASON_TAG,
            corrected_span=extract_changed_span(raw_text, final_text),
        ))

    return AlignmentResult(pairs=pairs, summary=summary)


def write_corrections(conn, job_id: int, pairs: list[CorrectionPair]) -> int:
    """Persist aligned CorrectionPairs via the existing correction-table path
    (same store function the web editor's /save endpoint uses)."""
    for pair in pairs:
        store.create_correction(
            conn,
            job_id=job_id,
            token_idx=pair.token_idx,
            raw_text=pair.raw_text,
            corrected_text=pair.corrected_text,
            source_engine=pair.source_engine,
            reason=pair.reason,
            corrected_span=pair.corrected_span,
        )
    return len(pairs)
