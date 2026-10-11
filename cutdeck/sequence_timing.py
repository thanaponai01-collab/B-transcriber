"""Exact Premiere tick/frame conversions and analysis-window timing."""
from fractions import Fraction
from cutdeck.contracts import Timebase

PPRO_TICKS_PER_SECOND = 254016000000


class SequenceRefusal(ValueError):
    """The sequence cannot be analysed or edited safely."""


def frame_to_ticks(frame: int, tb: Timebase) -> int:
    exact = Fraction(frame * PPRO_TICKS_PER_SECOND * tb.fps_den, tb.fps_num)
    return exact.numerator // exact.denominator


def range_window_frames(tb: Timebase, seq_frames: int, frame_range: tuple[int, int],
                        pad_seconds: float = 2.0) -> tuple[int, int]:
    """Sequence-frame window ``[lo, hi]`` = the In/Out range plus ``pad_seconds``
    of context each side, clamped to the sequence. The pad is defined in seconds
    so the recognizer gets the same context at any frame rate."""
    pad = int(round(pad_seconds * tb.fps_num / tb.fps_den))
    return max(0, frame_range[0] - pad), min(seq_frames, frame_range[1] + pad)


def ticks_per_frame(tb: Timebase) -> int:
    """Premiere ticks per frame, exact. The panel does all cut math in integer ticks,
    so a frame rate whose frame isn't a whole number of ticks is refused."""
    per_frame, remainder = divmod(PPRO_TICKS_PER_SECOND * tb.fps_den, tb.fps_num)
    if remainder:
        raise SequenceRefusal(f"frame rate {tb.fps_num}/{tb.fps_den} is not a whole number "
                              f"of Premiere ticks per frame")
    return per_frame
