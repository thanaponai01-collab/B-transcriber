"""The word timeline moved to ``transcribe.words`` (transcribe must not import cutdeck).

This re-export keeps ``cutdeck.words`` imports working until the open branches merge; then
point the importers at ``transcribe.words`` and delete it. A patch on ``cutdeck.words.X``
does not reach the code: patch ``transcribe.words.X``.
"""

from transcribe.words import Piece, TimedToken, Word, timed_tokens, words_for_job, words_from_pieces

__all__ = ["Piece", "TimedToken", "Word", "timed_tokens", "words_for_job", "words_from_pieces"]
