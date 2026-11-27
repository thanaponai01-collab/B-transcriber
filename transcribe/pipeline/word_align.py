from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

AlignWindow = Callable[[int, int, list[str]], list[tuple[float, float] | None]]

HUB_MODEL = "sakares/wav2vec2-large-xlsr-thai-demo"
DEFAULT_MODEL = "models/wav2vec2-th-ctc.pt"


def levels_db(audio: np.ndarray, sr: int) -> np.ndarray:
    hop, size = sr // 100, sr * 25 // 1000
    n = max(0, (len(audio) - size) // hop + 1)
    if not n:
        return np.zeros(0)
    frames = np.lib.stride_tricks.sliding_window_view(audio, size)[::hop][:n]
    ms = np.concatenate([(frames[i:i + 6000].astype(np.float64) ** 2).mean(axis=1)
                         for i in range(0, n, 6000)])
    return 20 * np.log10(np.sqrt(ms) + 1e-9)


DIGITAL_DB = -120.0


def _floor(window: np.ndarray) -> float:
    live = window[window > DIGITAL_DB]
    return float(live.min() if len(live) else window.min())


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
    floor = _floor(lev[max(0, f - ctx):f + ctx])
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


def flux_onsets(audio: np.ndarray, sr: int) -> np.ndarray:
    """Spectral-flux onsets, each backtracked to the energy minimum before it (librosa), in ms."""
    import librosa
    hop = sr // 100
    env = librosa.onset.onset_strength(y=audio.astype(np.float32), sr=sr, hop_length=hop)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop, backtrack=True, units="frames")
    return np.asarray(frames, dtype=np.int64) * 10


def snap_to_flux(start_ms: int, prev_ms: int, onsets_ms: np.ndarray, lev: np.ndarray, reach_ms: int = 200,
                 pause: int = 6, ctx: int = 50, quiet_db: float = 6.0) -> int:
    """A start moved to the nearest backtracked flux onset within ``reach_ms``, when that onset
    comes after the previous word's start and ``pause`` quiet frames (as in ``snap_to_sound``)
    come before it; otherwise the start stays."""
    if not len(onsets_ms):
        return start_ms
    near = onsets_ms[np.abs(onsets_ms - start_ms) <= reach_ms]
    for o in sorted(near, key=lambda o: abs(int(o) - start_ms)):
        g = int(o) // 10
        if g - pause < 0 or g >= len(lev) or (g - pause) * 10 <= prev_ms:
            continue
        floor = _floor(lev[max(0, g - ctx):g + ctx])
        if (lev[g - pause:g] < floor + quiet_db).all():
            return int(o)
    return start_ms


def snap_end_to_sound(start_ms: int, anchor_ms: int, lev: np.ndarray, reach: int = 40, pause: int = 6,
                      ctx: int = 50, quiet_db: float = 6.0, range_db: float = 20.0,
                      below_peak_db: float = 30.0, tail_db: float = 25.0, hold_db: float = 3.0) -> int | None:
    """The end of a word followed by a pause: where its sound fades into the quiet, or None.

    ``anchor_ms`` is CTC's last letter, which stops before the syllable fades, or lands after it.
    Quiet is as in ``snap_to_sound``, or ``below_peak_db`` under the loudest frame from the
    word's start ``start_ms`` to the anchor, whichever is higher: a fading tail is not speech.
    An anchor ``tail_db`` under that peak sits in the word's tail, or in noise where CTC put
    letters it did not hear, so there the tail counts as quiet too. From a sounding anchor the
    end walks forward while the sound runs on, at most ``reach`` frames; from a quiet one it
    walks back to the sound, never past the word's start. It counts only if ``pause`` frames
    follow that stay under quiet + ``hold_db`` (room noise flickers). The music-bed gate is as
    in ``snap_to_sound``."""
    f = min(anchor_ms // 10, len(lev) - 1)
    if f < 0:
        return None
    floor = _floor(lev[max(0, f - ctx):f + ctx])
    peak = lev[min(max(0, start_ms // 10), f):f + 1].max()
    if peak - floor < range_db:
        return None
    q = max(floor + quiet_db, peak - below_peak_db)
    if q <= lev[f] < peak - tail_db:
        q = peak - tail_db
    g = f
    if lev[f] >= q:
        while g < len(lev) - 1 and g - f < reach and lev[g] >= q:
            g += 1
        if g - f >= reach:
            return None
    else:
        first = max(0, start_ms // 10)
        while g > first and lev[g - 1] < q:
            g -= 1
        if g <= first:
            return None
    if (lev[g:g + pause] >= q + hold_db).any():
        return None
    return g * 10


def retime_words(words: list[dict], cues: list, align: AlignWindow, alignable: Callable[[str], bool],
                 pad_ms: int, duration_ms: int, snap: Callable[[int, int], int] | None = None,
                 snap_end: Callable[[int, int], int | None] | None = None,
                 pad_into_neighbours: bool = True) -> list[dict]:
    """New word dicts with aligned starts and, where a pause follows, ends. ``cues`` give the
    windows: each word goes with the cue its start falls in. A word the model cannot align
    (Latin, digits) keeps its times and walls off its own audio: the Thai words either side
    align only up to its start or from its end, so they cannot latch onto its sound.
    ``snap(start, previous word's start)`` then moves every start (aligned or kept) onto the
    sound's edge. Starts never go backwards. ``snap_end(start, anchor)`` gives the
    end of a word a pause follows, from CTC's last letter (the engine's end where the model
    has no letters), kept before the next word's start; an end found past that start is
    dropped. Elsewhere a word ends at the engine's end. A word ends by the next word's
    start and keeps at least 1 ms. With ``pad_into_neighbours`` off, a cue's padded window
    stops at the engine's end of the previous cue's last word and the start of the next cue's
    first word, so two windows never align the same sound."""
    out = [dict(w) for w in words]
    last_letter: dict[int, float] = {}
    for c in cues:
        idx = [i for i, w in enumerate(words) if c.start_ms <= w["start_ms"] < c.end_ms]
        lo = max(c.start_ms - pad_ms, 0)
        lo_wall, hi_wall = 0, duration_ms
        if not pad_into_neighbours and idx:
            if idx[0] > 0:
                lo_wall = words[idx[0] - 1]["end_ms"]
            if idx[-1] + 1 < len(words):
                hi_wall = words[idx[-1] + 1]["start_ms"]
            lo = max(lo, min(lo_wall, c.start_ms))
        run: list[int] = []
        for i in idx + [None]:
            if i is not None and alignable(words[i]["text"]):
                run.append(i)
                continue
            hi = min(c.end_ms + pad_ms, duration_ms, max(hi_wall, c.end_ms)) if i is None else words[i]["start_ms"]
            if run and hi > lo:
                for j, span in zip(run, align(lo, hi, [words[j]["text"] for j in run])):
                    if span is not None:
                        out[j]["start_ms"] = int(round(span[0]))
                        last_letter[j] = span[1]
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
    for i, (w, nxt) in enumerate(zip(out, out[1:] + [None])):
        nxt_ms = duration_ms if nxt is None else nxt["start_ms"]
        anchor = min(int(last_letter.get(i, w["end_ms"])), nxt_ms - 10)
        heard = snap_end(w["start_ms"], anchor) if snap_end and anchor > w["start_ms"] else None
        if heard is not None and heard > nxt_ms:
            heard = None
        end = min(w["end_ms"] if heard is None else heard, nxt_ms)
        w["end_ms"] = max(end, w["start_ms"] + 1)
    return out


def retime_cues(cues: list, old_words: list[dict], new_words: list[dict]) -> None:
    """In place: each cue starts where its first word now starts. A cue that touched the
    previous one moves their shared boundary, so the pair stays gapless; otherwise the start
    never reaches back into the previous cue. A cue followed by a gap moves its end as far as its
    last word's end moved, never past the next cue's start. A cue keeps at least 1 ms."""
    prev = None
    for k, c in enumerate(cues):
        touching = prev is not None and c.start_ms == prev.end_ms
        mine = [(o, n) for o, n in zip(old_words, new_words) if c.start_ms <= o["start_ms"] < c.end_ms]
        firsts = [n["start_ms"] for o, n in mine]
        nxt = cues[k + 1] if k + 1 < len(cues) else None
        if mine and not (nxt and nxt.start_ms == c.end_ms):
            end = c.end_ms + mine[-1][1]["end_ms"] - mine[-1][0]["end_ms"]
            end = max(end, c.start_ms + 1)
            c.end_ms = end if nxt is None else min(end, nxt.start_ms)
        if firsts:
            if touching:
                c.start_ms = min(max(firsts[0], prev.start_ms + 1), c.end_ms - 1)
                prev.end_ms = c.start_ms
            else:
                c.start_ms = min(max(firsts[0], prev.end_ms if prev else 0), c.end_ms - 1)
        prev = c


def align_words(words: list[dict], cues: list, audio: np.ndarray, sr: int, device: str, cfg: dict) -> list[dict]:
    """The step as the pipeline runs it (config ``word_align``): load the CTC model, re-time the
    word starts, snap them to the sound unless ``snap_to_sound`` is off, snap the ends before a
    pause unless ``snap_ends`` is off, unload. New word dicts; the cues move in place."""
    lev = levels_db(audio, sr)
    snap = (lambda s, prev: snap_to_sound(s, prev, lev)) if cfg.get("snap_to_sound", True) else None
    if snap is not None and cfg.get("snap_method", "loudness") == "flux":
        onsets = flux_onsets(audio, sr)
        snap = lambda s, prev: snap_to_flux(s, prev, onsets, lev)
    snap_end = (lambda s, a: snap_end_to_sound(s, a, lev)) if cfg.get("snap_ends", True) else None
    aligner = ThaiCTCAligner(audio, sr, cfg.get("model", DEFAULT_MODEL), device)
    aligner.load()
    try:
        new = retime_words(words, cues, aligner, aligner.alignable, int(cfg.get("pad_ms", 400)),
                           len(audio) * 1000 // sr, snap, snap_end, bool(cfg.get("pad_into_neighbours", True)))
    finally:
        aligner.unload()
    retime_cues(cues, words, new)
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
    def __init__(self, audio: np.ndarray, sr: int, model: str = DEFAULT_MODEL, device: str = "cuda"):
        if sr != 16000:
            raise ValueError(f"the CTC model needs 16 kHz audio, got {sr} Hz")
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
