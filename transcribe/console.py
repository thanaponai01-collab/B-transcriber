"""console.py — printing that survives a non-UTF-8 stdout.

Every media path in this project is Thai, and on Windows a redirected or piped
stdout inherits the ANSI code page (cp1252 on this machine), not UTF-8. A plain
``print()`` of a Thai path therefore raises ``UnicodeEncodeError`` and kills the
process. Where that print is a CLI's *success* announcement — after the file is
written and the DB row committed — the crash reports failure for work that
completed: exit code 1, a traceback, and a user or wrapper script that concludes
the export did not happen. That is the failure this module exists to prevent.

``safe_print`` degrades in three steps, in this order:

1. ``print()`` — the normal path; a UTF-8 stream or a Windows console (which
   Python drives through the Unicode API regardless of code page) takes it.
2. UTF-8 bytes straight to the stream's binary buffer. Chosen over lossy
   re-encoding because the message is usually **a path the user must go find**;
   a ``???`` path is technically printed and practically useless. The declared
   encoding is knowingly bypassed — cp1252 cannot represent the text at all, so
   there is no faithful alternative, only a readable one and an unreadable one.
3. Lossy re-encode with ``errors="replace"`` — the never-crash floor, for a
   stream with no accessible buffer (pytest capture, some wrappers).

Deliberately does **not** call ``sys.stdout.reconfigure()``: that mutates
process-global state a library has no business owning, is documented as
unsupported on Windows console streams, and would silently change the encoding
seen by every other writer in the process.

Owned here rather than in whichever module hit it first — this is the same rule
CLAUDE.md states for engine adapters, applied to CLI concerns. The original
instance lived as ``transcribe.eval.harness._safe_print``; it now delegates here.
"""

from __future__ import annotations

import sys
from typing import Optional, TextIO

__all__ = ["safe_print"]


def safe_print(msg: str, *, file: Optional[TextIO] = None) -> None:
    """``print(msg)``, but never raises ``UnicodeEncodeError``.

    Takes a single pre-formatted string rather than ``print``'s varargs: the
    fallbacks re-emit the whole message as one unit, and multiple arguments
    would let a stream fail partway through a line.
    """
    stream = file if file is not None else sys.stdout

    try:
        print(msg, file=stream)
        return
    except UnicodeEncodeError:
        pass

    # Step 2 — readable bytes. Flush the text wrapper first so the raw write
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

    # Step 3 — lossy, but printed.
    encoding = getattr(stream, "encoding", None) or "utf-8"
    print(msg.encode(encoding, errors="replace").decode(encoding, errors="replace"),
          file=stream)
