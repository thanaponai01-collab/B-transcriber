"""Select-only judgment loop (cutdeck/hks_judge.py): lines, prompts without gold, answer checks."""

import pytest

from cutdeck import hks_judge as j

WORDS = [[0.0, 0.4, "สวัสดี"], [0.5, 0.9, "ครับ"], [2.0, 2.5, "วันนี้"], [2.6, 3.0, "เรื่อง"],
         [10.0, 10.5, "โฆษณา"], [10.6, 11.0, "สินค้า"]]


def test_lines_break_at_pauses_and_leave_drops_out():
    ls = j.lines(WORDS)
    assert [(l.id, l.text) for l in ls] == [("L0001", "สวัสดีครับ"), ("L0002", "วันนี้เรื่อง"), ("L0003", "โฆษณาสินค้า")]
    assert [l.text for l in j.lines(WORDS, drops=[(1.9, 3.1)])] == ["สวัสดีครับ", "โฆษณาสินค้า"]
    long = [[i * 0.5, i * 0.5 + 0.4, "ก"] for i in range(60)]  # 30 s without a pause
    assert max(l.end - l.start for l in j.lines(long)) <= j.MAX_LINE


def test_the_prompt_holds_the_lines_and_no_times_are_asked_for():
    text = j.prompt_text("sponsors", {"a.mp4": j.lines(WORDS)})
    assert "L0003 [0:00:10] โฆษณาสินค้า" in text and "Do not write times" in text


def test_an_answer_is_select_only():
    per = {"a.mp4": j.lines(WORDS)}
    got = j.parse("sponsors", {"spans": [{"from": "L0003", "to": "L0003", "why": "ad"}]}, per)
    assert got["a.mp4"][0]["start"] == 10.0 and got["a.mp4"][0]["end"] == 11.0
    with pytest.raises(j.JudgeAnswerError):
        j.parse("sponsors", {"spans": [{"from": "L0009", "to": "L0009"}]}, per)
    with pytest.raises(j.JudgeAnswerError):
        j.parse("sponsors", {"spans": [{"from": "L0003", "to": "L0001"}]}, per)
    with pytest.raises(j.JudgeAnswerError):
        j.parse("topics", {"topics": [{"start": "L0002", "story": 2}, {"start": "L0003", "story": 1}]}, per)
    topics = j.parse("topics", {"topics": [{"start": "L0002", "story": 1, "title": "x"}]}, per)
    assert topics["a.mp4"] == [{"start": 2.0, "line": "L0002", "story": 1, "title": "x"}]


def test_an_answer_keeps_the_lines_its_prompt_showed(tmp_path, monkeypatch):
    folder = tmp_path / "20990101 - x"
    shown = {"a.mp4": j.lines(WORDS)}
    monkeypatch.setattr(j, "episode_lines", lambda *a, **k: shown)
    monkeypatch.setattr(j.hks_episode, "load", lambda *a, **k: {"files": {}})
    j.write_prompt(folder, "sponsors", tmp_path)
    shown = {"a.mp4": j.lines(WORDS, drops=[(1.9, 3.1)])}  # a later drop renumbers the lines
    j.paths(folder, "sponsors", tmp_path)[1].write_text('{"spans": [{"from": "L0003", "to": "L0003"}]}')
    assert j.answer(folder, "sponsors", tmp_path)["a.mp4"][0]["start"] == 10.0
