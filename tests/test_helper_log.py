import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import helper_log  # noqa: E402


def _write(path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _call(n, minute, command, error=None, caller=None):
    t = f"2026-11-24T03:{minute:02d}:00.000+07:00"
    start = {"time": t, "call": str(n), "event": "start", "command": command, "args": {}}
    if caller:
        start["caller"] = caller
    end = {"time": t.replace(":00.000", ":00.500"), "call": str(n), "event": "end", "ok": error is None}
    if error:
        end["error"] = error
    return [start, end]


def test_a_repeating_failure_is_one_incident(tmp_path):
    log = tmp_path / "premiere_commands.jsonl"
    events = []
    for i in range(5):  # one wait loop, a minute apart
        events += _call(i, i, "read_sequence", "ValueError: No CutDeck panel is connected: open it", "s1")
    events += _call(9, 6, "menu_command", 'ValueError: No menu item "Clip > Link" (see premiere_list_menu)')
    events += _call(10, 7, "read_sequence")
    _write(log, events)

    rows = helper_log.calls(log)
    runs = helper_log.incidents(rows)

    assert len(rows) == 7
    assert [(r["command"], r["count"]) for r in runs] == [("read_sequence", 5), ("menu_command", 1)]
    assert runs[0]["callers"] == {"s1"}
    assert "7 calls" in helper_log.report(rows)


def test_a_gap_splits_incidents_and_since_filters(tmp_path):
    log = tmp_path / "premiere_commands.jsonl"
    _write(log, _call(1, 0, "read_sequence", "ValueError: No panel") + _call(2, 59, "read_sequence", "ValueError: No panel"))

    assert [r["count"] for r in helper_log.incidents(helper_log.calls(log))] == [1, 1]
    assert len(helper_log.calls(log, since="2026-11-24T03:30")) == 1
