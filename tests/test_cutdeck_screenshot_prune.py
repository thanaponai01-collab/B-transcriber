"""capture() without an output path keeps only the newest screenshots in %TEMP%."""
import os

from PIL import Image

from cutdeck import screenshot


def test_capture_keeps_only_the_newest_screenshots(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshot.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(screenshot, "window_pixels", lambda: Image.new("RGB", (4, 4)))
    for i in range(screenshot.KEEP + 5):  # older shots, named by their ms time like capture's
        (tmp_path / f"cutdeck-premiere-{1700000000000 + i}.png").write_bytes(b"x")
    other = tmp_path / "keep-me.png"
    other.write_bytes(b"x")

    shot = screenshot.capture()

    left = sorted(tmp_path.glob("cutdeck-premiere-*.png"))
    assert len(left) == screenshot.KEEP
    assert str(tmp_path / os.path.basename(shot["path"])) in map(str, left)
    assert not (tmp_path / "cutdeck-premiere-1700000000000.png").exists()
    assert other.exists()


def test_capture_to_a_chosen_path_deletes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshot, "window_pixels", lambda: Image.new("RGB", (4, 4)))
    for i in range(screenshot.KEEP + 5):
        (tmp_path / f"cutdeck-premiere-{i}.png").write_bytes(b"x")
    screenshot.capture(str(tmp_path / "mine.png"))
    assert len(list(tmp_path.glob("cutdeck-premiere-*.png"))) == screenshot.KEEP + 5
