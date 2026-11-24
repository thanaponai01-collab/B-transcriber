from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from transcribe.db import store
from transcribe.flywheel.diff import CorrectionPair, extract_changed_span

_MIN_OVERLAP_MS = 50

_MAX_UNMATCHED_MASS_FRAC = 0.5

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
    counts = Counter(t["source_engine"] for t in group_original)
    best_count = max(counts.values())
    for t in group_original:
        if counts[t["source_engine"]] == best_count:
            return t["source_engine"]
    return group_original[0]["source_engine"]


def align_tokens_to_cues(original_tokens: list[dict], final_cues: list[dict]) -> AlignmentResult:
    """Align an ASR job's original tokens against a hand-corrected final cue
    list (e.g. parsed from an NLE-exported .srt via transcribe.subtitles.read_subtitles)
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
            for j in final_idxs:
                summary.unmatched_final += 1
                summary.unmatched_final_texts.append(final[j]["text"])
            continue

        group_original = [original[i] for i in orig_idxs]
        summary.matched_original += len(orig_idxs)
        if not final_idxs:
            summary.unmatched_original += len(orig_idxs)
        else:
            summary.matched_final += len(final_idxs)

        raw_text = " ".join(t["text"] for t in group_original).strip()
        final_text = " ".join(final[j]["text"] for j in final_idxs).strip()
        if raw_text == final_text:
            continue

        token_idx = min(t["idx"] for t in group_original)
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
