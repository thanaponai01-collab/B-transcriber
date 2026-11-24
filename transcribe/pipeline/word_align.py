"""Word-start alignment: re-time each engine word's start against the audio with a Thai CTC model.

Whisper's word times come from its attention, which lands a word start within one 25 fps frame
of the real onset only about half the time (``transcribe.eval.timing``). A CTC acoustic model
scores every 20 ms frame against every letter, so forced alignment of the engine's own text
finds where each word actually begins.

Times only: the text never changes. Starts move. CTC ends stop before a syllable's sound
fades (measured 168 ms early), so ends stay the engine's, cut back only where the next word
now starts sooner; a cue touching the next one ends where that one now starts. A word the
model has no letters for (Latin, digits) keeps its times and bounds its neighbours' windows.
CTC fires on a letter's spike, late after a pause, so a start next to a pause then moves onto
the edge of the sound in the waveform (``snap_to_sound``).

Runs after Engine A is unloaded (one model on the GPU at a time). Each cue is aligned in its
own window, padded by ``pad_ms``, so a long file never goes through the model at once.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# (lo_ms, hi_ms, word texts) -> each word's (start_ms, end_ms), or None where nothing aligned
AlignWindow = Callable[[int, int, list[str]], list[tuple[float, float] | None]]

HUB_MODEL = "sakares/wav2vec2-large-xlsr-thai-demo"
DEFAULT_MODEL = "models/wav2vec2-th-ctc.pt"  # HUB_MODEL as a torchaudio checkpoint (export_checkpoint)


def levels_db(audio: np.ndarray, sr: int) -> np.ndarray:
    """RMS level in dB of each 10 ms hop (25 ms frames); frame f covers [10f, 10f + 25) ms."""
    hop, size = sr // 100, sr * 25 // 1000
    n = max(0, (len(audio) - size) // hop + 1)
    if not n:
        return np.zeros(0)
    frames = np.lib.stride_tricks.sliding_window_view(audio, size)[::hop][:n]  # a view, no copy
    ms = np.concatenate([(frames[i:i + 6000].astype(np.float64) ** 2).mean(axis=1)  # 1 min at a time
                         for i in range(0, n, 6000)])
    return 20 * np.log10(np.sqrt(ms) + 1e-9)


def snap_to_sound(start_ms: int, prev_ms: int, lev: np.ndarray, reach: int = 20, pause: int = 6,
                  ctx: int = 50, quiet_db: float = 6.0, range_db: float = 20.0) -> int:
    """A start next to a pause, moved onto the edge of the sound. CTC places a word at its
    first letter's spike, which after a pause lands up to ~170 ms after the sound begins.

    Quiet means within ``quiet_db`` of the lowest level in the ±``ctx`` frames around the
    start. On sound, the start walks back while the sound runs on unbroken, at most ``reach``
    frames, and moves only if ``pause`` quiet frames come before it, all after the previous
    word's start ``prev_ms``: a word with no pause before it stays put. In quiet, it walks
    forward to the first sound within ``reach``. Where the sound rises less than ``range_db``
    out of the quiet (music under the voice, no real pause) the start stays."""
    f = start_ms // 10
    if f >= len(lev):
        return start_ms
    floor = lev[max(0, f - ctx):f + ctx].min()
    if lev[f:f + 15].max() - floor < range_db:
        return start_ms
    q = floor + quiet_db
    g = f
    if lev[f] >= q:
        while g > 0 and f - g < reach and lev[g - 1] >= q:
            g -= 1
        if f - g >= reach or (g - pause) * 10 <= prev_ms or (lev[g - pause:g] >= q).any():
            return start_ms
    else:
        while g < len(lev) - 1 and g - f < reach and lev[g] < q:
            g += 1
        if g - f >= reach:
            return start_ms
    return start_ms if g == f else g * 10


def retime_starts(words: list[dict], cues: list, align: AlignWindow, alignable: Callable[[str], bool],
                  pad_ms: int, duration_ms: int, snap: Callable[[int, int], int] | None = None) -> list[dict]:
    """New word dicts with aligned starts. ``cues`` give the windows: each word goes with the cue
    its start falls in. A word the model cannot align (Latin, digits) keeps its times and walls
    off its own audio: the Thai words either side align only up to its start or from its end,
    so they cannot latch onto its sound. ``snap(start, previous word's start)`` then moves every
    start (aligned or kept) onto the sound's edge. Starts never go backwards; a word ends by the next word's start and keeps
    at least 1 ms."""
    out = [dict(w) for w in words]
    for c in cues:
        idx = [i for i, w in enumerate(words) if c.start_ms <= w["start_ms"] < c.end_ms]
        lo = max(c.start_ms - pad_ms, 0)
        run: list[int] = []
        for i in idx + [None]:
            if i is not None and alignable(words[i]["text"]):
                run.append(i)
                continue
            hi = min(c.end_ms + pad_ms, duration_ms) if i is None else words[i]["start_ms"]
            if run and hi > lo:
                for j, span in zip(run, align(lo, hi, [words[j]["text"] for j in run])):
                    if span is not None:
                        out[j]["start_ms"] = int(round(span[0]))
            run = []
            if i is not None:
                lo = words[i]["end_ms"]
    if snap is not None:
        aligned = [w["start_ms"] for w in out]
        for i, w in enumerate(out):
            w["start_ms"] = snap(w["start_ms"], aligned[i - 1] if i else -1)
    prev = 0
    for w in out:
        w["start_ms"] = max(w["start_ms"], prev)
        prev = w["start_ms"]
    for w, nxt in zip(out, out[1:] + [None]):
        end = w["end_ms"] if nxt is None else min(w["end_ms"], nxt["start_ms"])
        w["end_ms"] = max(end, w["start_ms"] + 1)
    return out


def retime_cue_starts(cues: list, old_words: list[dict], new_words: list[dict]) -> None:
    """In place: each cue starts where its first word now starts. A cue that touched the
    previous one moves their shared boundary, so the pair stays gapless; otherwise the start
    never reaches back into the previous cue. A cue keeps at least 1 ms."""
    prev = None
    for c in cues:
        touching = prev is not None and c.start_ms == prev.end_ms
        firsts = [n["start_ms"] for o, n in zip(old_words, new_words) if c.start_ms <= o["start_ms"] < c.end_ms]
        if firsts:
            if touching:
                c.start_ms = min(max(firsts[0], prev.start_ms + 1), c.end_ms - 1)
                prev.end_ms = c.start_ms
            else:
                c.start_ms = min(max(firsts[0], prev.end_ms if prev else 0), c.end_ms - 1)
        prev = c


def align_words(words: list[dict], cues: list, audio: np.ndarray, sr: int, device: str, cfg: dict) -> list[dict]:
    """The step as the pipeline runs it (config ``word_align``): load the CTC model, re-time the
    word starts, snap them to the sound unless ``snap_to_sound`` is off, unload. New word dicts;
    the cue starts move in place."""
    snap = None
    if cfg.get("snap_to_sound", True):
        lev = levels_db(audio, sr)
        snap = lambda s, prev: snap_to_sound(s, prev, lev)  # noqa: E731
    aligner = ThaiCTCAligner(audio, sr, cfg.get("model", DEFAULT_MODEL), device)
    aligner.load()
    try:
        new = retime_starts(words, cues, aligner, aligner.alignable, int(cfg.get("pad_ms", 400)),
                            len(audio) * 1000 // sr, snap)
    finally:
        aligner.unload()
    retime_cue_starts(cues, words, new)
    return new


def model_path(model: str = DEFAULT_MODEL) -> Path:
    """The checkpoint on disk (a relative path is from the repo root). Raises when it was never
    exported, so a job can fail before Engine A runs rather than after."""
    path = Path(model) if Path(model).is_absolute() else Path(__file__).resolve().parents[2] / model
    if not path.exists():
        raise FileNotFoundError(f"word_align model {path} is missing; export it once with: python -c "
                                f"\"from transcribe.pipeline.word_align import export_checkpoint; export_checkpoint()\"")
    return path


def export_checkpoint(out: str = DEFAULT_MODEL, hub_model: str = HUB_MODEL) -> None:
    """Save a Hugging Face wav2vec2 CTC model as the torchaudio checkpoint ``ThaiCTCAligner`` loads:
    fp16 weights, builder config, letter vocabulary. Run once; loading it then needs no
    transformers import (about 6 s, against 0.4 s for the weights). Emissions are bit-identical."""
    import torch
    from torchaudio.models.wav2vec2.utils import import_huggingface_model
    from torchaudio.models.wav2vec2.utils.import_huggingface import _get_config
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    hf = Wav2Vec2ForCTC.from_pretrained(hub_model).eval()
    tok = Wav2Vec2Processor.from_pretrained(hub_model).tokenizer
    config = {**_get_config(hf.config), "aux_num_out": hf.config.vocab_size}
    weights = {k: v.half() for k, v in import_huggingface_model(hf).state_dict().items()}
    path = Path(__file__).resolve().parents[2] / out
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"config": config, "state_dict": weights, "vocab": tok.get_vocab(), "blank": tok.pad_token_id}, path)


class ThaiCTCAligner:
    """A wav2vec2 CTC model with a Thai letter vocabulary (a torchaudio checkpoint), as an ``AlignWindow``."""

    def __init__(self, audio: np.ndarray, sr: int, model: str = DEFAULT_MODEL, device: str = "cuda"):
        self._audio, self._sr, self._name, self._device = audio, sr, model, device
        self._model = None

    def load(self) -> None:
        import torch
        from torchaudio.models import wav2vec2_model
        ck = torch.load(model_path(self._name), weights_only=True)
        model = wav2vec2_model(**ck["config"])
        model.load_state_dict(ck["state_dict"])
        dtype = torch.float16 if self._device == "cuda" else torch.float32
        self._model = model.to(self._device, dtype).eval()
        self._vocab, self._blank = ck["vocab"], ck["blank"]

    def alignable(self, text: str) -> bool:
        """True when the model has a letter for at least one character of ``text``."""
        return any(self._vocab.get(ch, self._blank) != self._blank for ch in text)

    def unload(self) -> None:
        import torch
        self._model = None
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
        seg = (seg - seg.mean()) / np.sqrt(seg.var() + 1e-7)  # the model's input normalisation
        x = torch.from_numpy(seg.astype(np.float32))[None].to(self._device)
        with torch.inference_mode():
            logits = self._model(x.half() if self._device == "cuda" else x)[0].float()
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
