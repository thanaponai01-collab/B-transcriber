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
        if asr:
            from types import SimpleNamespace

            from transcribe.db import store
            from transcribe.pipeline.run import run_file

            from cutdeck.words import words_for_job

            db_path = Path(db) if db else store._DEFAULT_DB

            # The mixdown is deterministic for one sequence + range, so its sha256
            # is the cache key: a finished job for the same media, engine pair and
            # pipeline version already holds the transcript — reuse it, 0 ASR passes.
            from transcribe.pipeline import plan as planning
            from transcribe.pipeline.run import PIPELINE_VERSION
            engine_a, engine_b = planning.canonical_engine_names(raw_config)
            asr_conn = store.connect(db_path)
            try:
                media_id = store.create_media(asr_conn, mixdown_wav)
                cached = store.find_finished_job(
                    asr_conn, media_id, engine_a, engine_b, PIPELINE_VERSION)
                if cached is not None:
                    print(f"--asr: reusing the transcript of job {cached.id} "
                          "(same mixdown, engines and pipeline version)")
                    words = words_for_job(asr_conn, cached.id)
                    token_dicts = [dict(text=t.text, start_ms=t.start_ms, end_ms=t.end_ms)
                                   for t in store.get_tokens(asr_conn, cached.id)]
                    job_id = cached.id
            finally:
                asr_conn.close()

            if cached is None:
                _progress(35, "Transcribing speech")
                print("--asr: running the full ASR pipeline on the mixdown "
                      "(this transcribes the whole mixdown — slower than silence-only)...")
                token_dicts = run_file(mixdown_wav, raw_config, db_path,
                                       ingest_result=mixdown_result)
                # run_file() resolves/creates its own job_id internally and never
                # returns it — look it up by media path so the plan we save below
                # references the job the tokens actually belong to, not job_id's
                # default of 0 (which doesn't exist -> cut_plan FK violation).
                asr_conn = store.connect(db_path)
                try:
                    job_row = store.get_latest_job_for_media(asr_conn, media_id)
                    if job_row is not None:
                        job_id = job_row.id
                        words = words_for_job(asr_conn, job_row.id)
                finally:
                    asr_conn.close()
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
