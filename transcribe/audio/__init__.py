"""Shared audio preparation — concerns that sit *before* any model.

Anything two engine adapters both need in order to turn an audio array into
something decodable belongs here, not in whichever adapter happened to grow it
first. The Engine Contract says engines do not know about each other; this
package is where the things they legitimately share go instead.
"""

from transcribe.audio.windows import Window, WindowPolicy, speech_windows

__all__ = ["Window", "WindowPolicy", "speech_windows"]
