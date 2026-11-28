"""Drive live CutDeck in Premiere for verification, and keep the evidence.

    python .claude/skills/verify-cutdeck/scripts/cdv.py <step> [...]

Steps (see ../SKILL.md): launch, doctor, start, scratch, call, shot, cleanup.
State of the current run: output/verify-cutdeck/current.json. Evidence of each run:
output/verify-cutdeck/runs/<run_id>/ (never deleted by cleanup). Exit code 0 means the step
passed; anything else prints why on stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from cutdeck.helper_protocol import PORT, VERSION, ask, exchange  # noqa: E402

ROOT = REPO / "output" / "verify-cutdeck"
STATE = ROOT / "current.json"
MEDIA = ROOT / "media" / "verify-clip-1080x1920-30fps.mp4"
SCRATCH = "CutDeck verify (scratch)"
PRESET = Path("C:/Program Files/Adobe/Adobe Premiere Pro 2027/Settings/SequencePresets/Social/"
              "Social Media Portrait 9x16 30 fps.sqpreset")
UDT_WORKSPACE = Path(os.environ.get("APPDATA", "")) / "Adobe" / "Adobe UXP Developer Tool" / "plugins_workspace.json"


def fail(message: str) -> None:
    print(f"FAIL  {message}", file=sys.stderr)
    raise SystemExit(1)


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(state: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def run_dir(state: dict) -> Path:
    if not state.get("run_id"):
        fail("no run started: run `cdv.py start` first")
    return ROOT / "runs" / state["run_id"]


def premiere(command: str, args: dict | None = None):
    return ask({"type": "premiere", "command": command, "args": args or {}})["result"]


def helper_hello() -> dict | None:
    """The helper's hello reply ({version, pid}), or None when nothing answers on the port."""
    try:
        return exchange([{"type": "hello", "version": VERSION}], open_timeout=3, check=False)
    except Exception:
        return None


def process_started(pid: int) -> float | None:
    """Epoch seconds the process started (Windows), or None."""
    import ctypes
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [ctypes.c_ulonglong() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        return times[0].value / 1e7 - 11644473600  # FILETIME (1601) -> Unix epoch
    finally:
        k32.CloseHandle(handle)


def newest_python_change() -> float:
    return max(p.stat().st_mtime for p in (REPO / "cutdeck").rglob("*.py"))


def wait_for_panel(timeout_s: float = 60) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status = ask({"type": "premiere_status"})
            if status.get("connected"):
                return status
        except Exception:
            pass
        time.sleep(2)
    fail(f"the CutDeck panel did not connect to the helper within {timeout_s:.0f} s: open it in Premiere "
         "(Window > UXP Plugins > CutDeck), or load it in UXP Developer Tool")


# --- steps ---------------------------------------------------------------------------------------

def cmd_launch(args) -> None:
    """Make the stack drivable: a helper on this checkout's code, the panel connected, and with
    --reload-panel the panel reloaded on this checkout's code (the project is saved first)."""
    import subprocess  # here and below, not at import: `call` is one process per command and needs none of it
    from cutdeck import live_check
    if not live_check.premiere_running():
        fail("Premiere Pro is not running: start it and open a project (an agent never opens or closes projects)")
    hello = helper_hello()
    state = load_state()
    if hello and hello.get("ok") is False and hello.get("code") == "version_mismatch":
        fail(f"an older helper (pid {hello.get('pid')}) holds port {PORT}: run `cdv.py launch --restart-helper`")
    if hello and args.restart_helper:
        # The helper restarts in place: it starts its own successor on this checkout's code
        # (observed: the new helper's parent is the old one), so never start a second one here.
        _restart_request()
        for _ in range(60):
            time.sleep(0.5)
            new = helper_hello()
            if new and new.get("pid") and new["pid"] != hello["pid"]:
                print(f"PASS  helper restarted in place: pid {hello['pid']} -> {new['pid']}")
                hello = new
                break
        else:
            fail(f"no new helper answered on {PORT} after restarting pid {hello['pid']}; run `cdv.py launch`")
    if not hello:
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        log = (ROOT / "helper.log").open("ab")
        proc = subprocess.Popen([sys.executable, "-m", "cutdeck.helper", "--port", str(PORT),
                                 "--jobs-dir", str(REPO / "output" / "premiere")],
                                cwd=REPO, stdout=log, stderr=log, creationflags=flags)
        for _ in range(30):
            hello = helper_hello()
            if hello:
                break
            time.sleep(0.5)
        else:
            fail(f"the helper did not answer on {PORT}; see {ROOT / 'helper.log'}")
        if hello.get("pid") == proc.pid:
            state["helper_pid_started"] = proc.pid  # cleanup stops only this one
            save_state(state)
            print(f"PASS  started helper pid {proc.pid} (log {ROOT / 'helper.log'})")
        else:  # the panel launched its own helper first; ours lost the port and exited
            print(f"PASS  helper pid {hello.get('pid')} answers (not started by this run)")
    else:
        print(f"PASS  helper already running, pid {hello.get('pid')}")
    status = wait_for_panel()
    print(f"PASS  panel connected, {len(status['commands'])} panel commands")
    if args.reload_panel:
        print("      saving the project before reloading the panel:", premiere("save_project")["saved"])
        premiere("reload_panel")
        time.sleep(4)
        status = wait_for_panel()
        print(f"PASS  panel reloaded on {REPO / 'uxp' / 'cutdeck'}, {len(status['commands'])} panel commands")


def _restart_request() -> None:
    try:
        ask({"type": "restart"})
    except ValueError as exc:
        fail(f"helper refused restart: {exc}")


def cmd_doctor(args) -> None:
    """Read-only: is this instance worth driving? Exit 0 only when every line is PASS."""
    import subprocess
    from cutdeck import live_check
    ok = True
    steps, _ = live_check.check(PORT)
    for s in steps:
        print(("PASS  " if s.ok else "FAIL  ") + f"{s.name}: {s.detail}")
        ok &= s.ok
    hello = helper_hello()
    if hello and hello.get("pid"):
        started = process_started(hello["pid"])
        fresh = started is not None and started >= newest_python_change()
        print(("PASS  " if fresh else "FAIL  ") + f"helper pid {hello['pid']} "
              + ("started after the newest cutdeck/**/*.py change" if fresh else
                 "is older than the cutdeck/**/*.py code: run `cdv.py launch --restart-helper`"))
        ok &= fresh
    try:
        loaded = json.loads(UDT_WORKSPACE.read_text(encoding="utf-8"))["plugins"]
        here = [p for p in loaded if Path(p["manifestPath"]).resolve() == (REPO / "uxp/cutdeck/manifest.json").resolve()]
        print(("PASS  " if here else "WARN  ") + "panel source: " + (
            "UXP Developer Tool loads this checkout's uxp/cutdeck (a panel reload picks up its code)" if here else
            "UXP Developer Tool does not point at this checkout; the panel may run other code"))
    except (OSError, KeyError, ValueError):
        print("WARN  panel source: no UXP Developer Tool workspace found (an installed .ccx ignores this checkout)")
    rev = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%h %s"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--short"], capture_output=True, text=True).stdout.strip()
    print(f"INFO  checkout {rev}{' (uncommitted changes)' if dirty else ''}")
    state = load_state()
    if state.get("run_id"):
        print(f"INFO  current run {state['run_id']}: evidence in {run_dir(state)}")
    raise SystemExit(0 if ok else 1)


def cmd_start(args) -> None:
    """Begin a run: a fresh evidence folder, and the user's active sequence remembered so
    cleanup can give it back."""
    state = load_state()
    if state.get("run_id") and not args.force:
        fail(f"run {state['run_id']} is still open: run `cdv.py cleanup` first (or start --force)")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{args.label}" if args.label else "")
    folder = ROOT / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    active = premiere("read_sequence")
    state.update({"run_id": run_id, "user_sequence": active["name"], "calls": 0})
    save_state(state)
    (folder / "run.json").write_text(json.dumps({"run_id": run_id, "started": datetime.now().isoformat(),
                                                 "user_sequence": active["name"], "project": active["project_path"]},
                                                indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"PASS  run {run_id}; evidence in {folder}; user sequence {active['name']!r} remembered")


def cmd_scratch(args) -> None:
    """Make the scratch sequence ready: create it once (9:16 30 fps preset), clear it, and place
    the verify clip on V1/A1 at 0. Idempotent: every run starts from the same timeline."""
    import subprocess
    state = load_state()
    run_dir(state)
    if not MEDIA.exists():
        MEDIA.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "6",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(MEDIA)], check=True)
    project = premiere("list_project", {"depth": 1})
    if not any(s["name"] == SCRATCH for s in project["sequences"]):
        if not PRESET.exists():
            fail(f"sequence preset not found: {PRESET}")
        premiere("create_sequence", {"name": SCRATCH, "preset_path": str(PRESET)})
    timeline = premiere("read_timeline", {"sequence": SCRATCH})
    clips = [c["id"] for t in timeline["tracks"] for c in t["clips"]]
    if clips:
        premiere("edit_clips", {"sequence": SCRATCH, "edits": [{"clip": c, "op": "remove"} for c in clips]})
    premiere("open_sequence", {"sequence": SCRATCH})
    placed = premiere("place_media", {"sequence": SCRATCH, "media": str(MEDIA), "at_ticks": "0", "v": 0, "a": 0})
    state["scratch"] = SCRATCH
    save_state(state)
    print(f"PASS  scratch {SCRATCH!r} reset: removed {len(clips)} clip(s), placed {[c['id'] for c in placed['placed']]}")


def cmd_call(args) -> None:
    """Run one Premiere command through the helper (the user's one way in) and record the
    request, the result or error, and the time into the run's evidence folder."""
    state = load_state()
    folder = run_dir(state)
    payload = json.loads(args.args) if args.args else {}
    state["calls"] = state.get("calls", 0) + 1
    save_state(state)
    record = {"n": state["calls"], "command": args.command, "args": payload, "at": datetime.now().isoformat()}
    try:
        record["result"] = premiere(args.command, payload)
        record["ok"] = True
    except Exception as exc:
        record["error"], record["ok"] = str(exc), False
    path = folder / f"{record['n']:02d}-{args.command}{('-' + args.label) if args.label else ''}.json"
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(record.get("result", record.get("error")), indent=1, ensure_ascii=False)[:4000])
    print(f"{'PASS' if record['ok'] else 'FAIL'}  recorded {path}", file=sys.stderr)
    raise SystemExit(0 if record["ok"] else 1)


def cmd_shot(args) -> None:
    """Evidence of what Premiere shows: the whole window, and (with --frame) the scratch
    sequence's rendered frame at the playhead. Both are copied into the run folder."""
    state = load_state()
    folder = run_dir(state)
    stamp = datetime.now().strftime("%H%M%S")
    window = premiere("screenshot")
    out = folder / f"shot-{stamp}-{args.label}-window.png"
    shutil.copyfile(window["path"], out)
    print(f"PASS  window {out}")
    if args.frame:
        frame = premiere("export_frame", {"sequence": state.get("scratch", SCRATCH)})
        out = folder / f"shot-{stamp}-{args.label}-frame.png"
        shutil.copyfile(frame["path"], out)
        print(f"PASS  frame {out}")


def cmd_cleanup(args) -> None:
    """Give Premiere back: reopen the user's sequence, stop only a helper this run started, close
    the run. Never deletes evidence, never saves the project, never deletes the scratch sequence
    (no API can; it is reused next run)."""
    import subprocess
    state = load_state()
    folder = run_dir(state)
    notes = []
    if state.get("user_sequence"):
        try:
            premiere("open_sequence", {"sequence": state["user_sequence"]})
            notes.append(f"reopened {state['user_sequence']!r}")
        except Exception as exc:
            notes.append(f"could not reopen {state['user_sequence']!r}: {exc}")
    pid = state.get("helper_pid_started")
    if pid and not args.keep_helper:
        hello = helper_hello()
        if hello and hello.get("pid") == pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            notes.append(f"stopped helper pid {pid} (this run started it)")
        state.pop("helper_pid_started", None)
    files = sorted(p.name for p in folder.iterdir())
    (folder / "cleanup.json").write_text(json.dumps({"at": datetime.now().isoformat(), "notes": notes,
                                                     "evidence": files}, indent=1, ensure_ascii=False), encoding="utf-8")
    for key in ("run_id", "user_sequence", "calls", "scratch"):
        state.pop(key, None)
    save_state(state)
    print("PASS  " + "; ".join(notes or ["nothing to undo"]))
    print(f"PASS  evidence kept: {folder} ({len(files)} files)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="step", required=True)
    p = sub.add_parser("launch")
    p.add_argument("--restart-helper", action="store_true", help="restart the helper on this checkout's code")
    p.add_argument("--reload-panel", action="store_true", help="save the project, then reload the panel")
    p.set_defaults(fn=cmd_launch)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("start")
    p.add_argument("--label", default="")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_start)
    sub.add_parser("scratch").set_defaults(fn=cmd_scratch)
    p = sub.add_parser("call")
    p.add_argument("command")
    p.add_argument("args", nargs="?", help="JSON object of arguments")
    p.add_argument("--label", default="")
    p.set_defaults(fn=cmd_call)
    p = sub.add_parser("shot")
    p.add_argument("label")
    p.add_argument("--frame", action="store_true")
    p.set_defaults(fn=cmd_shot)
    p = sub.add_parser("cleanup")
    p.add_argument("--keep-helper", action="store_true")
    p.set_defaults(fn=cmd_cleanup)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
