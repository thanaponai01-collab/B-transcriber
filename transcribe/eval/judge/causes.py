"""Where the timing misses come from: each marked edge that the final pipeline misses by more
than one frame, put down to one cause (tune and heldout only; never the lockbox).

Per clip, three runs on the same cached Engine A output: Whisper alone, CTC alone (no snaps),
and the configured pipeline (CTC + snaps). For a missed edge, in order:
- vad_cut: the mark lies outside every ingest speech span (more than a frame from one);
- missing_text: no word, in Whisper's output or the final one, covers the 150 ms of speech on
  the mark's speech side (Whisper never wrote that speech);
- window_collision: the final word was squeezed to 1 ms or onto its neighbour's start (two cue
  windows aligned the same sound);
- low_conf_text: the matched word's Whisper confidence is under 0.2 (a proxy for wrong text;
  the timing clips have no reference transcript);
- snap: the snap moved the edge (snap_broke: CTC alone had it within a frame);
- ctc_placement: the snap did not move it, so it sits where CTC put it.
premiere_rounding: edges within a frame as timed that miss once Premiere floors them to 30 fps."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path

from transcribe.eval.judge import score
from transcribe.eval.judge.prepare import MANIFEST, REPO, wav_path, whisper_path


COVER_MS = 150


def speech_spans(clip: dict, manifest: dict, config: dict) -> list[tuple[int, int]]:
    """The ingest speech spans exactly as the pipeline computes them for this file."""
    from transcribe.pipeline import plan, run
    res = run._ingest_for_plan(str(wav_path(manifest, clip)), config, plan.make_plan(config, None))
    return [(s.start_ms, s.end_ms) for s in res.spans if s.kind == "speech"]


def covered(words: list[dict], r: float, kind: str) -> bool:
    lo, hi = (r, r + COVER_MS) if kind == "start" else (r - COVER_MS, r)
    return any(w["start_ms"] < hi and w["end_ms"] > lo for w in words)


def collided(words: list[dict], t: float | None, kind: str) -> bool:
    key = "start_ms" if kind == "start" else "end_ms"
    for i, w in enumerate(words):
        if w[key] == t:
            prev = words[i - 1] if i else None
            return w["end_ms"] - w["start_ms"] <= 1 or (prev is not None and prev["start_ms"] == w["start_ms"])
    return False


def _conf_at(words: list[dict], key: str, t: float) -> float | None:
    for w in words:
        if w[key] == t:
            return w.get("confidence")
    return None


def breakdown(split: str, config: dict) -> dict:
    if split == "lockbox":
        raise SystemExit("causes never reads the lockbox")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    score.check_lock(manifest)
    refs = score.load_refs(manifest, split)
    clips = {c["name"]: c for c in manifest["clips"]}
    ctc_only = copy.deepcopy(config)
    ctc_only.setdefault("word_align", {}).update(snap_to_sound=False, snap_ends=False)
    causes: Counter = Counter()
    by_kind: dict[str, Counter] = {"start": Counter(), "end": Counter()}
    rounding = 0
    examples = []
    for name, ref in sorted(refs.items()):
        clip = clips[name]
        fps = clip["fps"]
        raw = json.loads(whisper_path(manifest, clip).read_text(encoding="utf-8"))
        runs = {"whisper": (raw["words"], raw["cues"]),
                "ctc": score.replay(clip, manifest, ctc_only)[:2],
                "final": score.replay(clip, manifest, config)[:2]}
        rows = {k: score.edge_rows(ref, w, c, fps) for k, (w, c) in runs.items()}
        spans = speech_spans(clip, manifest, config)
        tol = 1000 / fps
        for rw, rc, rf in zip(rows["whisper"], rows["ctc"], rows["final"]):
            r, kind = rf["ref"], rf["kind"]
            if score._hit(r, rf["word"], fps, 1):
                if not score._hit(r, rf["word"], fps, 1, "premiere"):
                    rounding += 1
                cause = "hit"
            elif not any(a - tol <= r <= b + tol for a, b in spans):
                cause = "vad_cut"
            elif not covered(runs["whisper"][0], r, kind) and not covered(runs["final"][0], r, kind):
                cause = "missing_text"
            elif collided(runs["final"][0], rf["word"], kind):
                cause = "window_collision"
            elif (_conf_at(runs["whisper"][0], "start_ms" if kind == "start" else "end_ms", rw["word"]) or 1) < 0.2:
                cause = "low_conf_text"
            elif rf["word"] != rc["word"]:
                cause = "snap_broke" if score._hit(r, rc["word"], fps, 1) else "snap"
            else:
                cause = "ctc_placement"
            causes[cause] += 1
            by_kind[kind][cause] += 1
            if cause != "hit" and len(examples) < 400:
                examples.append({"clip": name, "kind": kind, "ref": r, "whisper": rw["word"], "ctc": rc["word"],
                                 "final": rf["word"], "cause": cause})
    n = sum(causes.values())
    return {"split": split, "edges": n, "causes": dict(causes.most_common()),
            "share_of_misses": {k: round(v / max(1, n - causes["hit"]), 3) for k, v in causes.items() if k != "hit"},
            "by_kind": {k: dict(v.most_common()) for k, v in by_kind.items()},
            "premiere_rounding": rounding, "examples": examples}


def main(argv: list[str] | None = None) -> int:
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--split", choices=["tune", "heldout"], default="tune")
    p.add_argument("--config", default=str(REPO / "transcribe" / "config.yaml"))
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    out = breakdown(args.split, yaml.safe_load(Path(args.config).read_text(encoding="utf-8")))
    dest = REPO / "output" / "judge_runs" / f"causes-{args.split}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "examples"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
