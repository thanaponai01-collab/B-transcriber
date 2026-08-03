# IMPLEMENT — Transcriber v2 Audit + CutDeck Rough-Cut System

Two parts. Part A is an audit of the transcriber you already built: what is solid, and the
specific gaps I would close before calling it durable. Part B is the design + build plan for
the rough-cut editing tool (**CutDeck**), built as a sibling package that consumes the same
SQLite store and inherits the same invariants (select-only decisions, eval-gated flywheel,
model-agnostic contracts).

Everything here is written as a Claude Code build spec: each item has a file target,
behavior, and acceptance criteria.

---

# PART A — Transcriber v2 audit

## A.0 Verdict

The spec is structurally correct and ahead of most production ASR pipelines:
contract layer, select-only reconciler with a hallucination assertion, normalization as the
single style authority shared by hypotheses and gold, regression-gated flywheel, sequential
VRAM discipline. None of that needs rework. The gaps below are operational — things that
will bite in real daily use, not on paper.

## A.1 Gap list (ordered by priority)

### GAP-1 · Timebase is missing from the system entirely — blocker for CutDeck
The spec stores `start_ms / end_ms` but nothing about the source media's true frame rate.
Your earlier SRT drift diagnosis (29.97 vs 30) lives in your head, not in the schema. Once
XML export exists, every millisecond must be convertible to a frame number under the exact
rational rate.

**Build:** `transcribe/timebase.py`
- `probe(media_path) -> Timebase(fps_num, fps_den, ntsc: bool, sample_rate, duration_ms)`
  via `ffprobe -select_streams v:0 -show_entries stream=r_frame_rate,avg_frame_rate`.
  Use `avg_frame_rate` as truth; if `r_frame_rate != avg_frame_rate`, the media is VFR —
  flag it (see GAP-2).
- `ms_to_frame(ms, tb) -> int` and `frame_to_ms(frame, tb) -> float` using exact integer
  math on the fraction (`frame = round(ms * fps_num / (fps_den * 1000))`). No float fps
  anywhere in the codebase — grep-able rule: the literal `29.97` must never appear.
- Schema: add `media.fps_num INTEGER, media.fps_den INTEGER, media.is_vfr INTEGER` via the
  existing idempotent `_migrate()`.

**Accept:** round-trip `ms → frame → ms` error < half a frame for 23.976/24/25/29.97/30/
59.94 across a 4-hour duration (this is exactly where float fps accumulates drift).

### GAP-2 · VFR media (phone footage) silently breaks frame math
Phone and screen-recorded sources are variable frame rate. Timestamps from audio are fine,
but frame-number conversion against a nominal rate drifts.

**Build:** in `ingest.py`, when `is_vfr`, emit a warning into the job record and (config
flag `ingest.conform_vfr: true`) transcode a CFR proxy via
`ffmpeg -vsync cfr -r <detected>` for any downstream frame-based export. Transcription
itself keeps using the original audio.

**Accept:** a VFR test fixture produces a job tagged `is_vfr=1` and XML export refuses to
run against the original file unless a conformed proxy exists.

### GAP-3 · VAD truth is computed, then thrown away
Silero VAD runs in ingest but its speech/silence timeline isn't persisted. You designed
this as the master timeline; CutDeck needs it, and the hallucination filter should use it
(a token whose span sits >80% inside VAD-silence is a stronger hallucination signal than
the current >3× repeat rule).

**Build:**
- Persist VAD output: table `speech_span(job_id, idx, start_ms, end_ms, kind {'speech','silence'})`.
- `normalize.py` Phase 6b: add `_drop_tokens_over_silence(tokens, spans, overlap=0.8)`
  alongside the repeat filter. Config-gated, default on.

**Accept:** synthetic test — inject a fake token over a known silence span, assert it is
dropped; a token straddling a boundary at 50% overlap is kept.

### GAP-4 · Chunk-boundary duplicate tokens
Per-chunk transcription with offset-to-global timestamps will produce duplicated or
truncated words wherever chunks overlap (and they should overlap ~0.5–1 s, or you lose
words at boundaries).

**Build:** `pipeline/stitch.py` — overlap-aware merge: in the overlap window, keep the
token whose span is more interior to its own chunk; tie-break on confidence then length.
Runs after each engine, before align_hyp.

**Accept:** MockEngine test with two chunks sharing a duplicated word at the seam yields
exactly one token.

### GAP-5 · Bias terms have no defined injection mechanism
`EngineInput.bias_terms` exists, but the spec never says how Whisper consumes them. The
only mechanism Whisper has is `initial_prompt`, which is capped (~224 tokens) and Thai is
token-expensive — an unbounded bias list silently truncates.

**Build:** `flywheel/inject.py` — `build_prompt(bias_terms, budget_tokens=200)`:
sort by `weight * recency`, greedily pack using the engine tokenizer's count, join Thai
terms with spaces deliberately (prompt-only; never affects output normalization). Each
engine adapter decides how to consume the string (`whisper_*`: `initial_prompt`; future
engines: their own slot — this stays behind the contract).

**Accept:** with 500 fake terms the prompt never exceeds budget; highest-weight terms
always survive packing.

### GAP-6 · Gold-set authoring has no tooling
The harness reads `eval/goldenset/*.json` but nothing creates them, so the gold set will
rot or never grow. The cheapest gold source you have is a fully human-corrected job.

**Build:** CLI `python -m transcribe.eval.promote --job-id N` — exports the corrected
token stream (corrections applied) + audio reference into a goldenset JSON, runs
`normalize` on it (so gold and hypotheses share the style authority by construction),
and refuses to promote a job with unsaved editor changes.

**Accept:** promoting a job then running the harness scores that file; promoting twice
is idempotent.

### GAP-7 · Corrections carry no *reason* — your level-2 flywheel (taste rubric) starves
`correction` rows record the what, not the why. Auto-generating a living rubric later
requires even a coarse reason signal.

**Build:** add `correction.reason TEXT NULL` + the editor offers a one-tap tag set:
`misheard / spelling / code-switch boundary / name-term / style / other`. Optional, never
blocks save.

**Accept:** save with and without reason both succeed; reason lands in the row.

### GAP-8 · No job resumability
A 3-hour file that crashes at Engine B restarts from zero. Add per-phase checkpointing:
`job.phase_completed` + serialized intermediate (EngineResult per engine) to
`jobs/{id}/checkpoint/`. `run_file(..., resume=True)` skips completed phases.

**Accept:** kill the pipeline after Engine A on a test file; resume completes without
re-running Engine A (assert via call counter on MockEngine).

### A.2 Smaller notes (do when touched, no dedicated phase)
- **Loudness pre-pass:** EBU R128 normalization (`ffmpeg loudnorm`) before VAD makes the
  VAD threshold stable across cameras/mics — one config flag in ingest.
- **Editor low-confidence highlighting:** color tokens by `confidence`/`source_engine`
  (disagreement slots first) so correction time goes where the signal is weakest. This is
  the single highest-leverage UI feature for flywheel throughput.
- **`eval_run` should record `pipeline_version` + active engine pair + bias-index hash** so
  regressions are attributable. One migration, three columns.

---

# PART B — CutDeck: the rough-cut system

## B.0 Position vs. existing tools (why build, what to steal)

I surveyed the field. auto-editor is a command-line tool that analyzes media first, then cuts silent and low-activity sections to speed up the first rough pass, with export to Adobe Premiere and DaVinci Resolve, and its `--margin` padding concept is the right call — cutting too aggressively, clipping the first word of a sentence, is what makes an automatic rough cut feel mechanical. TimeBolt's core argument is also correct: waveform-level silence detection is far more precise than transcript-based cut points, so words never get cut off. Recut validates the non-destructive model: analyze, build a cut list, export XML to the editor of choice. Descript/Gling own the semantic layer (filler words, bad takes) but are cloud, English-centric, and closed.

Nobody combines all four properties you need: **(1)** waveform-precise cut boundaries,
**(2)** transcript-level semantic decisions for *Thai* (fillers, retakes, false starts),
**(3)** FCP7 XML *round-trip* so your Premiere edits become labeled training data, and
**(4)** local, model-agnostic, eval-gated. That combination is the build. We deliberately
do **not** rebuild auto-editor's renderer — Premiere is the renderer; CutDeck only ever
manipulates a timeline description.

## B.1 Core design: the layered timeline

Everything operates on one data structure per job, built from data the transcriber already
produces:

```
Layer 0  VAD spans         sample-accurate speech/silence   (GAP-3 table)
Layer 1  tokens            word text + ms spans             (token table)
Layer 2  segments          sentence/utterance grouping      (built here)
Layer 3  labels            filler | false_start | retake |
                           mistake | keep-worthy            (rules + LLM)
Layer 4  cut plan          ordered keep spans with reasons  (the output)
```

**The boundary rule that makes cuts feel human:** semantic layers (2–3) decide *what* to
cut; Layer 0 decides *where* the blade lands. A segment marked "cut" is trimmed to the
nearest VAD silence boundary, then padding is applied: default **+250 ms pre-roll, +120 ms
post-roll** of kept audio around speech (asymmetric — attack matters more than decay),
both configurable. This is the TimeBolt precision + Descript semantics hybrid, and it's
why CutDeck never clips a word even when the LLM is deciding the cut.

## B.2 Package layout

```
Transcriber_v2/
└── cutdeck/
    ├── contracts.py      Segment, Label, CutSpan, CutPlan, Timebase (re-export)
    ├── segment.py        token stream → segments
    ├── rules.py          deterministic: silence, fillers, min-clip merge
    ├── takes.py          LLM keep/cut classifier (retakes, false starts, mistakes)
    ├── plan.py           assemble + serialize CutPlan JSON (versioned)
    ├── xml_export.py     CutPlan → FCP7 XML
    ├── xml_import.py     edited FCP7 XML → CutSpan[] (round-trip)
    ├── preview.py        optional ffmpeg concat preview render
    ├── flywheel/
    │   ├── diff.py       proposed plan vs imported plan → CutCorrection[]
    │   └── rubric.py     few-shot retrieval + (later) auto rubric
    ├── eval/
    │   ├── metrics.py    cut precision / recall / boundary error
    │   └── harness.py    regression gate, mirrors transcribe pattern
    └── server.py         review UI endpoints (mounted into existing FastAPI app)
```

## B.3 Module specs

### `segment.py` — utterance segmentation
Group tokens into segments by: gap > `segment.gap_ms` (default 700) **or** VAD silence
span between tokens > 500 ms. Each segment: `id, start_ms, end_ms, token_ids[], text`.
Thai has no sentence punctuation to lean on — gaps are the honest signal; do not import a
sentence tokenizer for this.

### `rules.py` — the deterministic pass (no LLM, ever)
1. **Silence cuts:** any VAD silence span > `cut.min_silence_ms` (default 900) becomes a
   cut, shrunk by the pre/post padding above. Silences shorter than the threshold are
   *pace*, not dead air — leave them.
2. **Filler removal (config-gated, default conservative=off):** match whole tokens against
   the filler lexicon in `config.yaml`. Seed Thai list: `เอ่อ, อ่า, อืม, เอิ่ม, แบบ, แบบว่า,
   ก็คือ, คือว่า, อะไรอย่างเงี้ย, อะไรงี้, นะครับ*` plus English `um, uh, like, you know`.
   `*` marks context-sensitive entries that are only cut when isolated (surrounded by
   silence ≥ 200 ms on both sides) — `แบบ` and `ก็คือ` are real words in normal speech;
   cutting them mid-sentence is how transcript tools mangle Thai. Start with only the
   always-safe subset enabled.
3. **Min-clip merge:** after all cuts, any kept clip < `cut.min_clip_ms` (default 1200)
   merges into its neighbor (keep direction: toward the longer neighbor). Prevents
   confetti timelines.

**Accept:** golden fixture audio with known silences produces byte-identical CutPlan
across runs (determinism test); no kept clip shorter than min_clip_ms; padding verified
to never overlap an adjacent kept clip.

### `takes.py` — the LLM classifier (the only judgment module)
Inherits the transcriber's reconciler discipline exactly:

- Input: numbered segment list (id, text, duration, gap-before). **No timestamps in the
  decision space.**
- Output contract: JSON `[{id, action: keep|cut, reason}]` — ids must be a subset of the
  input ids, every id covered, **assertion-enforced**. The LLM never emits a timecode,
  never rewrites text. Select-only, same as reconcile.py.
- Targets exactly three patterns: **repeated takes** (near-duplicate adjacent segments —
  pre-filter candidates with char-Jaccard > 0.55 within a 5-segment window so the LLM only
  sees plausible clusters, keep-last-take by default), **false starts** (segment < 2.5 s
  followed immediately by a longer segment sharing a prefix), **explicit mistakes**
  (speaker self-flags: "เดี๋ยวเอาใหม่", "ตัดตรงนี้", "อันนี้ผิด", "เมื่อกี้พูดผิด", "เอาใหม่นะ" —
  these phrases also work as a *deterministic* pre-pass marker before the LLM sees
  anything; rule-detect them in `rules.py`, LLM only resolves *how far back* the retake
  reaches).
- Few-shot slot: `rubric.py` injects up to 10 past CutCorrections retrieved by segment
  similarity (level-1 flywheel, live from day one).
- Engine-agnostic: `llm_fn` is injected, same pattern as the reconciler — Anthropic API
  today, anything later.

**Accept:** classifier output failing the id-subset assertion raises (test with a mock
LLM returning a hallucinated id); duplicate-take fixture keeps exactly the last take.

### `plan.py` — CutPlan, the system's contract artifact
```json
{
  "plan_version": "1.0", "job_id": 42, "media_sha256": "...",
  "timebase": {"fps_num": 30000, "fps_den": 1001},
  "spans": [
    {"idx": 0, "src_in_ms": 0,    "src_out_ms": 14520, "action": "keep"},
    {"idx": 1, "src_in_ms": 14520,"src_out_ms": 16900, "action": "cut",
     "reason": "silence", "source": "rule"},
    {"idx": 2, "...": "...", "reason": "retake", "source": "llm",
     "segment_ids": [17, 18]}
  ]
}
```
Spans are contiguous and exhaustive over the media duration (assert: no gaps, no
overlaps) — a cut is represented, not deleted, so the review UI and the diff both have
the full picture. Stored in DB (`cut_plan` table, JSON column + status
`proposed|reviewed|exported|reimported`).

### `xml_export.py` — FCP7 XML out
- One `<sequence>`, video track + linked audio track(s), one `<clipitem>` per keep-span,
  all referencing a single `<file>` element (Premiere convention: the full file listing appears once; later references point back via the id attribute).
- Frame math through `timebase.py` only. Rate is expressed as integer timebase + ntsc flag: timebase 30 with ntsc TRUE means 30000/1001; same scheme for 23.976 — timebase 24 with ntsc TRUE, versus true 24 fps with ntsc FALSE. Map: fps_den==1001 → ntsc TRUE with timebase = fps_num/1000 rounded; else ntsc FALSE.
- `pathurl` as `file://localhost/` URL-encoded absolute path (Windows drive letters need
  the `file://localhost/C%3a/...` form — test on your actual machine).
- Embed `job_id`, `plan_id`, and per-clipitem `span idx` in `<comments>`/clip names
  (`cd042_p007_s0012`) — this is the round-trip key.

**Accept (the only acceptance that matters):** import into your Premiere, on your footage,
at 29.97 — every cut lands on the intended frame at the end of a 1-hour timeline, audio
stays linked, no offline media. Paper-passing is explicitly not passing.

### `xml_import.py` + `flywheel/diff.py` — the editing-taste flywheel
- Parse the XML Premiere exports after you polish the rough cut. Recover spans from
  clipitem in/out frames → ms via the stored timebase; match clips to plan spans by the
  embedded name key, fall back to overlap matching for clips you split manually.
- Diff against the proposed plan → `cut_correction` rows:
  `(plan_id, span_idx, proposed_action, final_action, boundary_delta_in_ms,
  boundary_delta_out_ms, segment_text, label_source {rule|llm}, reason NULL)`.
  Three correction species fall out automatically: **decision flips** (I said cut, you
  kept it — feeds `takes.py` few-shots), **boundary nudges** (systematic padding error —
  if median pre-roll delta across 50+ corrections exceeds 80 ms, auto-suggest a config
  change rather than silently learning it), **manual splits** (segmentation was too
  coarse — feeds `segment.gap_ms` tuning).
- Zero extra effort by design: you edit in Premiere as normal; re-import is one CLI call
  or a drop-zone in the review UI.

### `eval/` — the gate, before the flywheel ships anything
Mirror of the transcriber harness, built **first** (your own frozen-eval-first principle):
- Golden set = (media, final human cut plan) pairs — your first 3–5 fully polished
  round-trips become the corpus via a `promote` CLI, same as GAP-6.
- Metrics: **cut recall** (fraction of human cut-time the system also cut — dead air it
  missed), **keep precision** (fraction of system-kept time the human also kept — good
  content it wrongly killed; this is the one that must stay near 1.0, a false cut is much
  worse than a missed one), **boundary MAE** in ms over matched cut edges.
- Gate: any rubric/few-shot/config change that worsens keep-precision by > 1% absolute on
  the golden set is rolled back automatically. Same `eval_run` table, new `kind` column.

### `server.py` — review UI (assisted mode)
Extends the existing editor app, one new page per job:
- Transcript rendered as segments, color = action (keep/cut) + source (rule/llm), reason
  on hover. Click toggles keep⇄cut; drag handles on span edges snap to VAD boundaries
  (never free-floating — the UI physically cannot create a mid-word cut).
- Audio scrub with cut spans grayed; spacebar plays "as cut" (skips cut spans) — this is
  the feature that makes review take minutes instead of an hour.
- Buttons: *Export XML*, *Re-import edited XML*, *Accept all rules / review LLM only*
  (the rule cuts are trustworthy fast; human attention goes to the judgment calls).
- Every toggle in this UI is also a `cut_correction` — the flywheel feeds whether you
  correct in the browser or in Premiere.

### `preview.py` (optional, last)
`ffmpeg` concat-demuxer stream-copy preview of the keep spans (keyframe-imprecise but
instant) for a sanity watch before opening Premiere. Flagged clearly as approximate.

## B.4 Schema additions (one migration)
```sql
speech_span(job_id, idx, start_ms, end_ms, kind)
cut_plan(id, job_id, plan_json, status, created_at)
cut_correction(id, plan_id, span_idx, proposed_action, final_action,
               boundary_delta_in_ms, boundary_delta_out_ms,
               segment_text, label_source, reason, created_at)
-- media: + fps_num, fps_den, is_vfr        (GAP-1/2)
-- correction: + reason                      (GAP-7)
-- eval_run: + kind, pipeline_version, engine_pair, bias_hash
```

## B.5 Config additions
```yaml
cut:
  min_silence_ms: 900
  pad_pre_ms: 250
  pad_post_ms: 120
  min_clip_ms: 1200
  fillers_enabled: false          # turn on after first eval baseline
  filler_lexicon: [เอ่อ, อ่า, อืม, เอิ่ม, um, uh]
  filler_lexicon_contextual: [แบบ, แบบว่า, ก็คือ, คือว่า, like, you know]
  retake_markers: [เดี๋ยวเอาใหม่, เอาใหม่นะ, ตัดตรงนี้, อันนี้ผิด, เมื่อกี้พูดผิด]
  llm_enabled: true
  keep_last_take: true
segment:
  gap_ms: 700
```

## B.6 Build order

| Phase | Scope | Done when |
|---|---|---|
| **0** | GAP-1 timebase + GAP-3 VAD persistence + schema migration | round-trip frame test green on 6 rates; speech_span populated on a real job |
| **1** | `segment.py` + `rules.py` + `plan.py` | deterministic CutPlan on real footage; determinism + min-clip + padding tests green |
| **2** | `xml_export.py` | **a real 29.97 file imports clean into your Premiere, frame-accurate at the 60-min mark** |
| **3** | `xml_import.py` + `diff.py` + cut_correction | edit a rough cut in Premiere, re-import, see sensible corrections in DB |
| **4** | `eval/` harness + promote CLI, freeze first golden pair | gate runs; baseline numbers recorded |
| **5** | `takes.py` LLM classifier + retake markers + few-shot slot | retake fixture passes; id-subset assertion test passes; eval gate still green |
| **6** | review UI in `server.py` | toggle→correction→export→reimport loop works end-to-end in browser |
| **7** | GAP-4/5/6/7/8 transcriber items + `preview.py` | each gap's acceptance test green |

Phase 2 before Phase 5 on purpose: the XML round-trip is the riskiest external interface
(Premiere's FCP7 handling has documented quirks) and the flywheel is worthless until it
works on your machine. The LLM is the *least* risky part — it slots into a contract that
already exists.

## B.7 What I deliberately left out
- **Multicam / multi-track sources** — schema-compatible later (CutPlan spans can carry a
  track id), but it doubles XML complexity now for footage you don't shoot yet.
- **Zoom/punch-in generation, captions burn-in, B-roll suggestion** — AutoCut-style
  features that belong after the cut flywheel has data, not before.
- **A custom renderer** — Premiere renders; CutDeck describes. Owning a render path is
  the trap most tools in this space fell into.
- **Fine-tuning anything** — level-3 flywheel stays deferred until cut_correction has
  hundreds of rows, per your existing plan.
