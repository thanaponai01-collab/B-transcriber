"""shorts_check flags a 9:16 timeline that breaks the measurable Shorts rules (issue 128)."""

from cutdeck.shorts_check import check_sequence

FEED = "Las Vegas GP 2026 Race.mp4"


def clip(start, end, name="cam.mp4", frame=(1920, 1080), **extra):
    c = {"name": name, "start": start, "end": end, "source_in": 0.0, "source_out": end - start,
         "disabled": False, "media_path": "E:\\x\\" + name, "source_frame": list(frame), "effects": []}
    c.update(extra)
    return c


def motion(pos, scale, anchor=(0.5, 0.5), crop=(0, 0, 0, 0)):
    params = {"position": {"value": list(pos)}, "scale": {"value": scale}, "rotation": {"value": 0.0},
              "anchor": {"value": list(anchor)}}
    for side, v in zip(("crop_left", "crop_top", "crop_right", "crop_bottom"), crop):
        params[side] = {"value": v}
    return {"name": "Motion", "match_name": "AE.ADBE Motion", "bypass": False, "params": params}


def text(start, end, words):
    return clip(start, end, name="Graphic", frame=(1080, 1920),
                effects=[{"name": "Text", "text": {"text": words}, "params": {}}])


def hold(start, end, **extra):
    return clip(start, end, name="CutDeck_Hold_1.png", frame=(1080, 1920), **extra)


def seq(*tracks, muted=()):
    return {"name": "TT test", "frame": [1080, 1920],
            "video_tracks": [{"index": i, "muted": i in muted, "locked": False, "clips": list(t)}
                             for i, t in enumerate(tracks)]}


def rules(sequence, **kw):
    return [f["rule"] for f in check_sequence(sequence, **kw)]


def test_clean_short_has_no_flags():
    s = seq([clip(0, 10)], [clip(0, 2, FEED)], [text(0, 2, "RUS ชนกำแพง")])
    assert check_sequence(s) == []


def test_more_than_3_s_of_moving_race_feed_is_flagged():
    flags = check_sequence(seq([clip(0, 10)], [clip(0, 2, FEED), clip(5, 7, FEED)]))
    assert [f["rule"] for f in flags] == ["moving_video"]
    assert flags[0]["seconds"] == 4.0


def test_a_hold_above_the_feed_hides_it():
    s = seq([clip(0, 10)], [clip(0, 4, FEED)], [hold(1, 4)])
    assert check_sequence(s) == []


def test_a_hold_hides_only_the_feed_below_it():
    s = seq([clip(0, 10)], [clip(0, 4, FEED)], [hold(0, 4)], [clip(0, 4, FEED)])
    assert rules(s) == ["moving_video"]


def test_a_cropped_box_above_the_feed_does_not_hide_it():
    box = hold(0, 4, effects=[motion((0.5, 0.5), 100, crop=(40, 40, 40, 40))])
    assert rules(seq([clip(0, 10)], [clip(0, 4, FEED)], [box])) == ["moving_video"]


def test_a_feed_on_a_hidden_track_or_disabled_does_not_count():
    assert rules(seq([clip(0, 10)], [clip(0, 4, FEED)], muted={1})) == []
    assert rules(seq([clip(0, 10)], [clip(0, 4, FEED, disabled=True)])) == []


def test_a_premiere_frame_hold_on_the_feed_is_not_moving():
    assert rules(seq([clip(0, 10)], [clip(0, 4, FEED, frame_hold=12.0)])) == []


def test_interview_footage_is_not_race_broadcast():
    s = seq([clip(0, 30)], [clip(0, 30, "2026 MAX VERSTAPPEN STEALS THE SHOW! VEGAS GP DRIVERS PRESS CONFERENCE.mp4")])
    assert check_sequence(s) == []


def test_a_clip_rendered_into_assets_counts_as_race_video():
    render = clip(0, 4, "crash_6755_i.mp4", media_path="E:\\Me\\2.Tasks\\ep\\6. ASSETS\\russell_wall\\crash_6755_i.mp4")
    assert rules(seq([clip(0, 10)], [render])) == ["moving_video"]


def test_feed_pattern_can_be_named():
    s = seq([clip(0, 10)], [clip(0, 4, "2026-11-21 10-55-45.mp4")])
    assert rules(s) == []
    assert rules(s, feed="10-55-45") == ["moving_video"]


# Radio box from Russell wall v5: 190% at (475, 1091), lands at x 100-850, y 744-1438.
RADIO = motion((475 / 1080, 1091 / 1920), 190, anchor=(727.5 / 1080, 1282.5 / 1920),
               crop=(530 / 10.8, 1100 / 19.2, (1080 - 925) / 10.8, (1920 - 1465) / 19.2))


def test_box_inside_the_safe_zone_passes():
    assert rules(seq([clip(0, 10)], [hold(0, 10, effects=[RADIO])])) == []


def test_box_to_y_1561_passes_and_past_it_is_flagged():
    def box_to(bottom):
        # 1080x1920 source at 100%, centred on x; cropped to x 100-850, y 1000-bottom.
        return hold(0, 10, effects=[motion((0.5, 0.5), 100, crop=(100 / 10.8, 1000 / 19.2, 230 / 10.8,
                                                                    (1920 - bottom) / 19.2))])
    assert rules(seq([clip(0, 10)], [box_to(1561)])) == []
    flags = check_sequence(seq([clip(0, 10)], [box_to(1600)]))
    assert [f["rule"] for f in flags] == ["safe_zone"]
    assert flags[0]["box"] == [100, 1000, 850, 1600]


def test_box_under_the_right_buttons_is_flagged():
    box = hold(0, 10, effects=[motion((0.5, 0.5), 100, crop=(500 / 10.8, 1000 / 19.2, 100 / 10.8, 600 / 19.2))])
    assert rules(seq([clip(0, 10)], [box])) == ["safe_zone"]


def test_full_width_feed_crop_is_not_a_box():
    feed = clip(0, 2, FEED, effects=[motion((0.5, 0.69), 173, crop=(0, 16.7, 0, 0))])
    assert rules(seq([clip(0, 10)], [feed])) == []


def test_title_that_ends_off_a_cut_is_flagged():
    flags = check_sequence(seq([clip(0, 3), clip(3, 10)], [text(0, 3.5, "RUS ชนกำแพง")]))
    assert [f["rule"] for f in flags] == ["title_on_cut"]
    assert flags[0]["text"] == "RUS ชนกำแพง"


def test_subtitles_and_labels_may_end_anywhere():
    s = seq([clip(0, 3), clip(3, 10)], [text(0, 3, "title"), text(3.2, 4.1, "subtitle"), text(5.5, 6.3, "RUS")])
    assert check_sequence(s) == []


def test_a_parking_gap_splits_two_shorts_and_is_not_flagged():
    s = seq([clip(0, 20), clip(80, 100)],
            [text(0, 20, "first title"), text(80, 85, "second title"), text(90, 91.5, "subtitle")])
    flags = check_sequence(s)
    assert [(f["rule"], f["short"]) for f in flags] == [("title_on_cut", [80.0, 100.0])]
