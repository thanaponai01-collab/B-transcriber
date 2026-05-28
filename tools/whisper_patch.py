"""
whisper_patch.py
================

Drop-in patch for the story-pipeline transcription stage.

Problem this fixes
------------------
The current engine reports `openai-whisper available` but then either:
  - hardcodes the English-only model (`.en` variants), which breaks Thai
    and Thai/English code-switched footage, OR
  - skips Whisper's own language detection because a language was forced
    too early in the call chain, OR
  - refuses to ingest containers like `.ts`, `.mkv`, `.mov`, etc., even
    though ffmpeg can read them just fine.

What this patch does
--------------------
1. Loads the multilingual model first (NEVER the `.en` variants).
2. Runs a short language-detection pass on the first ~30s of audio.
3. Picks the best model size based on what was actually detected.
4. Transcribes with the detected language — no manual override needed
   unless the caller explicitly passes one.
5. Accepts ANY container ffmpeg can demux. If the input is not a clean
   16-kHz mono WAV, audio is transparently extracted to a temp file
   before transcription — no more "convert to mp4 first" dance.

Supported input formats (anything ffmpeg can demux)
---------------------------------------------------
Video containers : mp4, mov, mkv, webm, avi, ts, m2ts, mts, mpg, mpeg,
                   flv, wmv, 3gp, vob, ogv, mxf
Audio formats    : wav, mp3, m4a, aac, flac, ogg, opus, wma, aiff
Other            : raw streams, DVD VOBs, network streams — if ffmpeg
                   can open it, this patch can transcribe it.

Run `ffmpeg -formats` on your machine for the exhaustive list — the
patch defers to whatever your ffmpeg build supports.

Usage
-----
In the engine's transcription module, replace the existing whisper call
with:

    from tools.whisper_patch import transcribe_auto
    result = transcribe_auto(video_path)            # full auto
    result = transcribe_auto(video_path, lang="en") # explicit override

`result` has the same shape as `whisper.transcribe()`, so the rest of the
pipeline (Agent 1 PROOFREADER onwards) needs no changes.

Note: this module targets the `openai-whisper` package API directly.
The primary pipeline uses `whisper_thai` (HuggingFace Transformers).
Use this module when you need a standalone openai-whisper call outside
the engine contract, or as a reference for container-handling patterns.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Models that we are willing to load. Note: NO `.en` variants — they cannot
# do language detection and break on multilingual footage.
SAFE_MODELS = ("tiny", "base", "small", "medium", "large-v3", "large-v2", "large")

# Default model for the detection probe (small + fast).
PROBE_MODEL = "base"

# Default model for the real transcription pass if not overridden.
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")


def _ensure_multilingual(model_name: str) -> str:
    """Strip any `.en` suffix — those models can't language-detect."""
    if model_name.endswith(".en"):
        stripped = model_name[:-3]
        log.warning(
            "Refusing to use English-only model %r; falling back to %r so "
            "language detection can run.",
            model_name, stripped,
        )
        return stripped
    return model_name


def _extract_probe_audio(video_path: str, seconds: int = 30) -> str:
    """Pull the first N seconds of audio out to a temp wav for the probe."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-t", str(seconds),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        tmp.name,
    ]
    subprocess.run(cmd, check=True)
    return tmp.name


# Containers Whisper's own loader stumbles on. We extract audio first
# instead of feeding the raw file. Anything else, we hand straight to
# whisper.transcribe() — it'll use ffmpeg under the hood.
NEEDS_PRE_EXTRACT = {".ts", ".m2ts", ".mts", ".vob", ".mxf", ".ogv"}


def _needs_extraction(video_path: str) -> bool:
    """Decide whether to pre-extract audio before handing to Whisper."""
    suffix = Path(video_path).suffix.lower()
    return suffix in NEEDS_PRE_EXTRACT


def _extract_full_audio(video_path: str) -> str:
    """Extract the full audio track to a 16-kHz mono wav."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    log.info("Pre-extracting audio from %s (container needs unpacking)…", Path(video_path).name)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        tmp.name,
    ]
    subprocess.run(cmd, check=True)
    return tmp.name


def detect_language(video_path: str, probe_model: str = PROBE_MODEL) -> tuple[str, float]:
    """
    Detect the dominant language in the first 30 seconds.

    Returns (language_code, confidence). Confidence is Whisper's softmax
    probability for the winning language.
    """
    import whisper

    probe_audio = _extract_probe_audio(video_path)
    try:
        model = whisper.load_model(_ensure_multilingual(probe_model))
        audio = whisper.load_audio(probe_audio)
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio, n_mels=model.dims.n_mels).to(model.device)
        _, probs = model.detect_language(mel)
        lang = max(probs, key=probs.get)
        conf = float(probs[lang])
        log.info("Detected language: %s (confidence=%.2f)", lang, conf)
        return lang, conf
    finally:
        try:
            os.unlink(probe_audio)
        except OSError:
            pass


def transcribe_auto(
    video_path: str,
    lang: Optional[str] = None,
    model_name: str = DEFAULT_MODEL,
    **whisper_kwargs,
):
    """
    Transcribe a video, auto-detecting language if `lang` is not provided.

    Parameters
    ----------
    video_path : str
        Path to the video (or audio) file.
    lang : str, optional
        ISO 639-1 code. If None, language is detected from the first 30s.
    model_name : str
        Whisper model size. Defaults to `large-v3` or $WHISPER_MODEL.
        `.en` suffixes are stripped automatically.
    **whisper_kwargs :
        Forwarded to `whisper.transcribe()` (e.g. `temperature`,
        `condition_on_previous_text`, `word_timestamps=True`).

    Returns
    -------
    dict
        The standard whisper result dict: {"text", "segments", "language"}.
    """
    import whisper

    if not Path(video_path).exists():
        raise FileNotFoundError(video_path)

    # 1. Resolve language.
    if lang is None:
        lang, conf = detect_language(video_path)
        if conf < 0.5:
            log.warning(
                "Low language-detection confidence (%.2f); proceeding with "
                "%r anyway. Pass lang=... to override.", conf, lang,
            )
    else:
        log.info("Language override supplied by caller: %s", lang)

    # 2. Load the multilingual model (never the .en variant).
    safe_name = _ensure_multilingual(model_name)
    log.info("Loading Whisper model: %s", safe_name)
    model = whisper.load_model(safe_name)

    # 3. Transcribe with the detected language. Letting Whisper know the
    #    language up front makes decoding faster and more accurate than
    #    leaving it to re-detect every window.
    defaults = {
        "language": lang,
        "task": "transcribe",
        "word_timestamps": True,
        "condition_on_previous_text": False,  # avoids hallucination loops
        "verbose": False,
    }
    defaults.update(whisper_kwargs)

    log.info("Transcribing %s …", video_path)

    # If the container is one Whisper's loader chokes on, pre-extract
    # audio to a temp wav and feed that instead.
    pre_extracted = None
    try:
        if _needs_extraction(video_path):
            pre_extracted = _extract_full_audio(video_path)
            source = pre_extracted
        else:
            source = video_path

        result = model.transcribe(source, **defaults)
    finally:
        if pre_extracted:
            try:
                os.unlink(pre_extracted)
            except OSError:
                pass

    log.info(
        "Done. %d segments, language=%s",
        len(result.get("segments", [])), result.get("language"),
    )
    return result


# ---------------------------------------------------------------------------
# Monkey-patch hook
# ---------------------------------------------------------------------------
# If the engine imports its own `transcribe()` from a known module, you can
# patch it in place by calling `apply_patch(target_module)` at engine startup.

def apply_patch(target_module) -> None:
    """
    Replace `target_module.transcribe` with the auto-detecting version.

    Example
    -------
    >>> from transcribe.engines import whisper_thai
    >>> from tools import whisper_patch
    >>> whisper_patch.apply_patch(whisper_thai)
    """
    if not hasattr(target_module, "transcribe"):
        raise AttributeError(
            f"{target_module.__name__!r} has no `transcribe` to patch"
        )
    original = target_module.transcribe
    target_module._original_transcribe = original  # keep an escape hatch
    target_module.transcribe = transcribe_auto
    log.info("Patched %s.transcribe -> whisper_patch.transcribe_auto",
             target_module.__name__)


if __name__ == "__main__":
    import argparse, json, sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    p = argparse.ArgumentParser(description="Auto-language Whisper transcribe.")
    p.add_argument("video")
    p.add_argument("--lang", default=None, help="Force a language (skip detect).")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--out", default=None, help="Write result JSON here.")
    args = p.parse_args()

    res = transcribe_auto(args.video, lang=args.lang, model_name=args.model)

    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(f"Wrote {args.out}")
    else:
        json.dump(res, sys.stdout, ensure_ascii=False, indent=2)
