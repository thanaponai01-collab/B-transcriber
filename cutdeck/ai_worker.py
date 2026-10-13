"""Subprocess adapter the :7891 helper spawns for `transcribe` jobs."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from cutdeck.ai_backend import ROOT, write_json


def run(folder: Path) -> None:
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    args = job["arguments"]
    if job["kind"] == "transcribe":
        import yaml
        from transcribe.service import transcribe
        config = yaml.safe_load((ROOT / "transcribe/config.yaml").read_text(encoding="utf-8"))
        # The shared store (config store.path), not a per-job DB: bias terms, corrections
        # and the sha256 cache then reach ClubFriday too. The job folder keeps result.json.
        transcript = transcribe(args["media_path"], config=config)
        # transcript_job_id lets an editing client (ClubFriday) save corrections against it.
        result = {"kind": "transcribe", "media_path": args["media_path"],
                  "timing_unit": "milliseconds", "granularity": "phrase_cues",
                  "transcript_job_id": transcript.job_id, "cues": transcript.cues}
    else:
        raise ValueError("Unknown worker operation")
    write_json(folder / "result.json", result)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
