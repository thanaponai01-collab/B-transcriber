"""hks_cache.trim drops whole least-recently-used groups until the caches fit, never recent ones."""
import os
import time

from cutdeck import hks_cache


def _file(path, size, age_days):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))
    return path


def test_trim_drops_the_biggest_groups_whole_until_under_the_limit(tmp_path, monkeypatch):
    big = [_file(tmp_path / "hks_cutpoints" / f"a.{s}", 100, 3) for s in ("npz", "thumbs", "pairs")]
    middle = [_file(tmp_path / "hks_layout" / "b.layout.npy", 50, 5)]
    small = [_file(tmp_path / "hks_turns" / "c h0.25.npz", 10, 9)]  # oldest, but tiny: kept
    hks_cache.trim(tmp_path, limit=100)  # 360 bytes: dropping the 300-byte group is enough
    assert not any(p.exists() for p in big)
    assert all(p.exists() for p in middle + small)
    hks_cache.trim(tmp_path, limit=20)
    assert not middle[0].exists() and small[0].exists()


def test_trim_keeps_groups_used_in_the_last_day_even_over_the_limit(tmp_path, monkeypatch):
    old = _file(tmp_path / "hks_breaks" / "a.mel32v1.npz", 100, 2)
    fresh = _file(tmp_path / "hks_breaks" / "b.mel32v1.npz", 100, 0.1)
    hks_cache.trim(tmp_path, limit=0)
    assert not old.exists() and fresh.exists()


def test_touch_makes_a_group_recent_again(tmp_path, monkeypatch):
    used = _file(tmp_path / "hks_audit" / "a.clock.npy", 100, 9)
    unused = _file(tmp_path / "hks_audit" / "b.clock.npy", 100, 5)
    hks_cache.touch(used)
    hks_cache.trim(tmp_path, limit=150)
    assert used.exists() and not unused.exists()


def test_a_group_loses_its_small_index_before_its_data(tmp_path, monkeypatch):
    index = _file(tmp_path / "hks_cutpoints" / "a.npz", 10, 9)
    data = _file(tmp_path / "hks_cutpoints" / "a.thumbs", 1000, 9)
    real_unlink = type(data).unlink

    def unlink(self, *a, **k):  # the data file is held open (a memmap): only the index goes
        if self.name == "a.thumbs":
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(type(data), "unlink", unlink)
    hks_cache.trim(tmp_path, limit=0)
    assert not index.exists() and data.exists()


def test_trim_leaves_caches_outside_its_root_alone(tmp_path):
    other = _file(tmp_path / "default" / "hks_layout" / "a.layout.npy", 100, 9)
    hks_cache.trim(tmp_path / "custom", limit=0)
    assert other.exists()
