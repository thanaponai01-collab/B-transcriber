"""The day command (cutdeck/hks_day.py): judge replies, the marker draft, the Premiere guard."""

import asyncio
import json

import pytest

from cutdeck import hks_day as d
from cutdeck import hks_judge as j
from transcribe.timebase import Timebase

LINES = [["L0001", 30.0, 33.0, "สวัสดีค่ะ"], ["L0002", 60.0, 64.0, "เกิดอะไรขึ้นคะ"], ["L0003", 65.0, 70.0, "หนูถูกจับ"],
         ["L0004", 300.0, 305.0, "ตำรวจว่าอย่างไร"], ["L0005", 306.0, 310.0, "ออกหมายจับ"]]
DROPS = [{"start": 0.0, "end": 22.0, "kind": "opening"},
         {"start": 100.0, "end": 108.0, "kind": "bumper"}, {"start": 108.0, "end": 150.0, "kind": "clock_off"},
         {"start": 400.0, "end": 420.0, "kind": "credits"}]
QUESTIONS = [{"start": 60.0, "line": "L0002", "story": 1, "title": "เกิดอะไรขึ้น"},
             {"start": 300.0, "line": "L0004", "story": 2, "title": "ตำรวจ"}]


def test_a_reply_may_wrap_its_json():
    assert d.answer_json('```json\n{"spans": []}\n```') == {"spans": []}
    with pytest.raises(j.JudgeAnswerError):
        d.answer_json("no answer here")


def test_the_questions_task_takes_parts_and_only_rising_story_numbers():
    per = {"a.mp4": [j.Line(*l) for l in LINES]}
    got = j.parse("questions", {"parts": [{"part": 1, "name": "x"}],
                                "topics": [{"start": "L0002", "story": 1, "title": "q"}]}, per)
    assert got["a.mp4"] == [{"start": 60.0, "line": "L0002", "story": 1, "title": "q"}]
    with pytest.raises(j.JudgeAnswerError):
        j.parse("questions", {"topics": [{"start": "L0004", "story": 2}, {"start": "L0005", "story": 1}]}, per)
    assert "parts" in j.TASKS["questions"]["format"] and j.TASKS["questions"]["hide"] == ("drops",)


def test_the_draft_has_questions_by_part_breaks_the_social_part_and_sponsors_outside_breaks():
    sponsors = [{"start": 110.0, "end": 140.0, "why": "ad inside the break"},
                {"start": 380.0, "end": 395.0, "why": "thanks the sponsors"}]
    markers, md = d.draft(QUESTIONS, {1: "ถูกอุ้ม", 2: "ตำรวจ"}, LINES, DROPS, sponsors, 250.0, 420.0,
                          Timebase(25, 1))
    names = [m["name"] for m in markers]
    assert names == ["[OPENING] cut", "S1.1 เกิดอะไรขึ้น", "[BREAK] cut", "[BREAK 3] social part starts",
                     "S2.1 ตำรวจ", "[SPONSOR?] check", "[CREDITS] cut"]
    first = markers[1]
    assert first["start_s"] == 60.0 and first["duration_s"] == 240.0  # runs to the next question
    assert first["comment"] == "เกิดอะไรขึ้นคะ หนูถูกจับ ตำรวจว่าอย่างไร"  # the opening lines
    assert markers[2]["start_s"] == 100.0 and markers[2]["duration_s"] == 50.0  # bumper + clock-off as one break
    assert markers[4]["duration_s"] == 120.0  # the last question runs to the end
    assert "`00:01:00:00`–`00:05:00:00` (4.0 min)" in md  # each question as Premiere timecode
    assert "## S1 ถูกอุ้ม" in md and "## S2 ตำรวจ" in md and "ad inside the break" not in md
    assert all(d.DRAFT_NAME.match(n) for n in names)
    assert not d.DRAFT_NAME.match("my own marker") and not d.DRAFT_NAME.match("S1 note")


class FakeBackend:
    def __init__(self, active="Editing", end=420.0, connected=True, markers=()):
        self.active, self.end, self.connected, self.markers, self.calls = active, end, connected, list(markers), []

    async def premiere_status(self):
        return {"connected": self.connected}

    async def premiere(self, command, args=None):
        self.calls.append((command, args))
        if command == "read_sequence":
            return {"name": self.active, "end_seconds": self.end, "ticks_per_frame": "10160640000"}
        if command == "read_timeline":
            return {"markers": self.markers}
        if command == "remove_markers":
            return {"removed": len(args["starts_ticks"])}
        if command == "add_markers":
            return {"added": len(args["markers"])}
        raise AssertionError(command)


def _place(monkeypatch, fake, footage_s=420.0):
    import cutdeck.ai_backend
    monkeypatch.setattr(cutdeck.ai_backend, "Backend", lambda: fake)
    return asyncio.run(d.place_markers([{"start_s": 1, "name": "S1.1 x"}], footage_s))


def test_markers_replace_only_the_earlier_draft(monkeypatch):
    fake = FakeBackend(markers=[{"name": "S1.1 old", "start_ticks": "1"}, {"name": "[BREAK] cut", "start_ticks": "2"},
                                {"name": "my note", "start_ticks": "3"}])
    assert "1 on 'Editing'" in _place(monkeypatch, fake)
    removed = [a for c, a in fake.calls if c == "remove_markers"][0]
    assert removed == {"sequence": "Editing", "starts_ticks": ["1", "2"]}


@pytest.mark.parametrize("fake, why", [
    (FakeBackend(connected=False), "not connected"),
    (FakeBackend(active="footage"), "active sequence is 'footage'"),
    (FakeBackend(end=300.0), "already cut"),
])
def test_markers_are_refused_unless_editing_is_active_and_uncut(monkeypatch, fake, why):
    assert why in _place(monkeypatch, fake)
    assert not any(c in ("add_markers", "remove_markers") for c, _ in fake.calls)


def test_transcript_lines_carry_start_and_end_as_premiere_timecode():
    lines = [["L0001", 22.55, 27.33, "สวัสดีค่ะ"], ["L0002", 3725.0, 3726.94, "ครับ"]]
    assert d.transcript(lines, Timebase(25, 1)) == (
        "[00:00:22:14 - 00:00:27:08] สวัสดีค่ะ\n"     # 22.55 s = frame 563.75 -> 564 = 22 s + 14
        "[01:02:05:00 - 01:02:06:24] ครับ\n")         # 3726.94 s -> frame 93173.5 -> 93174 = 1:02:06 + 24
