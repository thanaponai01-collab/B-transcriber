"""`live` tests need a real Premiere + CutDeck helper + panel. They are left out of every normal
run (so nothing skips silently) and run only with `--live`, where a missing piece FAILS."""
import os
import tempfile

import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="also run tests marked live (real Premiere, helper and panel)")
    parser.addoption("--live-edit", action="store_true", default=False,
                     help="let live tests edit the clips currently selected in Premiere")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs live Premiere + helper + panel; run with --live")


@pytest.fixture(autouse=True, scope="session")
def _temp_in_pytest_dir(tmp_path_factory):
    """Every temp file a test or the code under test makes lands in pytest's own folder, which
    pytest prunes to the last 3 runs, instead of piling up in %TEMP%. Child processes follow."""
    tmp = str(tmp_path_factory.mktemp("tempdir"))
    saved = {k: os.environ.get(k) for k in ("TMP", "TEMP", "TMPDIR")}
    saved_tempdir = tempfile.tempdir
    os.environ.update(TMP=tmp, TEMP=tmp, TMPDIR=tmp)
    tempfile.tempdir = tmp
    yield
    tempfile.tempdir = saved_tempdir
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    keep, dropped = [], []
    for item in items:
        (dropped if item.get_closest_marker("live") else keep).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep
