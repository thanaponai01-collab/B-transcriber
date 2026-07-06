"""GAP-6 — gold-set authoring: draft → hand-correct → freeze round-trip.

    # draft from a corrected editor job (preferred: corrections also feed the flywheel)
    python -m tools.make_gold draft path/to/clip.wav --db transcriber.db --job-id 12
    # or draft by running the pipeline fresh
    python -m tools.make_gold draft path/to/clip.wav --run --config transcribe/config.yaml
    # human edits eval/goldenset/<clip>.draft.json, then:
    python -m tools.make_gold freeze eval/goldenset/<clip>.draft.json

The Typhoon benchmark finding (arXiv 2601.13044) is the motivation: their strict
normalization protocol was worth as much as *model scaling* on Thai CER, and inflated
baselines usually come from formatting mismatches, not recognition errors. The gold
set + a shared normalize.py is this system's version of that discipline — so this tool
validates gold *mechanics* only (schema, script tags, monotonic time). The policy
questions (loanword script choice, number verbalization) live in STYLE_GUIDE.md.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transcribe.contracts import detect_script

_GOLDENSET = Path(__file__).resolve().parents[1] / "transcribe" / "eval" / "goldenset"
_VALID_SCRIPTS = {"thai", "latin", "other", "mixed"}
_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a")


def _to_gold_token(t: dict) -> dict:
    return {
        "text": t["text"],
        "script": t.get("script") or detect_script(t["text"]),
        "start_ms": t["start_ms"],
        "end_ms": t.get("end_ms", t["start_ms"]),
    }


def write_draft(audio_path: str, tokens: list[dict], goldenset: Path = _GOLDENSET) -> Path:
    """Copy the audio into the gold set and write a <stem>.draft.json beside it."""
    goldenset.mkdir(parents=True, exist_ok=True)
    src = Path(audio_path)
    stem = src.stem
    dst_audio = goldenset / (stem + src.suffix.lower())
    if src.resolve() != dst_audio.resolve():
        shutil.copyfile(src, dst_audio)
    draft = goldenset / (stem + ".draft.json")
    draft.write_text(
        json.dumps({"tokens": [_to_gold_token(t) for t in tokens]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return draft


def validate(tokens: list[dict]) -> list[str]:
    """Mechanics only: text/script/start_ms present, script matches detect_script,
    timestamps monotonic non-decreasing. Returns a list of error strings ([] = ok)."""
    errs: list[str] = []
    prev = -1
    for i, t in enumerate(tokens):
        text = t.get("text")
        if not text:
            errs.append(f"token {i}: missing/empty text")
            continue
        if "start_ms" not in t:
            errs.append(f"token {i}: missing start_ms")
        sc = t.get("script")
        if sc not in _VALID_SCRIPTS:
            errs.append(f"token {i}: invalid script {sc!r}")
        elif sc != detect_script(text):
            errs.append(f"token {i}: script {sc!r} != detect_script {detect_script(text)!r} for {text!r}")
        start = t.get("start_ms", prev)
        if start < prev:
            errs.append(f"token {i}: start_ms {start} < previous {prev} (not monotonic)")
        prev = start
    return errs


def freeze(draft_path: str, force: bool = False) -> Path:
    """Validate a .draft.json and promote it to the frozen <stem>.json."""
    draft = Path(draft_path)
    if not draft.name.endswith(".draft.json"):
        raise ValueError(f"not a draft file: {draft.name} (expected <stem>.draft.json)")
    data = json.loads(draft.read_text(encoding="utf-8"))
    errs = validate(data.get("tokens", []))
    if errs:
        raise ValueError("gold validation failed:\n  " + "\n  ".join(errs))
    frozen = draft.with_name(draft.name[: -len(".draft.json")] + ".json")
    if frozen.exists() and not force:
        raise FileExistsError(f"{frozen.name} already frozen — pass --force to overwrite")
    draft.replace(frozen)  # replace (not rename): overwrites on Windows too when --force
    return frozen


def _tokens_from_job(db: str, job_id: int) -> list[dict]:
    from transcribe.db import store
    conn = store.connect(Path(db))
    tokens = [{"text": t.text, "script": t.script, "start_ms": t.start_ms, "end_ms": t.end_ms}
              for t in store.get_tokens(conn, job_id)]
    conn.close()
    return tokens


def _tokens_from_pipeline(audio_path: str, config_path: str) -> list[dict]:
    import tempfile, yaml
    from transcribe.db import store
    from transcribe.pipeline import run as pipeline_run
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    scratch = Path(tempfile.mkdtemp(prefix="make_gold_")) / "scratch.db"
    store.init_db(scratch)
    return pipeline_run.run_file(audio_path, cfg, scratch)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("draft", help="write a <stem>.draft.json for hand-correction")
    d.add_argument("audio")
    d.add_argument("--db", help="pull corrected tokens from this DB (with --job-id)")
    d.add_argument("--job-id", type=int, help="job to export (editor/corrected path)")
    d.add_argument("--run", action="store_true", help="run the pipeline fresh instead")
    d.add_argument("--config", default="transcribe/config.yaml")

    f = sub.add_parser("freeze", help="validate + promote a draft to a frozen gold file")
    f.add_argument("draft")
    f.add_argument("--force", action="store_true", help="overwrite an existing frozen file")

    args = ap.parse_args()

    if args.cmd == "draft":
        if args.job_id is not None:
            if not args.db:
                ap.error("--job-id requires --db")
            tokens = _tokens_from_job(args.db, args.job_id)
        elif args.run:
            tokens = _tokens_from_pipeline(args.audio, args.config)
        else:
            ap.error("choose a source: --job-id (with --db) or --run")
        out = write_draft(args.audio, tokens)
        print(f"[make_gold] wrote {out} ({len(tokens)} tokens) — hand-correct, then `freeze`.")
    elif args.cmd == "freeze":
        frozen = freeze(args.draft, force=args.force)
        print(f"[make_gold] froze {frozen.name} — run_harness will now consume it.")


if __name__ == "__main__":
    main()
