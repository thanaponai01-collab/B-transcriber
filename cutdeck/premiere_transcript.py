"""Premiere Pro clip transcript JSON from a finished job.

Premiere's own speech-to-text has no Thai (docs/PREMIERE_FACTS.md "Premiere transcript
import"), so CutDeck hands Premiere our transcript through the public import path:
``Transcript.importFromJSON`` + ``Transcript.createImportTextSegmentsAction``. The format is
Adobe's ``reference/adobe/samples/sample-panels/premiere-api/assets/transcript_format_spec.json``:
times in seconds from the start of the source media, one segment per phrase cue (the token
table), the real Thai words of each cue from ``cutdeck.words.words_for_job``.
"""
from __future__ import annotations

import bisect
import json
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

from cutdeck.words import Word, words_for_job

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "reference/adobe/samples/sample-panels/premiere-api/assets/transcript_format_spec.json"
LANGUAGE = "th-th"
# token.speaker_id is null until diarization (v2), so every segment has this one speaker.
# A fixed version-4 UUID keeps exports of the same job byte-identical.
SPEAKER_ID = "3f2b8c1e-6d4a-4b7e-9a1c-5e8d2f0b7c64"
SPEAKER_NAME = "Speaker 1"


def _seconds(ms: int) -> float:
    return round(ms / 1000, 3)


def _is_punctuation(text: str) -> bool:
    return all(unicodedata.category(ch).startswith("P") for ch in text)


def build_transcript(cues: Iterable, words: list[Word],
                     filler_lexicon: Iterable[str] = ()) -> dict:
    """``cues`` have ``text``/``start_ms``/``end_ms`` attributes (``store.TokenRow``).

    Each word joins the cue holding its midpoint (the nearest cue when none does). A cue no
    word landed in becomes one word, so its text is never lost; with no word timeline at all
    (an engine that never filled ``raw["words"]``) every cue is one word. Words are then made
    non-overlapping: faster-whisper's word list overlaps its neighbour now and then, and a
    transcript word must not start before the previous one ends.
    """
    cues = sorted(cues, key=lambda c: (c.start_ms, c.end_ms))
    if not cues:
        raise ValueError("This job has no transcript cues to export.")
    fillers = {f.strip() for f in filler_lexicon}
    starts = [c.start_ms for c in cues]
    groups: list[list[Word]] = [[] for _ in cues]
    for w in sorted(words, key=lambda w: (w.start_ms, w.end_ms)):
        mid = (w.start_ms + w.end_ms) / 2
        i = max(bisect.bisect_right(starts, mid) - 1, 0)
        if not mid < cues[i].end_ms and i + 1 < len(cues) and \
                cues[i + 1].start_ms - mid < mid - cues[i].end_ms:
            i += 1
        groups[i].append(w)

    segments = []
    prev_end = 0
    for cue, group in zip(cues, groups):
        if not group:
            group = [Word(cue.text.strip(), cue.start_ms, cue.end_ms, getattr(cue, "confidence", None))]
        out = []
        for w in group:
            start = max(w.start_ms, prev_end)
            end = max(w.end_ms, start)
            prev_end = end
            text = w.text.strip()
            conf = 1.0 if w.confidence is None else min(max(w.confidence, 0.0), 1.0)
            out.append({
                "confidence": round(conf, 4),
                "duration": _seconds(end - start),
                "eos": False,
                "start": _seconds(start),
                "tags": ["filler"] if text in fillers else [],
                "text": text,
                "type": "punctuation" if _is_punctuation(text) else "word",
            })
        out[-1]["eos"] = True
        first, last = out[0]["start"], out[-1]["start"] + out[-1]["duration"]
        segments.append({
            "duration": round(last - first, 3),
            "language": LANGUAGE,
            "speaker": SPEAKER_ID,
            "start": first,
            "words": out,
        })
    return {"language": LANGUAGE, "segments": segments,
            "speakers": [{"id": SPEAKER_ID, "name": SPEAKER_NAME}]}


def transcript_for_job(conn, job_id: int, filler_lexicon: Iterable[str] = ()) -> dict:
    from transcribe.db import store
    return build_transcript(store.get_tokens(conn, job_id), words_for_job(conn, job_id),
                            filler_lexicon)


def media_duration_s(conn, job_id: int) -> Optional[float]:
    from transcribe.db import store
    job = store.get_job(conn, job_id)
    media = store.get_media(conn, job.media_id) if job else None
    return media.duration_ms / 1000 if media and media.duration_ms else None


def validate(doc: dict, duration_s: Optional[float] = None) -> None:
    """Raise ValueError unless ``doc`` is a transcript Premiere can take.

    Adobe's JSON schema, plus what the schema cannot say: words in time order without
    overlap, each inside its segment, and nothing past the end of the media (which is what
    milliseconds written as seconds would do).
    """
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Transcript does not match Adobe's schema: {exc.message}") from None
    eps = 1e-6
    prev_end = 0.0
    for i, seg in enumerate(doc["segments"]):
        seg_end = seg["start"] + seg["duration"]
        for w in seg["words"]:
            end = w["start"] + w["duration"]
            if w["start"] < prev_end - eps:
                raise ValueError(f"Segment {i}: word {w['text']!r} at {w['start']} s overlaps "
                                 f"the previous word ending at {prev_end} s")
            if w["start"] < seg["start"] - eps or end > seg_end + eps:
                raise ValueError(f"Segment {i}: word {w['text']!r} lies outside its segment")
            prev_end = end
    if duration_s is not None and prev_end > duration_s + 0.5:
        raise ValueError(f"Transcript ends at {prev_end} s, past the media's {duration_s} s; "
                         "times must be seconds")


def export(transcript_job_id: int, config: dict, out_path: Path) -> dict:
    """The helper's `premiere_transcript` answer: the checked JSON text, also saved to
    ``out_path`` as the record. Fillers are tagged from ``cut.filler_lexicon`` (the
    always-safe list; the contextual list needs silence around the word, not tagged here)."""
    from cutdeck.contracts import CutConfig
    from transcribe.db import store
    conn = store.connect(store.resolve_db_path(config))
    try:
        doc = transcript_for_job(conn, transcript_job_id, CutConfig.from_yaml(config).filler_lexicon)
        validate(doc, media_duration_s(conn, transcript_job_id))
    finally:
        conn.close()
    text = json.dumps(doc, ensure_ascii=False)
    out_path.write_text(text, encoding="utf-8")
    return {"transcript": text, "path": str(out_path), "segments": len(doc["segments"]),
            "words": sum(len(s["words"]) for s in doc["segments"])}
