"""4.3 cover finder (cutdeck/hks_covers.py): same moment first, then the story, then a hold."""

from cutdeck import hks_covers as c

LAYOUT = [[0, 100, "studio"], [100, 130, "clip"], [130, 200, "studio"], [200, 260, "footage"], [300, 340, "clip"]]
TOPICS = [{"start": 0, "story": 1}, {"start": 150, "story": 1}, {"start": 280, "story": 2}]


def test_stories_run_to_the_next_story():
    assert c.story_spans(TOPICS, 400) == [(0, 280, 1), (280, 400, 2)]


def test_candidates_stay_in_the_story_and_rank_the_nearest_first():
    got = c.candidates(190.0, LAYOUT, c.story_spans(TOPICS, 400))
    assert [g["kind"] for g in got] == ["same_moment", "same_story", "hold"]
    assert got[0]["source_in"] == 200.0 and got[0]["source_out"] == 202.0   # the footage run next to the cut
    assert 100 <= got[1]["source_in"] and got[1]["source_out"] <= 130        # the story's other clip run
    assert not any(300 <= g["source_in"] for g in got)                       # story 2's clip is not offered


def test_no_picture_in_the_story_gives_no_candidate():
    assert c.candidates(50.0, [[0, 400, "studio"]], c.story_spans(TOPICS, 400)) == []
