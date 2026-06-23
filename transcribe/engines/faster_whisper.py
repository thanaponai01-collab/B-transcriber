"""Engine — faster-whisper (CTranslate2) backend.

Same Whisper checkpoint family as whisper_thai, but run through CTranslate2 instead
of HuggingFace transformers: typically 3-4x faster and lower VRAM at equal accuracy,
which is why it's the default Engine A on the 8GB card. Needs a CT2-converted model
dir (produced once by `ct2-transformers-converter`, see README); it cannot load a raw
HF checkpoint.

CTranslate2 exposes the real Whisper anti-hallucination knobs the HF pipeline buried:
condition_on_previous_text=False stops loops propagating across windows, and the
compression/log-prob/no-speech thresholds drop garbage segments outright.
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register

logger = logging.getLogger(__name__)

# Converted once via ct2-transformers-converter (see README). Repo-root-relative so
# it resolves regardless of the caller's cwd.
_DEFAULT_MODEL = str(Path(__file__).resolve().parents[2] / "models" / "whisper-th-medium-ct2")

# Phrase-cue grouping. ponytail: fixed heuristics — break on a speech gap, or once a
# cue reaches target length/duration. Tune here if cues read too long/short; gap_ms
# matches the pipeline's segment.gap_ms default (700 ms), target_chars/target_ms are
# subtitle-line sizing.
_CUE_GAP_MS = 700
_CUE_TARGET_MS = 4000
_CUE_TARGET_CHARS = 42


def _group_words_into_cues(words, gap_ms=_CUE_GAP_MS, target_ms=_CUE_TARGET_MS,
                           target_chars=_CUE_TARGET_CHARS):
    """Group Whisper word-pieces into subtitle-length phrase cues at real word boundaries.

    `words` is a list of (text, start_ms, end_ms). Whisper word-pieces for spaceless
    Thai are sub-word and only sporadically carry a leading space, so they cannot be
    used to find word boundaries — a long spaceless run would never break. Instead we
    rebuild the full text with a per-character timeline, segment it with pythainlp
    (Latin/whitespace preserved), and group whole words into cues. A new cue starts on
    a silence gap >= gap_ms or once the cue reaches target_ms / target_chars.
    Returns list of (text, start_ms, end_ms).
    """
    from pythainlp.tokenize import word_tokenize

    # 1. per-character timeline (each char inherits its source piece's span)
    chartime: list[tuple[int, int]] = []
    chars: list[str] = []
    for txt, s, e in words:
        for ch in txt:
            chars.append(ch)
            chartime.append((s, e))
    if not chars:
        return []

    # 2. real word boundaries (pythainlp keeps Latin runs and spaces intact)
    toks = word_tokenize("".join(chars), keep_whitespace=True)

    # 3. map each token back to its time span via the char timeline
    timed: list[tuple[str, int, int]] = []
    pos = 0
    for t in toks:
        start = chartime[pos][0]
        end = chartime[pos + len(t) - 1][1]
        pos += len(t)
        timed.append((t, start, end))

    # 4. greedy group whole words into cues. Whitespace tokens are buffered and only
    # kept once a real word follows in the same cue, so a cue never starts or ends on
    # whitespace (a trailing space carries the next word's timing and would corrupt
    # the cue's end time and the gap check).
    cues: list[tuple[str, int, int]] = []
    cur: list[tuple[str, int, int]] = []
    pending_ws: list[tuple[str, int, int]] = []

    def _close():
        text = "".join(x[0] for x in cur).strip()
        if text:
            cues.append((text, cur[0][1], cur[-1][2]))

    for t, s, e in timed:
        if not t.strip():
            if cur:
                pending_ws.append((t, s, e))
            continue
        if cur:
            gap = s - cur[-1][2]
            span = e - cur[0][1]
            n_chars = len("".join(x[0] for x in cur).strip())
            if gap >= gap_ms or span > target_ms or n_chars >= target_chars:
                _close()
                cur = []
        if cur:
            cur.extend(pending_ws)  # interior whitespace only
        pending_ws = []
        cur.append((t, s, e))
    if cur:
        _close()
    return cues


@register("faster_whisper")
class FasterWhisperEngine(Engine):
    """Thai-specialist Whisper via CTranslate2."""

    prefers_whole_file = True

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda",
                 compute_type: str | None = None):
        self._model_id = model_id
        self._device = device
        # compute_type override lets an 8GB card fall back to int8_float16 if a
        # large model OOMs at float16. None → pick a sane default per device.
        self._compute_type = compute_type
        self._model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        compute_type = self._compute_type or ("float16" if self._device != "cpu" else "int8")
        logger.info("Loading FasterWhisper: %s (%s)", self._model_id, compute_type)
        self._model = WhisperModel(self._model_id, device=self._device, compute_type=compute_type)
        logger.info("FasterWhisper loaded on %s", self._device)

    def _load_array(self, inp: EngineInput):
        if inp.audio is not None:
            return inp.audio
        import librosa
        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)
        return audio

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        audio = self._load_array(inp)

        # bias terms ride in as initial_prompt (CT2's native biasing channel).
        initial_prompt = " ".join(inp.bias_terms) if inp.bias_terms else None

        # word_timestamps gives per-word boundaries so we can cut ~30s Whisper
        # segments down to subtitle-length phrase cues. The pieces are sub-word for
        # spaceless Thai, but _group_words_into_cues re-joins them — we never emit a
        # raw per-character token.
        segments, _info = self._model.transcribe(
            audio,
            language=inp.language_hint or "th",
            task="transcribe",
            initial_prompt=initial_prompt,
            beam_size=5,
            word_timestamps=True,
            # vad_filter: faster-whisper's own VAD skips music/silence on the full
            # track — this is what kills the hallucination loops at the source.
            vad_filter=True,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )

        words = []
        for seg in segments:  # generator — consuming it runs inference
            for w in (seg.words or []):
                if w.word.strip():  # keep w.word verbatim (its leading space marks the word boundary)
                    words.append((w.word, int(w.start * 1000), int(w.end * 1000)))

        tokens = [
            RecognizedToken(
                text=text, start_ms=start, end_ms=end,
                confidence=None, script=detect_script(text),
            )
            for text, start, end in _group_words_into_cues(words)
        ]

        return EngineResult(
            tokens=tokens,
            engine_name="faster_whisper",
            word_level_timestamps=True,  # phrase cues are final; skip re-align
            raw={},
        )

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        gc.collect()
        logger.info("FasterWhisper unloaded, VRAM freed")
