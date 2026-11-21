"""Analyse a panel sequence snapshot and emit a native cut plan; no timeline edits."""
from __future__ import annotations
from dataclasses import replace
from cutdeck.contracts import CUT, CutConfig, CutPlan, Timebase
from cutdeck import sequence_model
from cutdeck.sequence_timing import SequenceRefusal, range_window_frames, ticks_per_frame
from transcribe.timebase import ms_to_frame

def _cut_spans_frames(plan: CutPlan, tb: Timebase) -> list[tuple[int, int]]:
    """CUT spans as (start_frame, end_frame), ascending, non-overlapping."""
    out = []
    for s in plan.spans:
        if s.action != CUT:
            continue
        start = ms_to_frame(s.src_in_ms, tb)
        end = ms_to_frame(s.src_out_ms, tb)
        if end > start:
            out.append((start, end))
    out.sort()
    return out


def _progress(pct: int, stage: str) -> None:
    """Phase marker the helper parses off our stdout (helper.parse_progress)."""
    print(f"PROGRESS:{pct}:{stage}", flush=True)


def scoped_cuts(plan: CutPlan, tb: Timebase, duration_frames: int,
                frame_range: tuple[int, int] | None = None) -> list[tuple[int, int]]:
    """Intersect cuts with a half-open sequence range on the sequence frame grid."""
    cuts = _cut_spans_frames(plan, tb)
    if frame_range is None:
        return cuts
    start, end = frame_range
    if not (0 <= start < end <= duration_frames):
        raise SequenceRefusal("In/Out range must be inside the full sequence, with Out after In")
    return [(max(a, start), min(b, end)) for a, b in cuts
            if max(a, start) < min(b, end)]


_DURATION_GUARD_TOLERANCE_MS = 34


class DurationMismatch(ValueError):
    """The mixdown duration differs from the sequence; cuts would land on the wrong time axis."""


def _check_duration_guard(sequence_duration_frames: int, mixdown_duration_ms: int,
                           tb: Timebase) -> None:
    seq_ms = frame_to_ms_int(sequence_duration_frames, tb)
    if abs(seq_ms - mixdown_duration_ms) > _DURATION_GUARD_TOLERANCE_MS:
        raise DurationMismatch(
            f"mixdown duration ({mixdown_duration_ms} ms) does not match the "
            f"sequence's declared duration ({seq_ms} ms, {sequence_duration_frames} "
            f"frames) within one frame. If the mixdown was exported over an in/out "
            f"range or the work area instead of the whole sequence, every cut would "
            f"land at the wrong time, uniformly — refusing rather than risk that."
        )


def shift_plan(plan: CutPlan, offset_ms: int) -> CutPlan:
    """Move a plan built on a trimmed mixdown back onto the sequence timeline."""
    return replace(plan, spans=[
        replace(s, src_in_ms=s.src_in_ms + offset_ms, src_out_ms=s.src_out_ms + offset_ms)
        for s in plan.spans
    ])


def frame_to_ms_int(frame: int, tb: Timebase) -> int:
    from transcribe.timebase import frame_to_ms
    return int(round(frame_to_ms(frame, tb)))


def write_cuts_json(path, plan: CutPlan, cuts: list[tuple[int, int]], tb: Timebase,
                    seq_frames: int, source_sequence: dict) -> None:
    """Write frame spans and report for the native edit stage."""
    import json
    reasons = sorted({s.reason for s in plan.spans if s.action == CUT and s.reason})
    path.write_text(json.dumps({
        "cuts_frames": [[a, b] for a, b in cuts],
        "ticks_per_frame": str(ticks_per_frame(tb)),
        "sequence_duration_frames": seq_frames,
        "source_sequence": source_sequence,
        "report": {"cuts_applied": len(cuts), "removed_frames": sum(b - a for a, b in cuts),
                   "reasons": reasons},
    }), encoding="utf-8")


def _deep_update(base: dict, overlay: dict) -> None:
    """Recursively apply ``overlay``'s keys onto ``base``, in place."""
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def analysis_ingest_kwargs(raw_config: dict) -> dict:
    """ingest() settings for Rough Cut: the shared VAD mapping plus the sound guard."""
    from transcribe.pipeline.ingest import ingest_settings
    cfg = CutConfig.from_yaml(raw_config)
    return dict(**ingest_settings(raw_config), sound_guard_db=cfg.sound_guard_db,
                sound_guard_tail_db=cfg.sound_guard_tail_db,
                sound_guard_min_ms=cfg.sound_guard_min_ms)


# A source never transcribed is transcribed whole (once, for every later tool) when the cut uses
# at least this share of it; below it, transcribing the whole file for a short range costs too much
# and the analysed WAV is transcribed instead.
SOURCE_SHARE = 0.5


def _media_seconds(path: str) -> float | None:
    import shutil
    import subprocess
    if shutil.which("ffprobe") is None:
        return None
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def _transcribe_source(media: str, db_path) -> None:
    """Whole-file ASR of a source into the shared store, with the base config (no cut overlay:
    its VAD settings are for cutting, not for listening), as the transcribe tool runs it."""
    from pathlib import Path

    import yaml

    from transcribe.service import transcribe
    config = yaml.safe_load((Path(__file__).resolve().parent.parent / "transcribe" / "config.yaml")
                            .read_text(encoding="utf-8"))
    transcribe(media, config=config, db_path=db_path)


def _mapped_transcript(seq: sequence_model.Sequence, audio_track: int | None,
                       window: tuple[int, int] | None, raw_config: dict, db=None,
                       transcribe_sources: bool = False):
    """(transcript job id, words, cue tokens) in the analysed WAV's own milliseconds, from the
    reference track's source files' stored transcripts mapped through its clips. None when a
    source has no transcript: the caller then transcribes the WAV as before. With
    ``transcribe_sources``, a source the cut uses at least ``SOURCE_SHARE`` of is transcribed
    whole first (the usual rough cut of a whole recording), so later tools need no new listening.

    The same source transcript serves every rough cut of the same footage, so a re-cut never
    re-listens and never hears it differently (docs/TIMELINE_LISTEN.md)."""
    from pathlib import Path
    from types import SimpleNamespace

    from cutdeck import timeline_transcript as tt
    from cutdeck.words import Word
    from transcribe.db import store

    track = seq.reference_track(audio_track)
    clips = [tt.Clip(f"A{track.index + 1}@{c.start_ticks}", c.start_ticks, c.end_ticks, c.in_ticks,
                     c.out_ticks, c.media_path) for c in track.clips if c.enabled]
    db_path = Path(db) if db else store.resolve_db_path(raw_config)
    if not db_path.is_file() and not transcribe_sources:
        return None
    origin = window[0] * seq.ticks_per_frame if window else 0
    end = window[1] * seq.ticks_per_frame if window else seq.end_ticks
    levels_dir = Path(__file__).resolve().parent.parent / "output" / "timeline_transcripts" / "levels"
    words_by_media, job_ids = {}, []
    for media in dict.fromkeys(c.media for c in clips):
        if not Path(media).is_file():
            return None
        found = tt.source_words(media, db_path, levels_dir) if db_path.is_file() else None
        if found is None and transcribe_sources:
            used = sum(max(0, min(c.end, end) - max(c.start, origin)) for c in clips if c.media == media)
            total = _media_seconds(media)
            if total and used / tt.PPRO_TICKS_PER_SECOND >= SOURCE_SHARE * total:
                print(f"--asr: transcribing the source once, for this and every later cut: {media}")
                _transcribe_source(media, db_path)
                found = tt.source_words(media, db_path, levels_dir)
        if found is None:
            return None
        job_ids.append(found[0])
        words_by_media[media] = found[1]
    placed = [w for w in tt.project(clips, words_by_media) if w.end > origin and w.start < end]
    # Clamped to the WAV: a word that straddles the window's edge starts or ends at it.
    ms = lambda ticks: round((min(max(ticks, origin), end) - origin) / tt.TICKS_PER_MS)  # noqa: E731
    words = [Word(w.text, ms(w.start), ms(w.end), None) for w in placed]
    tokens = [SimpleNamespace(idx=i, text=ln["text"], start_ms=ms(int(ln["start_ticks"])),
                              end_ms=ms(int(ln["end_ticks"])))
              for i, ln in enumerate(tt.lines(placed, seq.ticks_per_frame))]
    return job_ids[0], words, tokens


def analyze(seq: sequence_model.Sequence, raw_config: dict, *, frame_range: tuple[int, int] | None = None,
            audio_track: int | None = None, asr: bool = False, db=None, job_id: int = 0,
            mixdown_wav: str | None = None) -> tuple[CutPlan, list[tuple[int, int]]]:
    """Analyse the sequence's reference audio (or the given ``mixdown_wav``) and return the plan plus
    its cut spans in sequence frames, scoped to ``frame_range``."""
    import tempfile
    from pathlib import Path

    from cutdeck.sequence_mixdown import plan_from_mixdown

    tb = seq.timebase
    seq_frames = seq.duration_frames
    cfg = CutConfig.from_yaml(raw_config)

    # Same config->ingest mapping as the rest of the pipeline. Without it,
    # ingest() falls back to its own hardcoded defaults (vad_threshold=0.5,
    # vad_min_silence_ms=300) and silence detection diverges from config.yaml
    # (2026-08-29 bug: leftover silence in recut output).
    ingest_kwargs = dict(denoise=raw_config.get("denoise", True),
                         **analysis_ingest_kwargs(raw_config))

    if asr:
        # One ingest serves the duration guard, run_file() and the plan. run_file
        # feeds ingest().audio to a whole-file engine, which must hear the raw
        # track, so the shared pass can't be denoised (run_file's own rule).
        ingest_kwargs["denoise"] = False

    extracted_tmp = None
    window = None  # (lo, hi) sequence frames, set only when we trim the mixdown ourselves
    if mixdown_wav is None:
        from cutdeck.audio_extract import extract_mixdown
        _progress(5, "Extracting audio")
        extracted_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        extracted_tmp.close()
        print("no mixdown given — extracting one from the sequence's own source media...")
        mixdown_wav = extract_mixdown(
            seq, extracted_tmp.name, audio_track,
            range_start_frame=frame_range[0] if frame_range else None,
            range_end_frame=frame_range[1] if frame_range else None,
            sample_rate=16000,
        )
        if frame_range:
            window = range_window_frames(tb, seq_frames, frame_range)

    try:
        from transcribe.pipeline.ingest import ingest
        _progress(20, "Detecting speech")
        mixdown_result = ingest(mixdown_wav, materialize_chunks=False, **ingest_kwargs)
        _check_duration_guard(window[1] - window[0] if window else seq_frames,
                              mixdown_result.duration_ms, tb)

        tokens = None
        words = None
        # Only for audio we extracted from the clips ourselves: a caller's own mixdown is theirs.
        if asr and extracted_tmp is not None:
            _progress(35, "Reading (or once transcribing) the sources")
        mapped = (_mapped_transcript(seq, audio_track, window, raw_config, db, transcribe_sources=True)
                  if asr and extracted_tmp is not None else None)
        if mapped is not None:
            job_id, words, tokens = mapped
            print(f"--asr: mapped the sources' own transcripts onto the range ({len(tokens)} lines, "
                  "no ASR pass; cutdeck/timeline_transcript.py)")
        elif asr:
            from types import SimpleNamespace

            from transcribe.service import transcribe

            # The service reuses a finished job for the same mixdown sha256, engines and
            # pipeline version (0 ASR passes) and returns the job id it ran under.
            _progress(35, "Transcribing speech")
            transcript = transcribe(mixdown_wav, config=raw_config,
                                    db_path=Path(db) if db else None,
                                    ingest_result=mixdown_result)
            if transcript.cached:
                print(f"--asr: reusing the transcript of job {transcript.job_id} "
                      "(same mixdown, engines and pipeline version)")
            job_id, words, token_dicts = transcript.job_id, transcript.words, transcript.cues
            print(f"--asr: got {len(token_dicts)} tokens")
            # rules.apply_min_clip_merge only needs .idx/.start_ms/.end_ms — the
            # dicts run_file returns aren't attribute-accessible, so wrap them
            # rather than re-deriving the job id run_file already resolved
            # internally (duplicating its resumable-job lookup would be another
            # place that lookup could drift out of sync).
            tokens = [
                SimpleNamespace(idx=i, text=t["text"],
                                 start_ms=t["start_ms"], end_ms=t["end_ms"])
                for i, t in enumerate(token_dicts)
            ]

        _progress(85, "Calculating cut spans")
        plan = plan_from_mixdown(mixdown_wav, job_id, cfg, timebase=tb,
                                  tokens=tokens, ingest_result=mixdown_result,
                                  words=words)
    finally:
        if extracted_tmp is not None:
            Path(extracted_tmp.name).unlink(missing_ok=True)

    if window:
        # The plan was built on a WAV that starts at the window's first frame.
        plan = shift_plan(plan, frame_to_ms_int(window[0], tb))

    cuts = scoped_cuts(plan, tb, seq_frames, frame_range)
    return plan, cuts


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    import json
    import yaml

    ap = argparse.ArgumentParser(
        description="Analyse a panel JSON sequence snapshot and return frame cuts for native Premiere editing."
    )
    ap.add_argument("sequence_json", help="the helper's panel sequence.json snapshot")
    ap.add_argument("mixdown_wav", nargs="?", default=None,
                     help="full-sequence audio mixdown (must span the whole sequence, "
                          "not an in/out range). Omit to auto-extract one straight from "
                          "the snapshot's clips + source media instead (see "
                          "cutdeck/audio_extract.py) — no Premiere export needed.")
    ap.add_argument("--audio-track", type=int, default=None,
                     help="0-based Premiere audio track index to use as the reference "
                          "dialogue track when auto-extracting (default: first track with clips). "
                          "Ignored when mixdown_wav is given explicitly.")
    ap.add_argument("--job-id", type=int, default=0)
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent.parent
                                             / "transcribe" / "config.yaml"))
    ap.add_argument("--overlay", default=None,
                     help="YAML file of config keys to override on top of --config (e.g. "
                          "transcribe/config.aggressive_cut.yaml's tuned silence-removal "
                          "thresholds) — only the keys present in the overlay are changed, "
                          "everything else still comes from --config.")
    ap.add_argument("--db", default=None, help="SQLite path (defaults to store default)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--range-start-frame", type=int)
    ap.add_argument("--range-end-frame", type=int)
    ap.add_argument("--cuts-json", help="output native cut-list JSON")
    ap.add_argument("--asr", action="store_true",
                     help="run the full ASR pipeline (Engine A) on the mixdown first and "
                          "use its real tokens to protect short speech islands in the "
                          "min-clip merge, instead of guessing blind from silence alone. "
                          "Slower (a real transcription pass over the whole mixdown) but "
                          "the merge no longer has to choose between re-admitting silence "
                          "or risking a dropped word — see plan_from_mixdown's tokens arg.")
    args = ap.parse_args(argv)

    src = Path(args.sequence_json)
    if src.suffix.lower() != ".json":
        raise SequenceRefusal("XML Rough Cut is retired. Use the panel or premiere_rough_cut.")
    source_sequence = json.loads(src.read_text(encoding="utf-8-sig"))
    seq = sequence_model.from_panel_json(source_sequence)
    if not args.cuts_json and not args.dry_run:
        ap.error("pass --cuts-json to write the native cut list, or --dry-run")
    tb = seq.timebase
    seq_frames = seq.duration_frames
    frame_range = None
    if args.range_start_frame is not None or args.range_end_frame is not None:
        if args.range_start_frame is None or args.range_end_frame is None:
            ap.error("both range frame arguments are required")
        frame_range = (args.range_start_frame, args.range_end_frame)
        if not (0 <= frame_range[0] < frame_range[1] <= seq_frames):
            ap.error("In/Out range must be inside the full sequence")

    raw_config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.overlay:
        _deep_update(raw_config, yaml.safe_load(Path(args.overlay).read_text(encoding="utf-8")))
    plan, cuts = analyze(seq, raw_config, frame_range=frame_range, audio_track=args.audio_track,
                         asr=args.asr, db=args.db, job_id=args.job_id, mixdown_wav=args.mixdown_wav)
    n_cut = len(cuts)
    cut_ms = frame_to_ms_int(sum(b - a for a, b in cuts), tb)

    if args.dry_run:
        print(f"{n_cut} cut spans, {cut_ms} ms to remove of {plan.duration_ms} ms "
              f"({seq_frames} frames in the sequence snapshot)")
        return 0

    if args.cuts_json:
        write_cuts_json(Path(args.cuts_json), plan, cuts, tb, seq_frames, source_sequence)
        print(f"wrote {args.cuts_json}: {n_cut} cuts, {cut_ms} ms to remove")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
