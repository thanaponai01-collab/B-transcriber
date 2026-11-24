"""Word-start alignment: re-time each engine word's start against the audio with a Thai CTC model.

Whisper's word times come from its attention, which lands a word start within one 25 fps frame
of the real onset only about half the time (``transcribe.eval.timing``). A CTC acoustic model
scores every 20 ms frame against every letter, so forced alignment of the engine's own text
finds where each word actually begins.

Times only: the text never changes. Only starts move. CTC ends stop before a syllable's sound
fades (measured 168 ms early), so ends stay the engine's, kept after the new start. Characters
the model has no letter for (Latin, digits) are skipped; a word with none keeps its times.

Runs after Engine A is unloaded (one model on the GPU at a time). Each cue is aligned in its
own window, padded by ``pad_ms``, so a long file never goes through the model at once.
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# (lo_ms, hi_ms, word texts) -> each word's (start_ms, end_ms), or None where nothing aligned
AlignWindow = Callable[[int, int, list[str]], list[tuple[float, float] | None]]

DEFAULT_MODEL = "sakares/wav2vec2-large-xlsr-thai-demo"


def retime_starts(words: list[dict], cues: list, align: AlignWindow, pad_ms: int, duration_ms: int) -> list[dict]:
    """New word dicts with aligned starts. ``cues`` give the windows: each word goes with the cue
    its start falls in. Starts never go backwards, and every word keeps at least 1 ms."""
    out = [dict(w) for w in words]
    for c in cues:
        idx = [i for i, w in enumerate(words) if c.start_ms <= w["start_ms"] < c.end_ms]
        if not idx:
            continue
        lo, hi = max(c.start_ms - pad_ms, 0), min(c.end_ms + pad_ms, duration_ms)
        for i, span in zip(idx, align(lo, hi, [words[i]["text"] for i in idx])):
            if span is not None:
                out[i]["start_ms"] = int(round(span[0]))
    prev = 0
    for w in out:
        w["start_ms"] = max(w["start_ms"], prev)
        w["end_ms"] = max(w["end_ms"], w["start_ms"] + 1)
        prev = w["start_ms"]
    return out


def retime_cue_starts(cues: list, old_words: list[dict], new_words: list[dict]) -> None:
    """In place: each cue starts where its first word now starts, never before the previous
    cue's end and never at or past its own end."""
    prev_end = 0
    for c in cues:
        firsts = [n["start_ms"] for o, n in zip(old_words, new_words) if c.start_ms <= o["start_ms"] < c.end_ms]
        if firsts:
            c.start_ms = min(max(firsts[0], prev_end), c.end_ms - 1)
        prev_end = c.end_ms


class ThaiCTCAligner:
    """A Hugging Face wav2vec2 CTC model with a Thai letter vocabulary, as an ``AlignWindow``."""

    def __init__(self, audio: np.ndarray, sr: int, model: str = DEFAULT_MODEL, device: str = "cuda"):
        self._audio, self._sr, self._name, self._device = audio, sr, model, device
        self._model = self._proc = None

    def load(self) -> None:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        self._proc = Wav2Vec2Processor.from_pretrained(self._name)
        model = Wav2Vec2ForCTC.from_pretrained(self._name).eval().to(self._device)
        self._model = model.half() if self._device == "cuda" else model
        self._vocab = self._proc.tokenizer.get_vocab()
        self._blank = self._proc.tokenizer.pad_token_id

    def unload(self) -> None:
        import torch
        self._model = self._proc = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def __call__(self, lo_ms: int, hi_ms: int, texts: list[str]) -> list[tuple[float, float] | None]:
        import torch
        import torchaudio
        ids, owner = [], []
        for wi, text in enumerate(texts):
            for ch in text:
                if ch in self._vocab and self._vocab[ch] != self._blank:
                    ids.append(self._vocab[ch])
                    owner.append(wi)
        seg = self._audio[lo_ms * self._sr // 1000:hi_ms * self._sr // 1000]
        if not ids or len(seg) < self._sr // 10:
            return [None] * len(texts)
        x = self._proc(seg, sampling_rate=self._sr, return_tensors="pt").input_values.to(self._device)
        with torch.inference_mode():
            logits = self._model(x.half() if self._device == "cuda" else x).logits.float()
        lp = torch.log_softmax(logits, -1)
        if len(ids) > lp.shape[1]:
            return [None] * len(texts)
        try:
            path, _ = torchaudio.functional.forced_align(lp, torch.tensor([ids], device=lp.device), blank=self._blank)
        except RuntimeError as e:  # more letters than the window can hold once repeats need blanks
            logger.info("word_align: window %d-%d ms not aligned (%s)", lo_ms, hi_ms, e)
            return [None] * len(texts)
        frame_ms = (hi_ms - lo_ms) / lp.shape[1]
        spans: dict[int, tuple[int, int]] = {}
        k, prev = -1, self._blank
        for f, tok in enumerate(path[0].tolist()):
            if tok != self._blank:
                if tok != prev:
                    k += 1
                w = owner[k]
                s, e = spans.get(w, (f, f))
                spans[w] = (min(s, f), max(e, f))
            prev = tok
        return [(lo_ms + spans[i][0] * frame_ms, lo_ms + (spans[i][1] + 1) * frame_ms) if i in spans else None
                for i in range(len(texts))]
