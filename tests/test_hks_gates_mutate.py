from cutdeck import hks_gates
from tools.hks_gates_mutate import FRAME, need, overlap_source, same_frame_count, shift_covers, uncover, unlabel

M, B = "G:/main.mp4", "G:/broll.mp4"


def clip(start, end, src_in, label=1, media=M):
    return {"start": start, "end": end, "source_in": src_in, "source_out": src_in + end - start,
            "media_path": media, "label": label, "disabled": False}


def final():
    """Three same-scene pieces; V1 cuts with A1; a B-roll cover sits on each sound cut."""
    sound = [clip(0, 10, 100), clip(10, 20, 130), clip(20, 30, 160)]
    v1 = [dict(c) for c in sound]
    covers = [clip(10, 12, 0, media=B), clip(20, 22, 50, media=B)]
    return {"name": "s", "audio_tracks": [{"clips": sound}],
            "video_tracks": [{"clips": v1}, {"clips": covers}]}


def test_removing_a_cover_exposes_a_same_frame_cut_and_leaves_the_final_alone():
    seq = final()
    assert same_frame_count(seq, 0, 30) == 0
    m, info = uncover(seq, 0, 30, 1)
    assert same_frame_count(m, 0, 30) == 1 and info == {"cuts_exposed": 1, "covers_removed": 1, "reached": True}
    assert len(seq["video_tracks"][1]["clips"]) == 2


def test_an_early_cover_is_a_near_miss_and_a_late_one_moves_its_start():
    seq = final()
    early, _ = shift_covers(seq, 0, 30, late=False)
    assert hks_gates.near_miss_covers(early, [10.0, 20.0])["value"] == 1.0
    late, info = shift_covers(seq, 0, 30, late=True)
    assert info["covers_shifted"] == 2
    assert [round(c["start"], 2) for c in late["video_tracks"][1]["clips"]] == [10.04, 20.08]


def test_one_piece_run_into_its_neighbour_is_one_source_repeat():
    sound = [clip(0, 10, 100), clip(10, 20, 110), clip(20, 30, 300)]
    seq = {"name": "s", "audio_tracks": [{"clips": sound}], "video_tracks": [{"clips": []}]}
    m, info = overlap_source(seq, 0, 30)
    assert info["source_gap_s"] == 0.0
    assert hks_gates.source_repeats(hks_gates.body_audio(m, 0, 30))["value"] == 1
    assert hks_gates.source_repeats(hks_gates.body_audio(seq, 0, 30))["value"] == 0


def test_unlabel_resets_the_asked_count_to_the_default_label():
    sound = [clip(i, i + 1, 100 + 2 * i) for i in range(20)]
    seq = {"name": "s", "audio_tracks": [{"clips": sound}], "video_tracks": [{"clips": []}]}
    m, info = unlabel(seq, 0, 20, 2)
    assert info["reset"] == 2
    assert hks_gates.draft_labels(hks_gates.body_audio(m, 0, 20))["value"] == 0.9


def test_need_is_the_first_count_whose_rounded_share_crosses_the_line():
    assert need(100, 0.46, lambda v, line: v > line) == 47
    assert need(150, 0.06, lambda v, line: v > line) == 10
    assert FRAME == 0.04


def test_a_synced_reframing_on_v2_is_not_a_cover():
    seq = final()
    seq["video_tracks"][1]["clips"][0] = clip(10, 12, 130)  # V2 shows the incoming speaker in sync
    _, info = shift_covers(seq, 0, 30, late=True)
    assert info["covers_shifted"] == 1
    _, info = uncover(seq, 0, 30, 2)
    assert info["covers_removed"] == 1 and not info["reached"]
