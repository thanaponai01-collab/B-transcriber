"""One-command entry point: process an audio file, then open the editor to review it.

Usage:
    python transcribe_file.py path\\to\\audio.wav
    python transcribe_file.py path\\to\\audio.wav --no-editor
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "transcribe" / "config.yaml"
DB = ROOT / "transcriber.db"
EDITOR_HOST = "127.0.0.1"
EDITOR_PORT = 8000


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _start_editor() -> None:
    if _port_open(EDITOR_HOST, EDITOR_PORT):
        print(f"Editor already running on http://{EDITOR_HOST}:{EDITOR_PORT}")
        return
    # CREATE_NEW_CONSOLE is Windows-only; on other platforms it doesn't exist and
    # would raise AttributeError. Guard so the entry point runs anywhere.
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "transcribe.editor.server:app",
            "--host", EDITOR_HOST, "--port", str(EDITOR_PORT),
        ],
        cwd=ROOT,
        **popen_kwargs,
    )
    for _ in range(30):
        if _port_open(EDITOR_HOST, EDITOR_PORT):
            break
        time.sleep(0.5)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--no-editor", action="store_true", help="Skip opening the editor afterward")
    args = parser.parse_args()

    result = subprocess.run(
        [sys.executable, "-m", "transcribe.pipeline.run", args.audio,
         "--config", str(CONFIG), "--db", str(DB)],
        cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        sys.exit(result.returncode)

    job_id = None
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("JOB_ID="):
            job_id = line.split("=", 1)[1].strip()
            break
    if job_id:
        subprocess.run(
            [sys.executable, "scripts/export_job.py", job_id, "--db", str(DB)],
            cwd=ROOT,
        )

    if not args.no_editor:
        _start_editor()
        webbrowser.open(f"http://{EDITOR_HOST}:{EDITOR_PORT}")


if __name__ == "__main__":
    main()
