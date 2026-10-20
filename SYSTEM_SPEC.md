# Transcriber v2 — System File Specification

A batch, offline **Thai-primary code-switch ASR pipeline**. Two ASR engines transcribe the
same audio independently; a select-only reconciler merges them; output is normalized,
force-aligned (when needed), stored, human-corrected, and the corrections feed a flywheel
that biases future runs — gated by an eval harness that blocks accuracy regressions.
A CutDeck sub-system turns the token+VAD timeline into Premiere Pro rough cuts.

**Stack:** Python **3.11.9** (venv; older docs said 3.13 — wrong) · faster-whisper/CTranslate2
· PyTorch/torchaudio · HuggingFace transformers · silero-vad · SQLite · FastAPI · PyThaiNLP

---

## 1. Top-level layout

```
B-transcriber/
├── CLAUDE.md                  # agent guidance (architecture rules, engine list)
├── STYLE_GUIDE.md             # transcription style decisions (gold-authoring policy)
├── SYSTEM_SPEC.md             # this document
├── TODO_LEDGER.md             # deferred work, each entry with a due-when trigger
├── docs/                       # BUILD_PLAN.md · HANDOFF_*.md · IMPLEMENT_*.md — historical build/handoff docs
├── requirements.txt · setup.py
├── transcriber.db             # SQLite store (schema in transcribe/db/schema.sql)
├── models/whisper-th-medium-ct2/   # CT2-converted Engine A checkpoint (local, untracked)
├── tests/                     # 184 tests, MockEngine-based (no GPU needed)
├── tools/                     # make_gold.py, bench_transcribe.py, dev utilities
├── scripts/                   # learn_from_srt.py, export_job.py, preflight.py
├── cutdeck/                   # Part B: rough-cut planning + FCP7 XML export
└── transcribe/                # the package
    ├── service.py             # unified transcription entry point (shared DB, sha256 cache)
    ├── review.py              # targeted acoustic review & suspicion reasons
    ├── contracts.py           # engine contracts & token data structures
    ├── audio/                 # decode, VAD windowing, and span stitching
    ├── cues/                  # cue splitting and layout policies
    ├── db/                    # SQLite persistence (schema.sql + store.py)
    ├── editor/                # FastAPI review & correction editor
    ├── engines/               # ASR adapters (faster_whisper, qwen3_asr, etc.)
    ├── eval/                  # metrics (v4), paired regression gate, evaluation harness
    ├── flywheel/              # correction capture, diffing, bias index, prompt injection
    ├── pipeline/              # orchestration (run.py), plan, refine, coverage guard (coverage.py)
    ├── subtitles/             # subtitle formatting and layout
    └── thai/                  # Thai language atoms and lint rules
```

---

## 2. The contract layer — `transcribe/contracts.py`

**The single most important boundary.** Every ASR model is reached only through these
dataclasses; nothing outside `engines/` may import a concrete model.

| Type | Role |
|---|---|
| `EngineInput` | `audio_path` or pre-decoded `audio` array, `bias_terms[]`, `bias_weights{}`, `language_hint` |
| `RecognizedToken` | engine output unit: `text, start_ms, end_ms, confidence (None-able), script` |
| `EngineResult` | `tokens[], engine_name, timestamps_final, raw{}` — `timestamps_final=True` means the cue timestamps are final (skip forced alignment); `raw["words"]` keeps the per-word list for on-demand re-derivation |
| `PipelineToken` | post-reconcile unit: adds `idx, source_engine ('a'\|'b'\|'both')` |
| `detect_script(text)` | classifies → `thai \| latin \| mixed \| other` (Thai block U+0E00–0E7F vs ASCII alpha) |

Rule: `confidence=None` if the engine gives none — **never faked**.

### 2.1 Service & Review — `transcribe/service.py` and `transcribe/review.py`

- **`service.py`** — The single transcription entry point for all frontends (CLI, web editor, Rough Cut, helper daemon, MCP). Wraps `pipeline.run.run_file_job`, anchors all callers to the shared database path (`store.resolve_db_path`), provides sha256 transcript caching, passes job glossaries into `EngineInput.bias_terms`, attaches `job_id`, and surfaces `coverage_gaps` and `review_flags` on the returned `Transcript`.
- **`review.py`** — Targeted acoustic review (`suspicion_reasons(cue) -> list[str]`). Evaluates cues for acoustic and lexical anomalies: short duration (<500 ms), high character density (>25 chars/sec), low recognition confidence (<0.8), unfamiliar Thai fragments outside PyThaiNLP corpus and colloquial atoms, and high compression ratio segments. Produces ranked `review_flags` prioritizing human inspection or targeted re-decode without generating text or inventing word timings.

---

## 3. Engines — `transcribe/engines/`

Config-driven, registry-dispatched, lazily imported. Per-engine construction knobs live
under `config["engines"][<registry name>]` (model_id, compute_type, beam_size, cue
thresholds, batch_size, bias budget) — an engine/model/compute swap is a YAML edit.

| File | Name | Model / role | Status |
|---|---|---|---|
| `faster_whisper.py` | **Engine A (active)** `faster_whisper` | `biodatlab/whisper-th-medium-combined` via CTranslate2 (`models/whisper-th-medium-ct2`). Whole-file (`prefers_whole_file=True`), `BatchedInferencePipeline` VAD-batched decode, own uncapped Silero VAD pass, long-span split+stitch, truncated-tail recovery, phrase-cue grouping (crfcut sentence boundaries). | active |
| `null_engine.py` | **Engine B (active)** `passthrough` | single-engine fallback — no second hypothesis | active |
| `whisper_thai.py` | `whisper_thai` | same checkpoint via HF transformers — slower per-chunk fallback | registered |
| `whisper_multi.py` | `whisper_multi` | `openai/whisper-large-v3` — multilingual code-switch slot | registered |
| `qwen3_asr.py` | `qwen3_asr` | `Qwen/Qwen3-ASR-1.7B` via `qwen_asr`. LLM-decoder ASR candidate for code-switching; own internal VAD segmentation (`speech_windows`, capped at `max_span_s: 8.0`); context prompt injection. Probed with real disagreements; **not activated** because model transliterates English loanwords into Thai script (model quality, not a reconciler bug; docs/ENGINES.md:53-70). | built, not activated |
| `typhoon_rt.py` | `typhoon_rt` | SCB10X Typhoon ASR Real-time (FastConformer-Transducer, ~115M) via NeMo — decorrelated Engine B candidate. **Rejected**: regresses `cer_thai` and `wer_latin` vs baseline (docs/ENGINES.md:46-52). Do not retry without new evidence. | rejected |
| `funasr.py` | `funasr` | `SenseVoiceSmall`. **Retired**: model has no Thai support (only zh/en/yue/ja/ko); auto-detects Thai as Cantonese and emits CJK garbage (docs/ENGINES.md:31-40). Do not re-probe without a different model. | retired |
| `mock.py` | `mock` | canned tokens, no GPU — used by all pipeline tests | tests only |
| `base.py` / `registry.py` | — | `Engine` ABC (`load → transcribe → unload`), `@register` + `get_engine()` | — |

**VRAM discipline (RTX 3070, 8 GB):** engines run strictly sequentially —
`load → run → unload() → del → torch.cuda.empty_cache()`. Never two models resident at once.
Enforced in `pipeline/run.py`. CUDA OOM in batched decode auto-halves `batch_size`.

---

## 4. Pipeline — `transcribe/pipeline/` (orchestrated by `run.py`)

```
audio
 │
 ├─[ingest.py]      decode ONCE (librosa / PyAV for AV containers) → optional rolling
 │                  in-memory DeepFilterNet denoise (only when a chunk engine is active)
 │                  → Silero VAD (pip silero-vad, hub fallback) → speech/silence span
 │                  timeline (persisted to speech_span) + overlapping AudioChunks
 │                  (chunk_overlap_ms) when a chunk engine needs them
 │
 ├─[Engine A]       whole-file or per-chunk transcribe; per-chunk output goes through
 ├─[Engine B]       [audio/decode.py, audio/stitch.py] seam-window dedup. Sequential;
 │                  VRAM freed between engines.
 │                  A whole-file engine turns its word pieces into subtitle-grade
 │                  phrase cues via [cues/] split_cues(words, CuePolicy) — shared,
 │                  engine-agnostic, and the owner of cue_boundary_error_rate.
 │                  Each engine's token list is persisted to engine_result (job_phase
 │                  checkpoints: ingested → engine_a_done → engine_b_done → reconciled →
 │                  written) so a re-run of a failed job reuses cached GPU work.
 │
 ├─[align_hyp.py]   greedy A↔B match (0.6·time-overlap + 0.4·char-Jaccard) inside a
 │                  sliding temporal window (near-linear) → AlignSlot[]
 │
 ├─[reconcile.py]   SELECT one candidate per slot → (RecognizedToken, source_engine).
 │                  agree → 'both' (merged span/conf); disagree → optional llm_fn
 │                  (llm_reconcile.py, local Ollama, gated by reconciler.llm_enabled)
 │                  else _script_fallback (confidence first, script only as tiebreak).
 │                  Select-only enforced by ReconcilerViolation raise (survives -O).
 │
 ├─[normalize.py]   deterministic text policy (§6) → _filter_hallucinations (loop
 │                  collapse + >3× repeat drop) → drop_tokens_over_silence (VAD overlap)
 │
 ├─[coverage.py]    coverage guard — detects speech gaps (≥600ms) and re-decodes them
 │                  within Engine A residency; unfilled gaps reported, never invented
 │
 └─[align_force.py] ONLY when timestamps_final is False: word expansion + CTC forced
                    alignment (torchaudio MMS_FA, LinearFallbackAligner on failure).
                    faster-whisper cues skip this entirely.
        → tokens written to DB (job + token rows) · [subtitles/] write_subtitles
```

`run.py` entry: `run_file(audio_path, config, db_path) → list[token dict]`.
CLI: `python -m transcribe.pipeline.run audio.wav --config transcribe/config.yaml`.
`PIPELINE_VERSION = "1.0.0"`.

Behind that one entry point, four **internal** seams (private to
`transcribe/pipeline/`, absent from its `__init__` exports — `run_file`'s own
interface is unchanged and is what every caller depends on):
`plan.py` decides everything pure (engine names incl. the canonical
`self_ensemble` label, which phases a resumed job skips, self-ensemble validity,
whether ingest must cut chunks) as a function of config plus one resume phase, with
no engine instantiated; `engine_run.py` owns the load → decode → unload → `del` →
`empty_cache` → persist → advance-phase bracket once, for both the real-Engine-B
and self-ensemble-pseudo-B cases; `coverage.py` finds speech gaps (≥600 ms) that
produced no cue (`find_gaps`), detects isolated orphan cues adjacent to gaps
(`find_orphans`), and offers gaps a second decode (`fill_gaps`) within Engine A's
residency without generating text; `refine.py` is the post-decode token pipeline
(align → reconcile → normalize → filter → silence drop → conditional word
expansion → conditional forced alignment → cue conform), taking its aligner as an
injected dependency.

**Two reconciler invariants:** it *selects, never generates* (exception-enforced), and
agreeing tokens skip the LLM entirely — only disagreements invoke it.

**Token granularity:** tokens persisted to the DB are **phrase cues** (~subtitle-length,
`cue_gap_ms`/`cue_max_ms`/`cue_target_chars`). Word granularity is re-derived on demand
from `engine_result.raw_words_json` (CutDeck Phase 5 filler excision).

---

## 5. Persistence — `transcribe/db/`

- **`schema.sql`** — single source of truth. Tables: `media` (sha256-deduped, timebase +
  `is_vfr`), `job` (incl. `job_phase` resume checkpoint), `token`, `correction`,
  `speech_span` (VAD master timeline), `cut_plan` (CutDeck), `bias_term`,
  `engine_result` (cached per-engine token lists + raw word timestamps), `eval_run`.
- **`store.py`** — the *only* place raw SQL is allowed; everything else calls typed
  functions returning row dataclasses. `init_db()` + idempotent, additive-only
  `_migrate()` (column adds for pre-existing DBs).

Key columns: `token.source_engine ∈ {a,b,both,reconciler}`; `token.speaker_id` nullable
(reserved for v2 diarization — do not remove); `correction.source_engine` (flywheel
down-weights stale-engine corrections) + `correction.corrected_span` (sub-cue promotable
term); `bias_term.added_by ∈ {manual,flywheel}` + `weight`; `eval_run.is_experiment`
(A/B probes never become the baseline) + `eval_run.metrics_version` (baselines partition
by metric definition — see §7).

---

## 6. Normalization — `transcribe/pipeline/normalize.py`

The **single source of truth for STYLE_GUIDE.md**, applied *identically* to hypotheses
(run.py) and the gold set (eval) so the metric never scores against a moving target.
Deterministic, tokenization-free. Order: Thai digits ๐-๙→0-9 → mai-yamok ๆ canonicalize
(no expansion — deliberate divergence from Na-Thalang/Typhoon, STYLE_GUIDE §3) →
Thai↔Latin boundary spacing → protect exception lexicon → PyThaiNLP cleanup → restore
exceptions → collapse spaces. Exception lexicon (COVID-19, iPhone, Shopee, LINE OA…)
lives in `config.yaml`.

---

## 7. Evaluation — `transcribe/eval/`

- **`metrics.py`** — five gated signals on well-defined units (`METRICS_VERSION = 4`):
  - **`cer_thai`** — character error rate over Thai-script content (primary Thai signal;
    tokenization-free because Thai has no word boundaries)
  - **`wer_latin`** — case-insensitive word error over Latin/digit runs
  - **`boundary_error_rate`** (BER) — temporal switch-point error (`1 − micro-F1`
    over character-interpolated switch timestamps within `boundary_tol_ms`)
  - **`cue_boundary_error_rate`** (cue_BER, v3) — `1 − micro-F1` of ref vs hyp cue-start
    timestamps (matched within tolerance; tokens are phrase cues, so each token start_ms
    is a cue boundary)
  - **`speech_coverage_miss`** (coverage_miss, v4) — ms of reference cue time that no
    hypothesis cue overlaps, divided by total reference cue time (`missed_speech_ms / ref_speech_ms`).
    Catches speech that produced no text at all, which CER averages away.
  - **Hard invariant:** `overlapping_cues == 0` asserted on hyp cues alone (not a rate;
    any overlap fails the gate).
  - **Descriptive-only stats:** `wer` (coarse sanity number, **never the gate**),
    `cue_count_delta` (hyp cue count − ref cue count), `shortest_cue_ms` (shortest hyp cue duration),
    `nonzero_gap_count` (positive gap count between consecutive hyp cues), and
    `orphan_cues` (isolated hyp cues under 300 ms with clear time to adjacent cues ≥300 ms).
- **`gate.py` / `harness.py`** — `run_harness()` runs the golden set (`eval/goldenset/*.json` +
  audio/AV pair) through the pipeline in a scratch DB (bias index mirrored in),
  aggregates corpus-level rates, records an `eval_run` stamped with
  `metrics_version`, and **fails** if any of the five gated signals (`cer_thai`,
  `wer_latin`, `boundary_error_rate`, `cue_boundary_error_rate`, `speech_coverage_miss`)
  regresses beyond `regression_tolerance` (+`regression_abs_floor`) via paired delta
  bootstrap 95% CIs vs the last passing **production** run of the **same metrics version**,
  or if `overlapping_cues > 0`. CLI `--engine-b X` / `--llm-enabled` /
  `--experiment` mark A/B probes that are judged against the baseline but can never
  become it. An empty gold set refuses to write a run.

CLI: `python -m transcribe.eval.harness --config transcribe/config.yaml --db transcriber.db`.

---

## 8. Flywheel — `transcribe/flywheel/`

```
web-editor edits ─[diff.py]────────→ CorrectionPair[] (idx-matched; corrected_span =
                                     minimal changed word/phrase, not the whole cue)
final NLE .srt  ─[align_srt.py]───→ (scripts/learn_from_srt.py CLI) connected-components
                                     time-overlap grouping — survives Premiere re-cut/
                                     re-time/merge/split — → correction rows
                        → correction table
                 [biasindex.py] weight by staleness (active engine ×1.0, swapped-out
                                ×stale_engine_weight), promote terms crossing
                                min_occurrences, refuse sentence-length terms
                        → REGRESSION GATE: run_harness is the single gate authority;
                          new terms rolled back on regression
                        → bias_terms + weights feed the next run's EngineInput
                 [inject.py]   budget-aware prompt packing (CT2 tokenizer counts,
                                highest weight×recency first) → initial_prompt
```

---

## 9. Editor — `transcribe/editor/`

FastAPI backend (`server.py`) + single-page `static/index.html`. Correction-capture only.
Shows per-token confidence + corrected state; one-tap reason tags (misheard, spelling,
code-switch boundary, name/term, style) ride into `correction.reason`.

| Endpoint | Purpose |
|---|---|
| `GET /jobs`, `GET /jobs/{id}` | list jobs / job + tokens (saved corrections merged in) |
| `GET /jobs/{id}/audio` | stream source audio |
| `POST /jobs/{id}/save` | diff submitted tokens vs original → upsert `correction` rows |
| `GET /jobs/{id}/export/{srt,vtt}` | download corrected subtitles |

Run: `uvicorn transcribe.editor.server:app --port 8000`.

---

## 10. CutDeck — `cutdeck/` (Part B: rough cuts for Premiere)

| File | Role |
|---|---|
| `contracts.py` | `Segment/Label/CutSpan/CutPlan/CutConfig` + Timebase re-export; `CutSpan.blade` (`BLADE_VAD`/`BLADE_WORD`) marks whether an edge came from a VAD silence boundary or a word timestamp inside continuous speech |
| `words.py` | word-timeline reconstruction (`Word`, `words_from_pieces`, `words_for_job`) from raw sub-word ASR pieces — the one implementation shared with `transcribe/engines/faster_whisper.py`'s cue grouping |
| `segment.py` | gap/VAD utterance segmentation over the token + speech_span timeline |
| `rules.py` | deterministic cut pass; two rough-cut modes via `cut.rough_cut_mode` (default `interval`: silence-interval subtraction + min-clip merge; opt-in `segment`: keeps built outward from segments, no merge/dissolve needed), plus word-level `filler_cuts` (on the Phase 1 word timeline, config-gated) and `repeat_cuts` (deterministic stutter/duplicate-word n-gram detector, segment-bounded, config-gated) — both apply identically in either mode |
| `plan.py` | contiguous/exhaustive CutPlan, JSON round-trip, `cut_plan` store glue, CLI `python -m cutdeck.plan --job-id N` |
| `preview.py` | ffmpeg concat-demuxer stream-copy render of a plan's KEEP spans — a fast, keyframe-imprecise sanity watch (labelled approximate in filename + CLI output), not a frame-accuracy check; `--reencode` for a slow frame-accurate render; CLI `python -m cutdeck.preview --job-id N [--reencode] --out preview.mp4` |
| `sequence_mixdown.py` | thin `ingest()` → `build_cut_spans()` wrapper over a live sequence's own audio mixdown; superseded (issue #17/#20) by the since-retired `live_clip.py`; kept in place, currently unused |

The retired ExtendScript/QE-DOM `in_place` mode (`jsx_export.py`, razor + reverse-
chronological ripple-delete) has been removed — see `TODO_LEDGER.md` for why and
`docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md`'s superseded-banner for the corrected history.
`mark` (split + disable, then one atomic ripple-delete of everything still disabled via
a UXP plugin) replaces it.

Status: see `docs/HANDOFF_CUTDECK_WORDLEVEL.md` for the authoritative phase-by-phase log.
Phases 0–2 (rough cut, FCP7 export, word-level fillers/stutters/blade contract),
Phase 3 (`preview.py` feedback loop), and Phase 4 (segment-first rough cut,
opt-in via `cut.rough_cut_mode: segment`) are built and unit-tested;
real-Premiere import acceptance on a 29.97 file is still pending and blocks
Phases 5–6 (dead-air wins, `takes.py` LLM retake resolution), which are not
started. `segment` mode itself also stays opt-in (default is still `interval`)
until watched on real footage.

---

## 11. Config — `transcribe/config.yaml`

Drives the whole system without code edits: `engine_a`/`engine_b` selection, per-engine
blocks under `engines:`, ingestion (denoise, Thai-tuned VAD thresholds 0.35/500,
`chunk_overlap_ms`), `boundary_tol_ms`, the `normalization` policy + exception lexicon,
`regression_tolerance` + `regression_abs_floor`, `flywheel` knobs, `reconciler.llm_enabled`
+ local Ollama settings, and the `cut:`/`segment:` CutDeck blocks.

**To swap an engine:** add adapter in `engines/` → `@register` it → add an `engines:`
block → update `config.yaml` → re-run the harness. No pipeline code changes.

---

## Data-flow summary (one line)

`audio → ingest → Engine A ⟂ Engine B (sequential, stitched, checkpointed) → align_hyp →
reconcile(select-only, optional local-LLM tiebreak) → normalize → (align_force if needed)
→ DB → editor/.srt re-import → diff/align_srt → corrections → biasindex → (gated by eval,
baselines partitioned by metrics_version) → next run`
