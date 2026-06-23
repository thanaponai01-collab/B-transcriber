#!/usr/bin/env python3
"""make_gold.py — author the frozen evaluation gold set.

The gold set is the single most important asset in this project: without it,
"Typhoon is better" is a vendor claim, not a measurement. This tool produces
gold references the RIGHT way — engine drafts the text, human corrects it — and
writes the exact JSON shape transcribe/eval/harness.py consumes.

WORKFLOW (three commands, in order)
-----------------------------------
1. DRAFT   Run the configured single engine over a short clip and emit an
           editable .draft.json + a human-friendly .draft.txt side by side.

               python scripts/make_gold.py draft clip.wav --config transcribe/config.yaml

2. (you)   Open clip.draft.txt, fix every error by hand against the audio.
           Keep one cue per line, do NOT touch the timing markers. This is the
           only slow step and it is the whole point — your corrections ARE the
           ground truth.

3. FREEZE  Convert your corrected .draft.txt back into the frozen reference and
           drop it (plus a copy of the audio) into eval/goldenset/.

               python scripts/make_gold.py freeze clip --config transcribe/config.yaml

           After freezing, NEVER edit the file again. A moving reference makes
           every CER comparison meaningless.

GOLD JSON SHAPE (what the harness reads)
----------------------------------------
    {
      "source": "clip.wav",
      "frozen": true,
      "tokens": [
        {"text": "...", "script": "thai|latin|mixed|other",
         "start_ms": 0, "end_ms": 1234},
        ...
      ]
    }

The .draft.txt line format round-trips losslessly:

    [0:00.000 -> 0:01.234] สวัสดีครับ

Edit only the text after the ']'. Timing is carried straight through from the
engine draft — gold timing need not be frame-perfect; cer_thai and wer_latin do
not use it, and boundary_error_rate only needs switch points roughly right.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# --- make the transcribe package importable when run from repo root ----------
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LINE_RE = re.compile(r"^\[(\d+):(\d{2})\.(\d{3})\s*->\s*(\d+):(\d{2})\.(\d{3})\]\s?(.*)$")


def _ms(m: int, s: int, ms: int) -> int:
    return (m * 60 + s) * 1000 + ms


def _fmt(t_ms: int) -> str:
    m, rem = divmod(int(t_ms), 60_000)
    s, ms = divmod(rem, 1000)
    return f"{m}:{s:02d}.{ms:03d}"


def _load_config(path: str) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# draft: engine → editable files
# ---------------------------------------------------------------------------
def cmd_draft(args) -> None:
    from transcribe.contracts import detect_script
    from transcribe.engines.registry import get_engine
    from transcribe.pipeline import ingest as ingest_mod

    config = _load_config(args.config)
    audio_path = Path(args.audio)
    if not audio_path.exists():
        sys.exit(f"audio not found: {audio_path}")

    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"

    engine_name = config["engine_a"]
    model_id = config.get("engine_a_model")
    kwargs = {"device": device}
    if model_id:
        kwargs["model_id"] = model_id
    if config.get("compute_type"):
        kwargs["compute_type"] = config["compute_type"]

    try:
        engine = get_engine(engine_name, **kwargs)
    except TypeError:
        try:
            engine = get_engine(engine_name, device=device)
        except TypeError:
            engine = get_engine(engine_name)  # mock/passthrough take no kwargs

    print(f"[draft] engine={engine_name} model={model_id or '(default)'} device={device}")
    print(f"[draft] transcribing {audio_path.name} ...")

    from transcribe.contracts import EngineInput
    audio, _sr = ingest_mod.load_audio(str(audio_path))
    engine.load()
    try:
        result = engine.transcribe(EngineInput(
            audio_path=str(audio_path), audio=audio,
            bias_terms=[], language_hint="th",
        ))
    finally:
        engine.unload()

    tokens = [
        {
            "text": t.text,
            "script": t.script or detect_script(t.text),
            "start_ms": int(t.start_ms),
            "end_ms": int(t.end_ms),
        }
        for t in result.tokens
    ]

    stem = audio_path.with_suffix("")
    draft_json = Path(f"{stem}.draft.json")
    draft_txt = Path(f"{stem}.draft.txt")

    draft_json.write_text(
        json.dumps({"source": audio_path.name, "frozen": False, "tokens": tokens},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Correct the text after each ']' against the audio. One cue per line.",
        "# Do NOT change the timing markers. Blank a line to delete that cue.",
        "#",
    ]
    for t in tokens:
        lines.append(f"[{_fmt(t['start_ms'])} -> {_fmt(t['end_ms'])}] {t['text']}")
    draft_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[draft] wrote {draft_txt}  ({len(tokens)} cues)")
    print(f"[draft] wrote {draft_json}")
    print("[draft] NEXT: hand-correct the .draft.txt, then run 'freeze'.")


# ---------------------------------------------------------------------------
# freeze: corrected text → frozen gold reference in eval/goldenset/
# ---------------------------------------------------------------------------
def cmd_freeze(args) -> None:
    from transcribe.contracts import detect_script

    stem = Path(args.stem)
    # accept either "clip" or "clip.draft" or a path
    base = stem.name.replace(".draft", "")
    src_dir = stem.parent if stem.parent != Path("") else Path(".")
    draft_txt = src_dir / f"{base}.draft.txt"
    if not draft_txt.exists():
        sys.exit(f"corrected draft not found: {draft_txt}")

    # locate the audio that was drafted
    audio = None
    for ext in (".wav", ".mp3", ".flac", ".m4a"):
        cand = src_dir / f"{base}{ext}"
        if cand.exists():
            audio = cand
            break
    if audio is None:
        sys.exit(f"no audio ({base}.wav/.mp3/.flac/.m4a) next to the draft")

    tokens = []
    for raw in draft_txt.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            sys.exit(f"unparseable line (fix or delete it):\n  {line}")
        sm, ss, sms, em, es, ems, text = m.groups()
        text = text.strip()
        if not text:  # blanked → deleted cue
            continue
        tokens.append({
            "text": text,
            "script": detect_script(text),
            "start_ms": _ms(int(sm), int(ss), int(sms)),
            "end_ms": _ms(int(em), int(es), int(ems)),
        })

    if not tokens:
        sys.exit("no cues survived — refusing to write an empty gold file")

    gold_dir = REPO_ROOT / "transcribe" / "eval" / "goldenset"
    gold_dir.mkdir(parents=True, exist_ok=True)

    gold_json = gold_dir / f"{base}.json"
    if gold_json.exists() and not args.overwrite:
        sys.exit(f"{gold_json} already exists — a frozen gold file must not be "
                 f"edited. Pass --overwrite only if you are deliberately "
                 f"replacing it (and know it invalidates past eval baselines).")

    gold_json.write_text(
        json.dumps({"source": audio.name, "frozen": True, "tokens": tokens},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    gold_audio = gold_dir / audio.name
    if not gold_audio.exists() or args.overwrite:
        shutil.copy2(audio, gold_audio)

    thai_chars = sum(len(t["text"]) for t in tokens if t["script"] in ("thai", "mixed"))
    print(f"[freeze] wrote {gold_json}")
    print(f"[freeze] copied {gold_audio.name}")
    print(f"[freeze] {len(tokens)} cues, ~{thai_chars} Thai chars frozen.")
    print("[freeze] This file is now the reference. Do NOT edit it again.")


def main() -> None:
    p = argparse.ArgumentParser(description="Author the frozen evaluation gold set.")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("draft", help="engine → editable draft files")
    d.add_argument("audio")
    d.add_argument("--config", default="transcribe/config.yaml")
    d.set_defaults(func=cmd_draft)

    f = sub.add_parser("freeze", help="corrected draft → frozen gold reference")
    f.add_argument("stem", help="clip name (e.g. 'clip' for clip.draft.txt)")
    f.add_argument("--config", default="transcribe/config.yaml")
    f.add_argument("--overwrite", action="store_true",
                   help="replace an existing frozen gold file (invalidates baselines)")
    f.set_defaults(func=cmd_freeze)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
