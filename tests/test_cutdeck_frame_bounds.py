"""cutdeck.frame_bounds and the helper's `frame_bounds` request: the box where a clip is drawn,
from a frame saved with the clip on and one with it off (Transform panel, graphics)."""

import asyncio
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from cutdeck import frame_bounds
from cutdeck.xml_bridge import XmlJobs


def _frames(folder, background=(0, 0, 0, 0)):
    """A frame with another clip in the middle, and the same frame plus 'our' clip bottom-left."""
    off = Image.new("RGBA", (1920, 1080), background)
    ImageDraw.Draw(off).rectangle([609, 584, 1027, 670], fill=(255, 255, 255, 255))
    on = off.copy()
    ImageDraw.Draw(on).rectangle([11, 904, 428, 990], fill=(250, 250, 250, 255))
    on_path, off_path = folder / "on.png", folder / "off.png"
    on.save(on_path)
    off.save(off_path)
    return str(on_path), str(off_path)


def test_box_is_only_the_clip_that_was_switched_off(tmp_path):
    on, off = _frames(tmp_path)
    assert frame_bounds.drawn_bounds(on, off) == {"left": 11, "top": 904, "right": 429, "bottom": 991}


def test_box_is_found_over_an_opaque_background_too(tmp_path):
    on, off = _frames(tmp_path, background=(30, 60, 90, 255))
    assert frame_bounds.drawn_bounds(on, off) == {"left": 11, "top": 904, "right": 429, "bottom": 991}


def test_invisible_colour_in_transparent_pixels_is_ignored(tmp_path):
    on, off = _frames(tmp_path)
    image = Image.open(off)
    image.putpixel((5, 950), (200, 10, 10, 0))  # fully transparent, different hidden colour
    image.save(off)
    assert frame_bounds.drawn_bounds(on, off) == {"left": 11, "top": 904, "right": 429, "bottom": 991}


def test_render_noise_in_another_clip_is_ignored(tmp_path):
    # Live 2026-09-24: 3 pixels 1/255 apart inside another clip stretched the box to 0-1315.
    on, off = _frames(tmp_path, background=(30, 60, 90, 255))
    image = Image.open(on)
    for x in (1269, 1290, 1314):
        image.putpixel((x, 500), (31, 60, 90, 255))
    image.save(on)
    assert frame_bounds.drawn_bounds(on, off) == {"left": 11, "top": 904, "right": 429, "bottom": 991}


def test_faint_anti_aliased_edge_next_to_the_clip_still_counts(tmp_path):
    on, off = _frames(tmp_path, background=(30, 60, 90, 255))
    image = Image.open(on)
    for x in range(11, 429):
        image.putpixel((x, 903), (32, 61, 91, 255))  # a 2/255 edge row above the text
    image.save(on)
    assert frame_bounds.drawn_bounds(on, off) == {"left": 11, "top": 903, "right": 429, "bottom": 991}


def test_identical_frames_give_no_box(tmp_path):
    on, _ = _frames(tmp_path)
    assert frame_bounds.drawn_bounds(on, on) is None


def test_request_measures_and_keeps_only_the_latest_pair(tmp_path):
    on, off = _frames(tmp_path)
    result = asyncio.run(XmlJobs(tmp_path / "jobs").dispatch({"type": "frame_bounds", "on": on, "off": off}))
    assert result == {"bounds": {"left": 11, "top": 904, "right": 429, "bottom": 991}}
    assert not (tmp_path / "on.png").exists() and not (tmp_path / "off.png").exists()
    kept = tmp_path / "cutdeck-bounds-last-on.png", tmp_path / "cutdeck-bounds-last-off.png"
    assert all(path.exists() for path in kept)
    on, off = _frames(tmp_path)  # a second request replaces the kept pair
    asyncio.run(XmlJobs(tmp_path / "jobs").dispatch({"type": "frame_bounds", "on": on, "off": off}))
    assert all(path.exists() for path in kept) and not Path(on).exists()


@pytest.mark.parametrize("on", [None, "relative.png", "C:/nope/missing.png"])
def test_request_refuses_a_missing_frame(tmp_path, on):
    _, off = _frames(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(XmlJobs(tmp_path / "jobs").dispatch({"type": "frame_bounds", "on": on, "off": off}))
