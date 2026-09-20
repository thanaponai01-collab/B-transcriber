"""Targeted acoustic review, separate from transcription and caption layout.

Flags are review priorities, not proof of errors. Alternatives always cover
the complete contextual window and are never assigned invented word timings.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import re

from transcribe.contracts import EngineInput


@dataclass(frozen=True)
class ReviewWindow:
    start_ms: int
    end_ms: int
    cue_indices: tuple[int, ...]
    reasons: tuple[str, ...]
    priority: int


def suspicion_reasons(cue: dict) -> list[str]:
    from pythainlp.corpus import thai_words
    from pythainlp.tokenize import word_tokenize

    text = cue['text']
    duration = cue['end_ms'] - cue['start_ms']
    reasons = []
    if duration < 500:
        reasons.append('caption shorter than 500ms')
    if len(re.sub(r'\s', '', text)) / max(duration / 1000, .001) > 25:
        reasons.append('dense text for available speech time')
    confidence = cue.get('confidence')
    if confidence is not None and confidence < .8:
        reasons.append('low recognition confidence')
    known = thai_words()
    unknown = [t for t in word_tokenize(text, keep_whitespace=False)
               if re.fullmatch(r'[ก-๛]+', t) and t not in known and t != 'ๆ']
    if unknown:
        reasons.append('unfamiliar Thai fragments: ' + ', '.join(dict.fromkeys(unknown)))
    return reasons


def plan_windows(cues: list[dict], duration_ms: int, *, requested=(),
                 context_ms: int = 1500, max_window_ms: int = 12000,
                 max_windows: int = 6) -> list[ReviewWindow]:
    """Rank flags and expand to whole neighboring cues within a bounded budget.

    Requested ranges outrank automatic flags. No human reference is accepted.
    Overlapping requests share one window when the merged span fits the limit.
    """
    if duration_ms <= 0 or max_windows < 1 or max_window_ms <= 0 or context_ms < 0:
        raise ValueError('Invalid review duration or budget')
    candidates = []
    for i, cue in enumerate(cues):
        if not 0 <= cue['start_ms'] < cue['end_ms'] <= duration_ms:
            raise ValueError('Cue timestamps must be inside the audio')
        if i and cue['start_ms'] < cues[i - 1]['start_ms']:
            raise ValueError('Cues must be time ordered')
        reasons = suspicion_reasons(cue)
        if reasons:
            candidates.append((cue['start_ms'], cue['end_ms'], reasons, len(reasons)))
    for start, end in requested:
        if not 0 <= start < end <= duration_ms:
            raise ValueError('Requested passage must be inside the audio')
        candidates.append((start, end, ['requested passage'], 100))

    selected = []
    for start, end, reasons, priority in sorted(candidates, key=lambda x: (-x[3], x[0])):
        hits = [i for i, c in enumerate(cues) if c['start_ms'] < end and c['end_ms'] > start]
        if hits:
            start = min(start, cues[hits[0]]['start_ms'])
            end = max(end, cues[hits[-1]]['end_ms'])
        if end - start > max_window_ms:
            if priority == 100:
                raise ValueError('Requested passage is too long; choose a smaller cue range')
            continue
        # Add complete neighbor cues, avoiding cuts through words at context edges.
        lo, hi = max(0, start - context_ms), min(duration_ms, end + context_ms)
        neighbors = [i for i, c in enumerate(cues)
                     if c['start_ms'] < hi and c['end_ms'] > lo]
        if neighbors:
            expanded_start = min(start, cues[neighbors[0]]['start_ms'])
            expanded_end = max(end, cues[neighbors[-1]]['end_ms'])
            if expanded_end - expanded_start <= max_window_ms:
                start, end = expanded_start, expanded_end
        indices = tuple(i for i, c in enumerate(cues)
                        if c['start_ms'] < end and c['end_ms'] > start)
        candidate = ReviewWindow(start, end, indices, tuple(reasons), priority)
        merged = False
        for j, prev in enumerate(selected):
            if start < prev.end_ms and end > prev.start_ms:
                left, right = min(start, prev.start_ms), max(end, prev.end_ms)
                if right - left <= max_window_ms:
                    selected[j] = ReviewWindow(left, right,
                        tuple(sorted(set(indices + prev.cue_indices))),
                        tuple(dict.fromkeys(prev.reasons + tuple(reasons))), max(priority, prev.priority))
                    merged = True
                    break
                # A fully covered flag needs no second decode.
                if prev.start_ms <= start and end <= prev.end_ms:
                    merged = True
                    break
        if not merged and len(selected) < max_windows:
            selected.append(candidate)
    for start, end in requested:
        if not any(w.start_ms <= start and w.end_ms >= end for w in selected):
            raise ValueError('Review budget cannot cover all requested passages; increase max_windows')
    return sorted(selected, key=lambda w: w.start_ms)


def recheck_windows(audio, windows: list[ReviewWindow], *, engine_factory,
                    engines=('faster_whisper', 'qwen3_asr')) -> list[dict]:
    """Decode the exact same 16kHz samples sequentially through each engine.

    Caller owns factory configuration and artifact storage. No DB writes,
    reference prompts, automatic selection, or cross-engine confidence scores.
    """
    if not windows:
        return []
    if any(not 0 <= w.start_ms < w.end_ms <= len(audio) // 16 for w in windows):
        raise ValueError('Review window outside audio bounds')
    proposals = [{**asdict(w), 'alternatives': {}, 'candidate_tokens': {},
                  'status': 'needs_review'} for w in windows]
    for name in engines:
        engine = engine_factory(name)
        try:
            engine.load()
            for window, proposal in zip(windows, proposals):
                excerpt = audio[window.start_ms * 16:window.end_ms * 16].copy()
                if not len(excerpt):
                    raise ValueError('Empty review audio window')
                result = engine.transcribe(EngineInput(audio=excerpt, language_hint='th'))
                # These adapters return phrase cues. Separate them for display
                # so adjacent English words cannot silently fuse at cue edges.
                proposal['alternatives'][name] = ' '.join(t.text.strip() for t in result.tokens if t.text.strip())
                proposal['candidate_tokens'][name] = [
                    {**asdict(t), 'start_ms': t.start_ms + window.start_ms,
                     'end_ms': t.end_ms + window.start_ms}
                    for t in result.tokens]
        finally:
            engine.unload()
    for proposal in proposals:
        texts = list(proposal['alternatives'].values())
        compact = [re.sub(r'\s+', '', t) for t in texts]
        proposal['engines_agree'] = len(compact) > 1 and bool(compact[0]) and len(set(compact)) == 1
        proposal['disagreement'] = (1 - SequenceMatcher(None, compact[0], compact[1], autojunk=False).ratio()
                                    if len(compact) > 1 else None)
    return proposals
