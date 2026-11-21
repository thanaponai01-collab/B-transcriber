"""Build items for HKS step 1e (cutdeck/hks_build.py), on sequences shaped like prproj_reader output."""
import copy

from cutdeck.hks_build import compare, items_from, smoke, ticks

SHOW = "D:\\shoot\\HKS Show Full.mp4"
DAMAGE = "D:\\fx\\FILM_DAMAGE2.mov"
BGM = "D:\\music\\[BGM]where everything.wav"


def motion(**params):
    base = {"position": [0.5, 0.5], "scale": 100.0, "scale_width": 100.0, "uniform": True, "rotation": 0.0,
            "anchor": [0.5, 0.5], "crop_left": 0.0, "crop_top": 0.0, "crop_right": 0.0, "crop_bottom": 0.0}
    return {"name": "Motion", "match_name": "AE.ADBE Motion", "bypass": False,
            "params": {k: {"value": v} for k, v in {**base, **params}.items()}}


def volume(level):
    return [{"name": "Volume", "match_name": None, "params": {"Level": {"value": level}}},
            {"name": "Channel Volume", "match_name": None,
             "params": {"Left": {"value": 0.177827939391}, "Right": {"value": 0.177827939391}}}]


def blur():
    return {"name": "Gaussian Blur (Legacy)", "match_name": "AE.ADBE Gaussian Blur 2", "params": None}


def clip(start, end, src_in, media=SHOW, effects=(), name=None):
    return {"name": name or media.rsplit("\\", 1)[-1], "start": start, "end": end, "source_in": src_in,
            "source_out": src_in + (end - start), "disabled": False, "media_path": media,
            "source_frame": [1280, 720], "effects": list(effects)}


def seq(video, audio, name="1 YOUTUBE D1"):
    return {"name": name,
            "video_tracks": [{"index": i, "muted": False, "clips": list(c)} for i, c in enumerate(video)],
            "audio_tracks": [{"index": i, "muted": False, "clips": list(c)} for i, c in enumerate(audio)]}


def show():
    adjustment = dict(media=None, name="Adjustment Layer")
    v1 = [clip(0, 4, 100, effects=[motion(scale=150.0, scale_width=150.0)]),
          clip(4, 6, 200, effects=[motion(scale=288.0, position=[0.8687499761581421, 0.75])])]
    v2 = [clip(1, 3, 0, DAMAGE, effects=[{"name": "Opacity", "match_name": "AE.ADBE Opacity", "params": {"opacity": {"value": 100.0}}}])]
    v8 = [clip(0, 5, 0, effects=[blur()], **adjustment)]
    v9 = [clip(0, 5, 0, effects=[blur()], **adjustment)]
    a1 = [clip(0, 4, 100), clip(10, 12, 300)]
    a2 = [clip(0, 20, 0, BGM, effects=volume(0.00398107199))]
    return seq([v1, v2, [], [], [], [], [], v8, v9], [a1, a2])


def test_pairs_in_sync_audio_with_its_video_and_keeps_the_rest_apart():
    items, _ = items_from(show())
    by_id = {it["id"]: it for it in items}
    assert (by_id["V1@0.00"]["v"], by_id["V1@0.00"]["a"]) == (0, 0)
    assert (by_id["V1@4.00"]["v"], by_id["V1@4.00"]["a"]) == (0, None)
    assert (by_id["A1@10.00"]["v"], by_id["A1@10.00"]["a"]) == (None, 0)
    assert by_id["A2@0.00"]["level"] == 0.00398107199
    assert by_id["V1@0.00"]["in_ticks"] == ticks(100) and by_id["V1@0.00"]["out_ticks"] == ticks(104)


def test_motion_sends_only_what_a_fresh_clip_lacks_and_never_scale_width():
    by_id = {it["id"]: it for it in items_from(show())[0]}
    assert by_id["V1@0.00"]["motion"] == {"scale": 150.0}
    assert by_id["V1@4.00"]["motion"] == {"scale": 288.0, "position": {"x": 0.8687499761581421, "y": 0.75}}
    plain = seq([[clip(0, 4, 100, effects=[motion(position=[0.50000001, 0.5])])]], [])
    assert items_from(plain)[0][0]["motion"] is None


def test_non_uniform_scale_is_counted_not_sent():
    items, skipped = items_from(seq([[clip(0, 4, 100, effects=[motion(scale=150.0, scale_width=80.0, uniform=False)])]], []))
    assert items[0]["motion"] == {"scale": 150.0}
    assert skipped["non-uniform scale"] == 1


def test_only_v8_blur_gets_the_clock_crop_and_v9_is_skipped_with_its_cause():
    items, skipped = items_from(show())
    blurs = [it for it in items if "blur" in it]
    assert [(it["v"], it["like"]["track"]) for it in blurs] == [(7, 7)]
    assert blurs[0]["motion"]["cropRight"] == 76.7
    assert skipped["blur on V9: box never measured"] == 1


def test_an_effect_that_is_not_replayed_is_counted_and_untouched_audio_components_are_not():
    _, skipped = items_from(show())
    assert skipped["effect dropped: AE.ADBE Opacity"] == 1
    assert not any("Volume" in cause for cause in skipped)
    louder = show()
    louder["audio_tracks"][1]["clips"][0]["effects"][1]["params"]["Left"]["value"] = 0.5
    assert items_from(louder)[1]["effect dropped: Channel Volume"] == 1


def test_smoke_takes_the_first_item_of_each_kind():
    picked = smoke(items_from(show())[0])
    assert sorted(it["id"] for it in picked) == ["A1@10.00", "A2@0.00", "V1@0.00", "V1@4.00", "V2@1.00", "V8@0.00"]
    assert len(smoke(items_from(show())[0] * 2)) == 6


def test_compare_passes_on_identical_input_and_on_a_smoke_build():
    items, _ = items_from(show())
    assert compare(items, items_from(show())[0]) == []
    assert compare(smoke(items), smoke(items)) == []


def test_compare_allows_exactly_one_frame_and_flags_two():
    original, _ = items_from(show())
    for frames, problems in ((1, []), (2, ["V1@4.00: in off by +0.080 s", "V1@4.00: out off by +0.080 s"])):
        built = show()
        built["video_tracks"][0]["clips"][1]["source_in"] += frames * 0.04
        built["video_tracks"][0]["clips"][1]["source_out"] += frames * 0.04
        assert compare(original, items_from(built)[0]) == problems


def test_compare_finds_a_shift_past_one_frame_a_level_change_and_lost_motion():
    original, _ = items_from(show())
    built = show()
    v1 = built["video_tracks"][0]["clips"]
    a1 = built["audio_tracks"][0]["clips"]
    for c, by in ((v1[0], 0.03), (a1[0], 0.03), (v1[1], 0.08)):  # 0.03 s is within a frame: no difference
        c["start"] += by
        c["end"] += by
    built["audio_tracks"][1]["clips"][0]["effects"] = volume(0.011220183223)
    built["video_tracks"][1]["clips"][0]["effects"] = []     # the build drops the Opacity: no difference
    v1[0]["effects"] = []                                    # Motion lost: Scale back to 100
    built["video_tracks"][7]["clips"][0]["effects"].append(motion(crop_right=76.7))  # the blur's crop
    problems = compare(original, items_from(built)[0])
    assert problems == ["V1@0.00: scale 150.0 != 100.0", "A2@0.00: level 0.00398107199 != 0.011220183223",
                        "V1@4.00: at off by +0.080 s"]


def test_compare_lists_missing_and_extra_items():
    original, _ = items_from(show())
    built = copy.deepcopy(show())
    built["audio_tracks"][0]["clips"].pop()
    built["video_tracks"][1]["clips"].append(clip(20, 22, 5, DAMAGE))
    assert compare(original, items_from(built)[0]) == ["A1@10.00: missing", "V2@20.00: extra"]
