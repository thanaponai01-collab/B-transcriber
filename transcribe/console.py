"""Every media path in this project is Thai, and on Windows a redirected or piped
stdout inherits the ANSI code page (cp1252 on this machine), not UTF-8. A plain
``print()`` of a Thai path therefore raises ``UnicodeEncodeError`` and kills the
process.

``safe_print`` degrades in three steps, in this order:

1. ``print()`` — the normal path; a UTF-8 stream or a Windows console (which
   Python drives through the Unicode API regardless of code page) takes it.
2. UTF-8 bytes straight to the stream's binary buffer.
3. Lossy re-encode with ``errors="replace"`` — the never-crash floor, for a
   stream with no accessible buffer (pytest capture, some wrappers).
"""

from __future__ import annotations

import sys
from typing import Optional, TextIO

__all__ = ["safe_print"]


def safe_print(msg: str, *, file: Optional[TextIO] = None) -> None:
    """``print(msg)``, but never raises ``UnicodeEncodeError``.
    """
    stream = file if file is not None else sys.stdout

    try:
        print(msg, file=stream)
        return
    except UnicodeEncodeError:
        pass

    # Flush the text wrapper first so the raw write
    # cannot land ahead of output already buffered above it.
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        try:
            stream.flush()
            buffer.write((msg + "\n").encode("utf-8"))
            buffer.flush()
            return
        except Exception:
            pass

    encoding = getattr(stream, "encoding", None) or "utf-8"
    print(msg.encode(encoding, errors="replace").decode(encoding, errors="replace"),
          file=stream)
