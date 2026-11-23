"""The draft as a build request (cutdeck/hks_assemble.py): the offline check catches a broken body."""

from cutdeck import hks_assemble as asm
from cutdeck.hks_build import ticks


def _item(at, a, b, v=0):
    return {"at_ticks": ticks(at), "in_ticks": ticks(a), "out_ticks": ticks(b), "v": v, "a": 0 if v == 0 else None}


def test_a_gap_in_the_body_or_a_bare_cut_is_reported():
    bed = {**_item(0, 0, 20), "v": None, "a": 4}
    good = {"show_end": 20.0, "covers": [(10.0, "same_moment")],
            "items": [_item(0, 100, 110), _item(10, 200, 210), _item(9, 50, 52, v=1), bed]}
    assert asm.check(good) == []
    gap = {**good, "items": [_item(0, 100, 110), _item(11, 200, 209), _item(9, 50, 52, v=1), bed]}
    assert any("gap" in p for p in asm.check(gap))
    bare = {**good, "items": [_item(0, 100, 110), _item(10, 200, 210), bed]}
    assert any("no cover" in p for p in asm.check(bare))
