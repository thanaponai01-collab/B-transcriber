"""Phase C step 1 — fine-tune data engine (HANDOFF_ONE_ENGINE.md Section 5 item 1).

Ingests (audio, hand-recut SRT) pairs — the Premiere recut-loop artifact — and
DB `correction` rows into a training-ready manifest of (audio slice, corrected
text) utterances for a future LoRA fine-tune of the Phase B winner
(`biodatlab/whisper-th-medium-combined`).

Mechanically enforces the gold-set contamination guard from
HANDOFF_ONE_ENGINE.md Section 3.4: the gold set is a TEST set, so no clip in
`transcribe/eval/goldenset/` — nor anything sharing its source video — may
enter training data. Every ingest call takes an explicit `--source` name and
refuses (raises `ContaminationError`, writes nothing) if that name matches a
row in `transcribe/eval/goldenset/SOURCES.md`.

    # ingest a hand-recut SRT against its source audio/video
    python -m tools.make_finetune_set from-srt path/to/clip.srt --audio path/to/clip.mp4 --source "some_video_name"

    # ingest DB correction rows whose source media is still on disk
    python -m tools.make_finetune_set from-corrections --db transcriber.db

    # check what's been collected against the Phase C training threshold
    python -m tools.make_finetune_set stats

This tool only builds the manifest + audio slices; it does not train anything
(HANDOFF_ONE_ENGINE.md Section 5 items 3-5 are separate, later work, gated on
this step producing enough data to be worth training on).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transcribe.subtitles import read_subtitles

_ROOT = Path(__file__).resolve().parents[1]
_GOLD_SOURCES = _ROOT / "transcribe" / "eval" / "goldenset" / "SOURCES.md"
_DATA_DIR = _ROOT / "transcribe" / "finetune" / "data"
_MANIFEST = _ROOT / "transcribe" / "finetune" / "manifest.jsonl"

# Data thresholds from HANDOFF_ONE_ENGINE.md Section 5 (arXiv 2604.06507 lineage):
# gains become reliably large past ~800 utterances, roughly 60-90 min at
# phrase-cue granularity. Below MIN_COLLECT_MINUTES, the handoff's instruction
# is "collect, don't train yet".
MIN_COLLECT_MINUTES = 45.0
TARGET_MINUTES = 60.0

_MIN_MATCH_LEN = 3  # skip contamination-check tokens too short to be meaningful


class ContaminationError(ValueError):
    """Raised when a training candidate's declared source matches a gold-set row."""


# ── contamination guard ────────────────────────────────────────────────────────

def load_gold_sources(sources_md: Path = _GOLD_SOURCES) -> list[dict]:
    """Parse the `| Gold clip | Source video | Status |` table in SOURCES.md."""
    rows: list[dict] = []
    if not sources_md.exists():
        return rows
    for line in sources_md.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        first = cells[0]
        if first == "Gold clip" or set(first) <= {"-"}:
            continue  # header or separator row
        rows.append({
            "gold_clip": first.strip("`"),
            "source_video": cells[1],
            "status": cells[2],
        })
    return rows


def _source_tokens(text: str) -> list[str]:
    """Backtick-quoted filename-like tokens from a SOURCES.md cell, stripped of extension."""
    tokens = []
    for t in re.findall(r"`([^`]+)`", text):
        tokens.append(t.strip().lower())
        tokens.append(re.sub(r"\.[a-z0-9]+$", "", t.strip().lower()))
    return tokens


def find_contamination(declared_source: str, gold_rows: list[dict] | None = None) -> dict | None:
    """Return the matching gold row if `declared_source` names (or is named by)
    a gold-set clip or its source video, else None.

    Case-insensitive substring match in both directions — the conservative
    default SOURCES.md itself prescribes ("assume distinct source... verify").
    """
    if gold_rows is None:
        gold_rows = load_gold_sources()
    needle = declared_source.strip().lower()
    if len(needle) < _MIN_MATCH_LEN:
        return None
    for row in gold_rows:
        bits = [row["gold_clip"].lower(), row["source_video"].lower()] + _source_tokens(row["source_video"])
        for bit in bits:
            bit = bit.strip()
            if len(bit) < _MIN_MATCH_LEN:
                continue
            if needle in bit or bit in needle:
                return row
    return None


def require_clean(declared_source: str, gold_rows: list[dict] | None = None) -> None:
    match = find_contamination(declared_source, gold_rows)
    if match is not None:
        raise ContaminationError(
            f"declared source {declared_source!r} matches gold-set row "
            f"{match['gold_clip']!r} (source video: {match['source_video']!r}) - "
            "refusing to add this to the fine-tune training set (HANDOFF_ONE_ENGINE.md Section 3.4)"
        )


# ── manifest I/O ────────────────────────────────────────────────────────────────

def _append_manifest(entries: list[dict], manifest: Path) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _read_manifest(manifest: Path) -> list[dict]:
    if not manifest.exists():
        return []
    lines = manifest.read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines if ln.strip()]


def _manifest_path(p: Path) -> str:
    """Path recorded in the manifest: relative to the repo root when possible
    (portable across machines/sessions), absolute otherwise (e.g. tests using
    a data_dir outside the repo)."""
    try:
        return str(p.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p.resolve()).replace("\\", "/")


def _slice_and_write(audio, sr: int, start_ms: int, end_ms: int, out_path: Path) -> int:
    """Slice [start_ms, end_ms) out of a decoded (samples, sr) pair and write a wav.
    Returns the slice duration in ms actually written."""
    import soundfile as sf
    start = max(0, int(start_ms / 1000 * sr))
    end = min(len(audio), int(end_ms / 1000 * sr))
    clip = audio[start:end]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), clip, sr)
    return int(len(clip) / sr * 1000)


# ── from-srt ────────────────────────────────────────────────────────────────────

def ingest_srt(
    srt_path: str,
    audio_path: str,
    source_name: str,
    manifest: Path = _MANIFEST,
    data_dir: Path = _DATA_DIR,
    min_cue_ms: int = 200,
) -> dict:
    """Ingest a hand-recut SRT + its source audio into the fine-tune manifest.

    Raises ContaminationError (writes nothing) if `source_name` matches a gold
    row. Returns {"n_utterances": int, "duration_ms": int}.
    """
    require_clean(source_name)
    from transcribe.pipeline.ingest import load_audio

    cues = read_subtitles(Path(srt_path).read_text(encoding="utf-8-sig"), "srt")
    audio, sr = load_audio(audio_path)

    stem = Path(srt_path).stem
    out_dir = data_dir / stem
    entries = []
    total_ms = 0
    for i, cue in enumerate(cues):
        text = cue["text"].strip()
        if not text or cue["end_ms"] - cue["start_ms"] < min_cue_ms:
            continue
        clip_path = out_dir / f"{i:04d}.wav"
        dur = _slice_and_write(audio, sr, cue["start_ms"], cue["end_ms"], clip_path)
        entries.append({
            "audio": _manifest_path(clip_path),
            "text": text,
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
            "duration_ms": dur,
            "source": source_name,
            "origin": "srt",
        })
        total_ms += dur
    _append_manifest(entries, manifest)
    return {"n_utterances": len(entries), "duration_ms": total_ms}


# ── from-corrections ─────────────────────────────────────────────────────────────

def ingest_corrections(
    db_path: str,
    manifest: Path = _MANIFEST,
    data_dir: Path = _DATA_DIR,
) -> dict:
    """Ingest DB `correction` rows whose source media is still readable on disk.

    Groups corrections by job -> media so the contamination check and the audio
    decode each happen once per source file. A job whose media filename matches
    a gold row is skipped entirely (counted, not raised — this path processes
    many jobs unattended and one contaminated job must not abort the rest).
    Returns {"n_utterances", "duration_ms", "n_skipped_contaminated", "n_skipped_missing_audio"}.
    """
    from transcribe.db import store
    from transcribe.pipeline.ingest import load_audio

    conn = store.connect(Path(db_path))
    gold_rows = load_gold_sources()
    corrections = store.get_all_corrections(conn)

    by_job: dict[int, list] = {}
    for c in corrections:
        by_job.setdefault(c.job_id, []).append(c)

    n_utt = 0
    total_ms = 0
    n_skipped_contam = 0
    n_skipped_missing = 0

    for job_id, job_corrections in by_job.items():
        job = store.get_job(conn, job_id)
        if job is None:
            continue
        media = store.get_media(conn, job.media_id)
        if media is None:
            continue
        source_name = Path(media.path).stem
        if find_contamination(source_name, gold_rows) is not None:
            n_skipped_contam += len(job_corrections)
            continue
        if not Path(media.path).exists():
            n_skipped_missing += len(job_corrections)
            continue

        audio, sr = load_audio(media.path)
        tokens_by_idx = {t.idx: t for t in store.get_tokens(conn, job_id)}
        entries = []
        for c in job_corrections:
            text = c.corrected_text.strip()
            if not text:
                continue  # a deletion correction — no text to train on
            token = tokens_by_idx.get(c.token_idx)
            if token is None:
                continue
            clip_path = data_dir / source_name / f"corr_{job_id}_{c.token_idx:04d}.wav"
            dur = _slice_and_write(audio, sr, token.start_ms, token.end_ms, clip_path)
            entries.append({
                "audio": _manifest_path(clip_path),
                "text": text,
                "start_ms": token.start_ms,
                "end_ms": token.end_ms,
                "duration_ms": dur,
                "source": source_name,
                "origin": "correction",
                "job_id": job_id,
                "token_idx": c.token_idx,
            })
            total_ms += dur
        _append_manifest(entries, manifest)
        n_utt += len(entries)

    conn.close()
    return {
        "n_utterances": n_utt,
        "duration_ms": total_ms,
        "n_skipped_contaminated": n_skipped_contam,
        "n_skipped_missing_audio": n_skipped_missing,
    }


# ── stats ─────────────────────────────────────────────────────────────────────

def compute_stats(manifest: Path = _MANIFEST) -> dict:
    entries = _read_manifest(manifest)
    total_ms = sum(e["duration_ms"] for e in entries)
    total_min = total_ms / 60_000
    by_source: dict[str, int] = {}
    for e in entries:
        by_source[e["source"]] = by_source.get(e["source"], 0) + e["duration_ms"]
    if total_min >= TARGET_MINUTES:
        verdict = "ready"
    elif total_min >= MIN_COLLECT_MINUTES:
        verdict = "usable-but-below-target"
    else:
        verdict = "keep-collecting"
    return {
        "n_utterances": len(entries),
        "total_minutes": round(total_min, 2),
        "by_source_minutes": {k: round(v / 60_000, 2) for k, v in by_source.items()},
        "verdict": verdict,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("from-srt", help="ingest a hand-recut SRT + its source audio/video")
    s.add_argument("srt")
    s.add_argument("--audio", required=True)
    s.add_argument("--source", required=True, help="declared source-video name (contamination check)")

    c = sub.add_parser("from-corrections", help="ingest DB correction rows with recoverable audio")
    c.add_argument("--db", default="transcriber.db")

    sub.add_parser("stats", help="report collected training-set size vs the Phase C threshold")

    args = ap.parse_args()

    if args.cmd == "from-srt":
        try:
            result = ingest_srt(args.srt, args.audio, args.source)
        except ContaminationError as e:
            print(f"[make_finetune_set] REFUSED: {e}")
            raise SystemExit(1)
        print(f"[make_finetune_set] +{result['n_utterances']} utterances, "
              f"{result['duration_ms'] / 60_000:.2f} min from {args.srt}")
    elif args.cmd == "from-corrections":
        result = ingest_corrections(args.db)
        print(f"[make_finetune_set] +{result['n_utterances']} utterances, "
              f"{result['duration_ms'] / 60_000:.2f} min from {args.db} corrections "
              f"(skipped {result['n_skipped_contaminated']} contaminated, "
              f"{result['n_skipped_missing_audio']} missing-audio)")
    elif args.cmd == "stats":
        stats = compute_stats()
        print(f"[make_finetune_set] {stats['n_utterances']} utterances, "
              f"{stats['total_minutes']} min total (verdict: {stats['verdict']})")
        for source, minutes in sorted(stats["by_source_minutes"].items()):
            print(f"  {source}: {minutes} min")


if __name__ == "__main__":
    main()
