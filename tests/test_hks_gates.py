import importlib.util
from pathlib import Path

from cutdeck import hks_gates

M = "G:/x.mp4"


def clip(start, end, src_in, label=1, media=M):
    return {"start": start, "end": end, "source_in": src_in, "source_out": src_in + end - start,
            "media_path": media, "label": label, "disabled": False}


def seq(audio, video):
    return {"name": "s", "audio_tracks": [{"clips": audio}], "video_tracks": [{"clips": v} for v in video]}


def test_neighbouring_pieces_that_replay_words_are_repeats():
    a = [clip(0, 10, 100), clip(10, 15, 109.5), clip(15, 20, 200)]
    got = hks_gates.source_repeats(a)
    assert got["value"] == 1 and got["items"][0]["overlap_s"] == 0.5


def test_a_through_edit_or_a_jump_forward_is_not_a_repeat():
    a = [clip(0, 10, 100), clip(10, 15, 110), clip(15, 20, 300)]
    assert hks_gates.source_repeats(a)["value"] == 0


def test_a_cover_two_frames_after_the_sound_cut_is_a_near_miss():
    sound = [clip(0, 10, 100), clip(10, 20, 300)]
    body = [clip(0, 20, 100)]  # the picture runs on under the sound cut at 10.0
    late_cover = [clip(10.08, 14, 500)]  # and the cover arrives 2 frames late
    got = hks_gates.near_miss_covers(seq(sound, [body, late_cover]), [10.0])
    assert got["value"] == 1.0 and got["items"][0]["frames_off"] == 2


def test_a_cover_on_the_cut_frame_is_not_a_near_miss():
    sound = [clip(0, 10, 100), clip(10, 20, 300)]
    body = [clip(0, 10, 100), clip(10, 20, 300)]
    cover = [clip(10.0, 14, 500)]
    assert hks_gates.near_miss_covers(seq(sound, [body, cover]), [10.0])["value"] == 0.0


def test_unlabelled_pieces_lower_the_label_share():
    a = [clip(0, 5, 0), clip(5, 10, 10, label=hks_gates.DEFAULT_LABEL), clip(10, 15, 20, label=None), clip(15, 20, 30)]
    assert hks_gates.draft_labels(a)["value"] == 0.5


def test_every_code_gate_has_a_registry_line():
    reg = hks_gates.registry()["gates"]
    for gid in ("same_frame_share", "near_miss_covers", "source_repeats", "draft_labels", "day_setup"):
        assert {"kind", "direction", "line", "status"} <= reg[gid].keys()


def _hook():
    path = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "hks_handover_gate.py"
    spec = importlib.util.spec_from_file_location("hks_handover_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hook_blocks_a_draft_changed_after_the_last_handover():
    v = _hook().verdict([("mutate", "build_sequence"), ("say", "Draft is ready")], "label")
    assert v and "hks_handover" in v


def test_hook_in_label_mode_wants_each_failed_gate_named():
    evs = [("mutate", "build_sequence"), ("handover", "HANDOVER BLOCKED: x\n  FAILED same_frame_share: 0.7"),
           ("say", "Draft is ready.")]
    assert "same_frame_share" in _hook().verdict(evs, "label")
    evs[-1] = ("say", "same_frame_share failed at 0.705 (line 0.42). Draft is ready.")
    assert _hook().verdict(evs, "label") is None
    assert _hook().verdict(evs, "block") is not None


def test_hook_lets_a_session_with_no_draft_stop():
    assert _hook().verdict([("say", "hello")], "label") is None


def test_hook_blocks_a_handover_that_did_not_finish():
    evs = [("mutate", "build_sequence"), ("handover", "Traceback (most recent call last): ..."), ("say", "ready")]
    assert "did not finish" in _hook().verdict(evs, "label")


def test_hook_wants_an_overridden_gate_named_too():
    evs = [("mutate", "build_sequence"), ("handover", "HANDOVER OK: x\n  OVERRIDDEN same_frame_share: 0.7"),
           ("say", "Draft is ready.")]
    assert "same_frame_share" in _hook().verdict(evs, "label")


def test_hook_reads_a_build_and_handover_in_one_command_in_order(tmp_path):
    import json as _json
    t = tmp_path / "t.jsonl"
    rows = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Bash",
            "input": {"command": "python build_sequence_x.py && python -m cutdeck.hks_handover --prproj p"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "content": "HANDOVER OK: s"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ready"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b", "name": "Bash",
            "input": {"command": "grep -n build_sequence cutdeck/*.py"}}]}},
    ]
    t.write_text("\n".join(_json.dumps(r) for r in rows), encoding="utf-8")
    hook = _hook()
    assert [k for k, _ in hook.events(t)] == ["mutate", "handover", "say"]
    assert hook.verdict(list(hook.events(t)), "label") is None


def test_hook_reads_every_text_block_after_the_handover():
    evs = [("mutate", "build_sequence"), ("handover", "HANDOVER BLOCKED: x\n  FAILED same_frame_share: 0.7"),
           ("say", "same_frame_share FAILED at 0.705."), ("say", "Other notes.")]
    assert _hook().verdict(evs, "label") is None
