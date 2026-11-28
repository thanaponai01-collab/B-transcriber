"""Cut each judge clip and cache its Engine A output (Whisper words and cues, word_align off).

One GPU model at a time: clips run one after another, each job unloads before the next.
A clip whose cache exists is skipped, so trials downstream of Engine A never re-run Whisper."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).with_name("manifest.json")


def clip_dir(manifest: dict, clip: dict) -> Path:
    return Path(manifest["lockbox_dir"]) / "audio" if clip["split"] == "lockbox" else Path(manifest["cache"])


def wav_path(manifest: dict, clip: dict) -> Path:
    return clip_dir(manifest, clip) / f"{clip['name']}.wav"


def whisper_path(manifest: dict, clip: dict, tag: str = "") -> Path:
    return clip_dir(manifest, clip) / f"{clip['name']}{tag}.whisper.json"


def cut(manifest: dict, clip: dict) -> Path:
    wav = wav_path(manifest, clip)
    if not wav.exists():
        src = Path(clip["source"])
        src = src if src.is_absolute() else REPO / src
        if not src.exists():
            raise FileNotFoundError(f"{clip['name']}: source {src} missing")
        wav.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(clip["start_s"]), "-t", str(clip["dur_s"]),
                        "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    return wav


def engine_a(wav: Path, config: dict, out: Path, db: Path) -> None:
    """Run the pipeline with word_align off and keep Engine A's words and cues."""
    from transcribe.eval.timing import _run
    whisper_only = copy.deepcopy(config)
    whisper_only.setdefault("word_align", {})["enabled"] = False
    words, cues = _run(str(wav), whisper_only, db)
    out.write_text(json.dumps({"words": words, "cues": cues}, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=str(REPO / "transcribe" / "config.yaml"))
    p.add_argument("--tag", default="", help="cache suffix for an Engine A variant (e.g. .hpf)")
    p.add_argument("--only", nargs="*", help="clip names")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    for clip in manifest["clips"]:
        if args.only and clip["name"] not in args.only:
            continue
        out = whisper_path(manifest, clip, args.tag)
        if out.exists():
            continue
        wav = cut(manifest, clip)
        engine_a(wav, config, out, clip_dir(manifest, clip) / f"judge{args.tag}.db")
        print(f"{clip['name']}: cached {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
