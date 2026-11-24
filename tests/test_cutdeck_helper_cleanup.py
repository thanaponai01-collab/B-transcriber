"""The helper deletes month-old job folders when it starts and rotates its command log."""
import os
import time

from cutdeck import helper


def _age(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_start_deletes_job_folders_older_than_a_month_only(tmp_path):
    old, recent, other = tmp_path / ("a" * 32), tmp_path / ("b" * 32), tmp_path / "notes"
    for d in (old, recent, other):
        d.mkdir()
        (d / "job.json").write_text("{}")
    _age(old / "job.json", 31)
    _age(recent / "job.json", 29)
    _age(other / "job.json", 90)
    (tmp_path / "premiere_commands.jsonl").write_text("")
    helper.Jobs(tmp_path)
    assert not old.exists() and recent.exists() and other.exists()


def test_command_log_moves_to_dot_1_past_its_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "COMMAND_LOG_MAX", 100)
    jobs = helper.Jobs(tmp_path)
    log = tmp_path / helper.COMMAND_LOG
    log.write_text("x" * 150)
    jobs._log_command({"event": "start"})
    assert (tmp_path / (helper.COMMAND_LOG + ".1")).read_text() == "x" * 150
    assert log.read_text().count("\n") == 1 and '"event": "start"' in log.read_text()
    jobs._log_command({"event": "end"})
    assert log.read_text().count("\n") == 2


def test_command_log_never_rotates_between_a_calls_start_and_end(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "COMMAND_LOG_MAX", 100)
    jobs = helper.Jobs(tmp_path)
    log = tmp_path / helper.COMMAND_LOG
    log.write_text('{"event": "start"}\n' + "x" * 150 + "\n")
    jobs._log_command({"event": "end"})
    assert not (tmp_path / (helper.COMMAND_LOG + ".1")).exists()
    assert log.read_text().endswith('"event": "end"}\n')
