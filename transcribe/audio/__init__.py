"""Shared audio preparation — concerns that sit *before* any model.

Anything two engine adapters both need in order to turn an audio array into
something decodable belongs here, not in whichever adapter happened to grow it
first. The Engine Contract says engines do not know about each other; this
package is where the things they legitimately share go instead — and, read the
other direction, no module under `transcribe/engines/` may import
`transcribe.pipeline` (issue #13; enforced by
`tests/test_engine_contract_import_direction.py`). This package stays
importable without torch or CTranslate2 so that holds without a GPU.

This is also where the overlap/dedup invariant lives as a single unit rather
than a warning addressed to callers: `windows.py`'s `WindowPolicy.overlap_s`
decides how much consecutive decode windows of an over-long span share, and
`stitch.py` removes the duplicate words that sharing produces. `decode.py`'s
`decode_windows` composes the two, so a caller windowing audio with a nonzero
overlap gets seam-dedupe in the same call — it cannot get one half without
the other.
"""

from transcribe.audio.decode import AudioWindow, decode_windows
from transcribe.audio.stitch import ChunkTokens, stitch
from transcribe.audio.windows import Window, WindowPolicy, speech_windows

__all__ = [
    "Window", "WindowPolicy", "speech_windows",
    "ChunkTokens", "stitch",
    "AudioWindow", "decode_windows",
]
