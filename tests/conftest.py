"""`live` tests need a real Premiere + CutDeck helper + panel. They are left out of every normal
run (so nothing skips silently) and run only with `--live`, where a missing piece FAILS."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="also run tests marked live (real Premiere, helper and panel)")
    parser.addoption("--live-edit", action="store_true", default=False,
                     help="let live tests edit the clips currently selected in Premiere")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs live Premiere + helper + panel; run with --live")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    keep, dropped = [], []
    for item in items:
        (dropped if item.get_closest_marker("live") else keep).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep
