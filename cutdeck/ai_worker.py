"""Subprocess adapter the :7891 helper spawns for `transcribe` jobs."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from cutdeck.ai_backend import ROOT, write_json


def run(folder: Path) -> None:
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    args = job["arguments"]
    from transcribe.db import store
    database = folder / "transcribe.db"
    store.init_db(database)
    if job["kind"] == "transcribe":
        import yaml
        from transcribe.pipeline.run import run_file
        config = yaml.safe_load((ROOT / "transcribe/config.yaml").read_text(encoding="utf-8"))
        cues = run_file(args["media_path"], config, database)
        result = {"kind": "transcribe", "media_path": args["media_path"],
                  "timing_unit": "milliseconds", "granularity": "phrase_cues", "cues": cues}
    else:
        raise ValueError("Unknown worker operation")
    write_json(folder / "result.json", result)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
