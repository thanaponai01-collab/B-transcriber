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
