"""Subprocess adapter: reuse the existing pipelines without changing their rules."""
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
    elif job["kind"] == "rough_cut_xml":
        from cutdeck.xml_recut import main
        output = folder / "rough_cut.xml"
        report = folder / "report.json"
        command = [args["sequence_xml"], "--out", str(output), "--report", str(report),
                   "--config", str(ROOT / "transcribe/config.yaml"),
                   "--db", str(database), "--no-save-plan"]
        if args["preset"] == "aggressive":
            command += ["--overlay", str(ROOT / "transcribe/config.aggressive_cut.yaml")]
        if args["speech_protection"]:
            command.append("--asr")
        if args["audio_track"] is not None:
            command += ["--audio-track", str(args["audio_track"])]
        if args["start_frame"] is not None:
            command += ["--range-start-frame", str(args["start_frame"]),
                        "--range-end-frame", str(args["end_frame"])]
        if main(command) != 0:
            raise RuntimeError("Rough cut did not complete")
        result = {"kind": "rough_cut_xml", "output_path": str(output),
                  "report": json.loads(report.read_text(encoding="utf-8")),
                  "import_required": True}
    else:
        raise ValueError("Unknown worker operation")
    write_json(folder / "result.json", result)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
