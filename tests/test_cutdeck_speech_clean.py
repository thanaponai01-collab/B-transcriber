"""Clean speech: which fillers, repeats and restarts are cut, which are marked, which are left."""
from cutdeck import speech_clean
from cutdeck.timeline_transcript import TimelineWord

MS = 254016000
TPF = 8467200000  # 30 fps


def lines(*spec):
    """Each line ``(text, start_ms, end_ms)`` is one cue, one word per space-separated piece."""
    out = []
    for cue, (text, s, e) in enumerate(spec):
        pieces = text.split()
        step = (e - s) // len(pieces)
        for n, p in enumerate(pieces):
            a = s + n * step
            out.append(TimelineWord(p, a * MS, (a + step) * MS, "A1@0", "a.mp4", a, a + step, cue, None))
    return out


def kinds(found):
    return [(f["kind"], f["action"], f["text"]) for f in found]


def test_fillers_whole_line_and_at_line_start():
    words = lines(("เอ่อ", 0, 300), ("เอ่อ เข้าสู่ โค้ง", 800, 2000), ("ไป ต่อ", 2600, 3000))
    assert kinds(speech_clean.find(words)) == [("filler", "cut", "เอ่อ"), ("filler", "cut", "เอ่อ")]
    assert speech_clean.find(words)[1]["word_range"] == [1, 1]


def test_repeat_twice_is_cut_short_word_twice_is_marked_three_times_is_left():
    words = lines(("สังเกต ข้างหลัง", 0, 800), ("สังเกต ข้างหลัง", 1000, 1800),   # stutter
                  ("มัน", 2500, 2700), ("มัน", 2900, 3100),                         # short: mark
                  ("เพิ่บ", 4000, 4200), ("เพิ่บ", 4400, 4600), ("เพิ่บ", 4800, 5000),  # emphasis
                  ("จบ", 6000, 6300))
    assert kinds(speech_clean.find(words)) == [("repeat", "cut", "สังเกตข้างหลัง"), ("repeat", "mark", "มัน")]


def test_restart_is_cut_but_reduplication_and_long_lines_are_not():
    words = lines(("จังหวะ", 0, 400), ("จังหวะ พิษ", 600, 1400),          # restart
                  ("สีไฟ", 2500, 2900), ("สีไฟ สีไฟ", 3100, 3900),        # doubling
                  ("ผม คิด ว่า แบบ นี้ ยาว มาก", 5000, 8000), ("ผม คิด ว่า แบบ นี้ ยาว มาก แล้ว", 8200, 11000))
    found = speech_clean.find(words, cut_restarts=True)
    assert ("restart", "cut", "จังหวะ") in kinds(found)
    assert ("restart", "mark", "จังหวะ") in kinds(speech_clean.find(words))  # marked by default
    assert not any(f["text"].startswith("สีไฟ") for f in found)
    # the 3 s first take is too long to be a restart: a near restart, marked
    assert ("near_restart", "mark", "ผมคิดว่าแบบนี้ยาวมาก") in kinds(found)


def test_a_restart_must_end_on_a_word_boundary():
    words = lines(("มา", 0, 300), ("มาก เลย", 500, 1200), ("จบ", 2000, 2300))
    assert not [f for f in speech_clean.find(words, cut_restarts=True) if f["kind"] == "restart"]


def test_lines_far_apart_are_not_restarts_and_retake_phrases_are_marked():
    words = lines(("จังหวะ", 0, 400), ("จังหวะ พิษ", 3000, 3800), ("เดี๋ยว เอา ใหม่", 4500, 5200))
    assert kinds(speech_clean.find(words, retake_markers=("เดี๋ยวเอาใหม่",))) == [
        ("retake", "mark", "เดี๋ยวเอาใหม่")]


def test_plan_turns_a_cut_with_no_pause_into_a_marker_and_skips_such_a_filler():
    words = lines(("จังหวะ", 0, 400), ("จังหวะ พิษ", 400, 1200), ("เอ่อ", 1200, 1500), ("ไป", 2200, 2500))
    found = speech_clean.find(words, cut_restarts=True)
    loud = lambda ticks: 5.0  # noqa: E731  every frame has sound: no cut can be clean
    p = speech_clean.plan(words, found, TPF, 3000 * MS, level_at=loud)
    assert p["cuts_frames"] == [] and not p["cut"]
    assert [m["kind"] for m in p["marked"]] == ["restart"] and "no pause" in p["marked"][0]["why"]
    assert [s["kind"] for s in p["skipped"]] == ["filler"]
    quiet = lambda ticks: -10.0  # noqa: E731
    p = speech_clean.plan(words, found, TPF, 3000 * MS, level_at=quiet)
    assert len(p["cut"]) == 2 and p["cuts_frames"]


def test_findings_next_to_each_other_are_one_cut():
    # filler, then a restart right after it, with a short pause between: no sliver between two cuts
    words = lines(("เอ่อ", 0, 300), ("มัน คือ", 400, 800), ("มัน คือ จุด นี้", 900, 1900), ("จบ", 2600, 2900))
    found = speech_clean.find(words, cut_restarts=True)
    assert [f["kind"] for f in found] == ["filler", "restart"]
    p = speech_clean.plan(words, found, TPF, 3500 * MS, level_at=lambda ticks: -10.0)
    assert len(p["cuts_frames"]) == 1


def test_markers_land_where_the_text_is_after_the_cuts():
    cuts = [[0, 30], [60, 90]]  # 1 s and 1 s removed
    assert speech_clean.after_cuts(1.5, cuts, TPF) == 0.5
    assert speech_clean.after_cuts(2.5, cuts, TPF) == 1.0   # inside the second cut: at its join
    assert speech_clean.after_cuts(4.0, cuts, TPF) == 2.0
    (m,) = speech_clean.markers([{"kind": "repeat", "text": "มัน", "why": "w", "at_s": [3.0, 3.5]}], cuts, TPF)
    assert m["start_s"] == 1.0 and m["duration_s"] == 0.5 and m["name"].startswith("CHECK repeat")


def test_clean_speech_command_cuts_a_copy_marks_it_and_reads_it_back(monkeypatch):
    import asyncio

    from cutdeck import driver_commands
    words = lines(("เอ่อ", 0, 300), ("จังหวะ", 900, 1300), ("จังหวะ พิษ", 1500, 2300),
                  ("มัน", 3000, 3200), ("มัน", 3400, 3600), ("จบ", 4200, 4500))
    built = {"missing": [], "word_objects": words, "track": "A1", "cuts_in_sound": [],
             "level_at": lambda ticks: -10.0}
    monkeypatch.setattr(driver_commands.timeline_transcript, "build", lambda *a, **k: built)
    monkeypatch.setattr(driver_commands, "_retake_markers", lambda: ())
    calls = []

    async def premiere(command, args):
        calls.append((command, args))
        return {"name": args.get("sequence", "Rough"), "ticks_per_frame": str(TPF), "end_ticks": str(5000 * MS)}

    args = COMMANDS_PREPARE({"result_name": "Rough clean", "cut_restarts": True})
    result = asyncio.run(driver_commands._clean_speech(args, premiere))
    assert result["cut_count"]["filler"] == 1 and result["cut_count"]["restart"] == 1
    assert result["marked_count"] == 1 and result["markers_added"] == 1 and result["new_cuts_in_sound"] == []
    names = [c for c, _ in calls]
    assert names == ["read_timeline", "cut_copy", "open_sequence", "add_markers", "read_timeline"]
    assert dict(calls)["cut_copy"]["result_name"] == "Rough clean"
    # apply false: nothing made, every finding listed with its context
    calls.clear()
    dry = asyncio.run(driver_commands._clean_speech(COMMANDS_PREPARE({"apply": False}), premiere))
    assert [c for c, _ in calls] == ["read_timeline"] and len(dry["cut"]) == 1  # restarts marked by default
    restart = next(f for f in dry["marked"] if f["kind"] == "restart")
    assert restart["context"].startswith("เอ่อ / [จังหวะ]")


def COMMANDS_PREPARE(args):
    from cutdeck.driver_commands import COMMANDS
    return COMMANDS["clean_speech"].prepare(args, None)
