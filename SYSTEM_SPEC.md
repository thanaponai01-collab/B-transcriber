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
├── BUILD_PLAN.md · HANDOFF_SPEED_AND_ROBUSTNESS.md · IMPLEMENT_*.md   # historical build plans
├── requirements.txt · setup.py
├── transcriber.db             # SQLite store (schema in transcribe/db/schema.sql)
├── models/whisper-th-medium-ct2/   # CT2-converted Engine A checkpoint (local, untracked)
├── tests/                     # 184 tests, MockEngine-based (no GPU needed)
├── tools/                     # make_gold.py, bench_transcribe.py, dev utilities
├── scripts/                   # learn_from_srt.py, export_job.py, preflight.py
├── cutdeck/                   # Part B: rough-cut planning + FCP7 XML export
└── transcribe/                # the package
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
| `funasr.py` | `funasr` | `SenseVoiceSmall` (imports fine on this venv; needs `hub="hf"`). Tried 2026-07-15: gate rejected it (WER_latin regressed; it reports `confidence=None` so it can never win a Thai disagreement) | registered, gated off |
| `typhoon_rt.py` | `typhoon_rt` | SCB10X Typhoon ASR Real-time (FastConformer-Transducer, ~115M) via NeMo — decorrelated Engine B candidate; NeMo not installed yet | adapter built, mock-tested |
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
 ├─[Engine B]       [stitch.py] seam-window dedup. Sequential; VRAM freed between engines.
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
 └─[align_force.py] ONLY when timestamps_final is False: word expansion + CTC forced
                    alignment (torchaudio MMS_FA, LinearFallbackAligner on failure).
                    faster-whisper cues skip this entirely.
        → tokens written to DB (job + token rows) · export_srt / export_vtt
```

`run.py` entry: `run_file(audio_path, config, db_path) → list[token dict]`.
CLI: `python -m transcribe.pipeline.run audio.wav --config transcribe/config.yaml`.
`PIPELINE_VERSION = "1.0.0"`.

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

- **`metrics.py`** — three signals on well-defined units (`METRICS_VERSION = 2`):
  - **`cer_thai`** — char error rate over the Thai stream (primary Thai signal;
    tokenization-free because Thai has no word boundaries)
  - **`wer_latin`** — case-insensitive word error over Latin/digit runs
  - **`boundary_error_rate`** — `1 − F1` of Thai↔Latin switch *timestamps* within
    `boundary_tol_ms`. Since v2, switch points are derived **character-by-character
    inside every token** (a switch inside a `mixed` phrase cue counts, with its
    timestamp linearly interpolated across the cue span) and the corpus number is a
    **micro-F1** over summed matched/ref/hyp counts, so hallucinated switches on
    monolingual clips are penalized. (v1 used token-level script only — at phrase-cue
    granularity that pinned BER at a structural 0.0.)
  - `wer` — coarse sanity number, **never the gate**
- **`harness.py`** — `run_harness()` runs the golden set (`eval/goldenset/*.json` +
  audio/AV pair) through the pipeline in a scratch DB (bias index mirrored in),
  aggregates corpus-level rates, records an `eval_run` stamped with
  `metrics_version`, and **fails** if `cer_thai`, `wer_latin`, or BER regresses beyond
  `regression_tolerance` (+`regression_abs_floor`) vs the last passing **production**
  run of the **same metrics version**. CLI `--engine-b X` / `--llm-enabled` /
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
| `contracts.py` | `Segment/Label/CutSpan/CutPlan/CutConfig` + Timebase re-export |
| `segment.py` | gap/VAD utterance segmentation over the token + speech_span timeline |
| `rules.py` | deterministic silence cuts (padding-shrunk) + config-gated filler removal + min-clip merge |
| `plan.py` | contiguous/exhaustive CutPlan, JSON round-trip, `cut_plan` store glue, CLI `python -m cutdeck.plan --job-id N` |
| `xml_export.py` | CutPlan → FCP7 (xmeml v5) XML for Premiere; rational timebase only, **refuses VFR sources** (GAP-2); CLI `python -m cutdeck.xml_export --job-id N` |

Status: Phases 0–2 built and unit-tested; real-Premiere import acceptance on a 29.97
file still pending. Phase 3 (cut-correction flywheel) and Phase 5 (LLM labels + filler
excision) not started.

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
