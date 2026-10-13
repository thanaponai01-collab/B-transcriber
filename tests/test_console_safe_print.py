"""transcribe.console.safe_print — Thai output must never crash a CLI.

Every real media path in this project is Thai. On Windows a *redirected* stdout
(a pipe, a `> log.txt`, a CI capture) inherits the ANSI code page rather than
UTF-8, and `print()` of a Thai path then raises UnicodeEncodeError. Where that
print is a success announcement — after the artifact is written and the DB row
committed — the process dies with exit 1 on work that fully succeeded.

The unit tests pin the three degradation steps individually.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from transcribe.console import safe_print

THAI = "โหน(หลัง)กระแส"
ROOT = Path(__file__).resolve().parent.parent


def _cp1252_stream() -> io.TextIOWrapper:
    """A text stream that behaves like a piped stdout on a cp1252 host."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")


class _NoBufferStream(io.TextIOWrapper):
    """A cp1252 text stream with no reachable binary buffer — forces step 3."""

    @property
    def buffer(self):  # type: ignore[override]
        raise AttributeError("buffer")


# ── the defect itself ─────────────────────────────────────────────────────────

def test_plain_print_really_does_crash_on_thai():
    """Guards the other tests from going vacuous: if a future Python stops
    raising here, safe_print's fallbacks are no longer being exercised."""
    stream = _cp1252_stream()
    with pytest.raises(UnicodeEncodeError):
        print(f"wrote D:/footage/{THAI}/cut.xml", file=stream)


# ── step 1: the normal path ───────────────────────────────────────────────────

def test_utf8_stream_takes_the_normal_path_unchanged():
    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    safe_print(f"wrote {THAI}.srt", file=stream)
    stream.flush()
    assert stream.buffer.getvalue().decode("utf-8") == f"wrote {THAI}.srt\n"


def test_ascii_on_a_cp1252_stream_is_untouched():
    stream = _cp1252_stream()
    safe_print("wrote plain.xml (9 keep clips)", file=stream)
    stream.flush()
    assert stream.buffer.getvalue().decode("cp1252") == "wrote plain.xml (9 keep clips)\n"


# ── step 2: readable UTF-8 bytes rather than a mangled path ───────────────────

def test_thai_on_a_cp1252_stream_does_not_raise_and_stays_readable():
    """The point of the message is a path the user must go find, so the Thai is
    preserved rather than replaced with '?' — see transcribe/console.py."""
    stream = _cp1252_stream()
    safe_print(f"wrote D:/footage/{THAI}/cut.xml (146 keep clips)", file=stream)

    written = stream.buffer.getvalue().decode("utf-8")
    assert THAI in written
    assert "?" not in written


def test_earlier_text_output_is_not_reordered_behind_the_raw_write():
    """Step 2 bypasses the text wrapper, so the wrapper must be flushed first or
    an already-buffered ASCII line would surface *after* the Thai one."""
    stream = _cp1252_stream()
    safe_print("first line", file=stream)          # step 1, may sit in the wrapper
    safe_print(f"second {THAI}", file=stream)      # step 2, writes raw bytes
    stream.flush()

    written = stream.buffer.getvalue().decode("utf-8")
    assert written.index("first line") < written.index(THAI)


# ── step 3: the never-crash floor ─────────────────────────────────────────────

def test_stream_without_a_buffer_degrades_lossily_but_never_raises():
    raw = io.BytesIO()
    stream = _NoBufferStream(raw, encoding="cp1252", newline="")
    safe_print(f"wrote {THAI}.xml", file=stream)
    stream.flush()

    written = raw.getvalue().decode("cp1252")
    assert "?" in written          # lossy, as designed
    assert written.endswith(".xml\n")


# ── the same wall at the other process boundary ───────────────────────────────
#
# Found while verifying the ladder above, not reported separately: subprocess's
# `text=True` decodes a child's output with the *locale* codec, and ffmpeg and
# ffprobe both emit UTF-8. Thai 'ก' is E0 B8 81; 0x81 is one of cp1252's five
# undefined bytes, so a Thai media path echoed in ffprobe's stderr kills the
# reader thread. stdout survives on its own thread — so frame rates were never
# silently wrong — but `.stderr` becomes None and the real error is destroyed.

_THAI_WITH_KO_KAI = "กระแส"          # 'ก' = E0 B8 81 — the byte cp1252 rejects


def _emit_script(tmp: Path) -> Path:
    """A stand-in for ffprobe: JSON on stdout, a Thai warning on stderr."""
    script = tmp / "emit.py"
    script.write_text(
        "import sys\n"
        'sys.stdout.buffer.write(b\'{"streams":[{"width":1920,"height":1080}]}\')\n'
        f'sys.stderr.buffer.write("warn {_THAI_WITH_KO_KAI}".encode("utf-8"))\n',
        encoding="utf-8")
    return script


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_locale_decoding_really_does_destroy_thai_stderr():
    """Pins the defect the fix addresses, so the next test can't go vacuous.

    The suppressed warning IS the defect: subprocess's reader thread dies with
    UnicodeDecodeError. Suppressed here only because this test provokes it
    deliberately — anywhere else in the suite it should stay loud.
    """
    script = _emit_script(Path(tempfile.mkdtemp()))
    proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, encoding="cp1252")
    assert proc.returncode == 0
    assert proc.stdout                      # stdout is on its own thread, unharmed
    assert proc.stderr is None              # ...but the error message is gone


def test_explicit_utf8_decoding_preserves_thai_stderr():
    script = _emit_script(Path(tempfile.mkdtemp()))
    proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0
    assert proc.stdout
    assert proc.stderr is not None
    assert _THAI_WITH_KO_KAI in proc.stderr


@pytest.mark.parametrize("module,func", [
    ("transcribe.timebase", "_ffprobe"),
])
def test_ffprobe_callers_pin_their_decoding(module, func):
    """The shipping ffprobe callers must not leave decoding to the locale."""
    import importlib
    import inspect
    src = inspect.getsource(getattr(importlib.import_module(module), func))
    assert 'encoding="utf-8"' in src, f"{module}.{func} still decodes by locale"
