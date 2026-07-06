#!/usr/bin/env python3
"""preflight.py — verify the box can run single-engine Typhoon before you spend
time downloading weights. Checks GPU, faster-whisper, the converted model dir,
and that config.yaml points where it should. Exits non-zero on any blocker.

    python scripts/preflight.py --config transcribe/config.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="transcribe/config.yaml")
    args = ap.parse_args()

    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        mark = "OK " if passed else "FAIL"
        print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
        if not passed:
            ok = False

    # 1. torch + CUDA
    try:
        import torch
        cuda = torch.cuda.is_available()
        name = torch.cuda.get_device_name(0) if cuda else "CPU only"
        vram = (torch.cuda.get_device_properties(0).total_memory / 1e9) if cuda else 0
        check("CUDA GPU", cuda, f"{name} ({vram:.1f} GB)" if cuda else "no GPU — will be very slow")
    except Exception as e:
        check("torch import", False, str(e))

    # 2. faster-whisper
    try:
        import faster_whisper  # noqa: F401
        check("faster-whisper installed", True)
    except Exception as e:
        check("faster-whisper installed", False, f"{e} — pip install faster-whisper")

    # 3. config + model dir
    try:
        import yaml
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        check("config.yaml parses", True)
        eng = cfg.get("engine_a")
        check("engine_a set", bool(eng), str(eng))
        check("engine_b is passthrough (single-engine focus)",
              cfg.get("engine_b") == "passthrough", str(cfg.get("engine_b")))
        model_dir = cfg.get("engine_a_model")
        if model_dir:
            p = (Path(args.config).resolve().parents[1] / model_dir)
            exists = p.exists() and any(p.glob("model.bin"))
            check("converted model dir present", exists,
                  str(model_dir) if exists else f"{model_dir} missing — run convert_model.sh")
        else:
            check("engine_a_model set", False, "add engine_a_model to config.yaml")
    except Exception as e:
        check("config check", False, str(e))

    # 4. silero/pythainlp presence (warn-only, pipeline degrades gracefully)
    for mod, note in [("pythainlp", "Thai tokenization/normalization"),
                      ("librosa", "audio decode"),
                      ("av", "video container decode")]:
        try:
            __import__(mod)
            print(f"[OK ] {mod} ({note})")
        except Exception:
            print(f"[warn] {mod} missing ({note}) — recommended")

    print()
    print("READY" if ok else "NOT READY — fix FAIL lines above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
