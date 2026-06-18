# Transcriber v2 — System File Specification

A batch, offline **Thai-primary code-switch ASR pipeline**. Two ASR engines transcribe the
same audio independently; a select-only reconciler merges them; output is normalized,
force-aligned, stored, human-corrected, and the corrections feed a flywheel that biases
future runs — gated by an eval harness that blocks accuracy regressions.

**Stack:** Python 3.13 · PyTorch/torchaudio · HuggingFace transformers · SQLite · FastAPI · PyThaiNLP

---

## 1. Top-level layout

```
Transcriber_v2/
├── CLAUDE.md                  # agent guidance (architecture rules, engine list)
├── STYLE_GUIDE.md             # transcription style decisions (gold-authoring policy)
├── BUILD_PLAN.md              # phased build plan
├── SYSTEM_SPEC.md             # this document
├── requirements.txt · setup.py
├── transcriber.db             # SQLite store (schema in db/schema.sql)
├── tests/test_smoke.py        # pipeline + reconciler tests (MockEngine, no GPU)
├── tools/                     # engine_sharpener.py, whisper_patch.py (dev utilities)
├── Patch/                     # scratch copies of the tools
└── transcribe/                # the package
```

---

## 2. The contract layer — `transcribe/contracts.py`

**The single most important boundary.** Every ASR model is reached only through these
dataclasses; nothing outside `engines/` may import a concrete model.

| Type | Role |
|---|---|
| `EngineInput` | `audio_path`, `bias_terms[]`, `language_hint` → fed to an engine |
| `RecognizedToken` | engine output unit: `text, start_ms, end_ms, confidence (None-able), script` |
| `EngineResult` | `tokens[], engine_name, word_level_timestamps, raw{}` |
| `PipelineToken` | post-reconcile unit: adds `idx, source_engine ('a'\|'b'\|'both')` |
| `detect_script(text)` | classifies → `thai \| latin \| mixed \| other` (Thai block U+0E00–0E7F vs ASCII alpha) |

Rule: `confidence=None` if the engine gives none — **never faked**.

---

## 3. Engines — `transcribe/engines/`

Config-driven, registry-dispatched, lazily imported (heavy deps load only when used).

| File | Name | Model / role |
|---|---|---|
| `base.py` | `Engine` (ABC) | contract: `load() → transcribe() → unload()` |
| `registry.py` | — | `@register(name)` decorator + `get_engine()` lazy-loader |
| `whisper_thai.py` | **Engine A** `whisper_thai` | `biodatlab/whisper-th-medium-combined` — Thai specialist, word timestamps |
| `whisper_multi.py` | **Engine B** `whisper_multi` | `openai/whisper-large-v3` — multilingual / code-switch slot |
| `funasr.py` | `funasr` | `SenseVoiceSmall` — registered but no Py3.13 wheel (unavailable) |
| `null_engine.py` | `passthrough` | single-engine fallback (Engine A only, no agreement signal) |
| `mock.py` | `mock` | canned tokens, no GPU — used by all tests |

**VRAM discipline (RTX 3070, 8 GB):** engines run strictly sequentially —
`load → run → unload() → del → torch.cuda.empty_cache()`. Never two models resident at once.
Enforced in `pipeline/run.py`.

---

## 4. Pipeline — `transcribe/pipeline/` (orchestrated by `run.py`)

```
audio
 │
 ├─[ingest.py]      Phase 2  decode (librosa/PyAV) → rolling DeepFilterNet denoise
 │                           (only loud windows) → Silero VAD → AudioChunk[]
 │
 ├─[Engine A]       Phase 3  per-chunk transcribe, timestamps offset to global;
 │                           unload → empty_cache
 ├─[Engine B]       Phase 3  same, sequentially (VRAM freed between A and B)
 │
 ├─[align_hyp.py]   Phase 4  greedy match A↔B tokens by (0.6·time-overlap +
 │                           0.4·char-Jaccard) → AlignSlot[] (sorted by start)
 │
 ├─[reconcile.py]   Phase 5  SELECT one candidate per slot →
 │                           (RecognizedToken, source_engine)
 │                           • agree → 'both', merged span/conf
 │                           • disagree → llm_fn(ta,tb) returns INDEX, else
 │                             _script_fallback (thai→A, latin→B, else higher conf)
 │                           • assert chosen.text ∈ candidates  ← no-hallucination gate
 │
 ├─[normalize.py]   Phase 6  deterministic text policy (see §6)
 │                  Phase 6b _filter_hallucinations (drop >3× repeated words)
 │                  Phase 6c _expand_to_words (pythainlp newmm / whitespace) —
 │                           skipped if Engine A gave word timestamps
 │
 └─[align_force.py] Phase 7  CTCForcedAligner (torchaudio MMS_FA) → final per-word
                             timestamps; LinearFallbackAligner if it fails;
                             skipped if Engine A already word-level.
                             Also: export_srt / export_vtt
        → tokens written to DB (job + token rows)
```

`run.py` entry: `run_file(audio_path, config, db_path) → list[token dict]`.
CLI: `python -m transcribe.pipeline.run audio.wav --config config.yaml`. `PIPELINE_VERSION = "1.0.0"`.

**Two reconciler invariants:** it *selects, never generates* (assertion-enforced), and
agreeing tokens skip the LLM entirely — only disagreements invoke it.

---

## 5. Persistence — `transcribe/db/`

- **`schema.sql`** — single source of truth. Tables: `media` (sha256-deduped), `job`,
  `token`, `correction`, `bias_term`, `eval_run`.
- **`store.py`** — the *only* place raw SQL is allowed; everything else calls typed
  functions returning row dataclasses. Handles `init_db()` + idempotent `_migrate()`
  (adds `cer_thai`/`wer_latin` to old DBs).

Key columns: `token.source_engine ∈ {a,b,both,reconciler}`; `token.speaker_id` nullable
(reserved for v2 diarization — do not remove); `correction.source_engine` (lets flywheel
down-weight stale-engine corrections); `bias_term.added_by ∈ {manual,flywheel}` + `weight`.

---

## 6. Normalization — `transcribe/pipeline/normalize.py`

The **single source of truth for STYLE_GUIDE.md**, applied *identically* to hypotheses
(run.py) and the gold set (eval) so the metric never scores against a moving target.
Deterministic, tokenization-free. Order: protect exception lexicon → Thai digits ๐-๙→0-9
→ mai-yamok ๆ canonicalize (no expansion) → Thai↔Latin boundary spacing → PyThaiNLP cleanup
→ restore exceptions → collapse spaces. Exception lexicon (COVID-19, iPhone, YouTube…) lives
in `config.yaml`.

---

## 7. Evaluation — `transcribe/eval/`

- **`metrics.py`** — three signals on well-defined units:
  - **`cer_thai`** — char error rate over the Thai stream (primary Thai signal;
    tokenization-free because Thai has no word boundaries)
  - **`wer_latin`** — case-insensitive word error over Latin runs
  - **`boundary_error_rate`** — `1 − F1` of Thai↔Latin switch *timestamps* within `boundary_tol_ms`
  - `wer` — coarse sanity number, **never the gate**
- **`harness.py`** — `run_harness()` runs the golden set (`eval/goldenset/*.json` + audio)
  through the pipeline, aggregates reference-weighted numerators into corpus-level rates,
  records an `eval_run`, and **fails** if any signal regresses beyond `regression_tolerance`
  (2%) vs the last passing run.

CLI: `python -m transcribe.eval.harness --config config.yaml`.

---

## 8. Flywheel — `transcribe/flywheel/`

```
human edits ─[diff.py]──→ CorrectionPair[]  (only changed tokens, carries source_engine)
                            → correction table
                 [biasindex.py] scan counts, weight by staleness
                            (active engine ×1.0, swapped-out ×0.2),
                            promote terms crossing min_occurrences(3) → bias_term
                            → REGRESSION GATE: auto-run harness; roll back the
                              new terms if WER/BER worsens >2%
                            → bias_terms feed next run's EngineInput.bias_terms
```

This closes the loop: corrections → bias index → better next run, with the eval harness as
the safety gate on every bias update or engine swap.

---

## 9. Editor — `transcribe/editor/`

FastAPI backend (`server.py`) + single-page `static/index.html`. Correction-capture only —
no accounts, no dashboard.

| Endpoint | Purpose |
|---|---|
| `GET /jobs`, `GET /jobs/{id}` | list jobs / job + tokens |
| `GET /jobs/{id}/audio` | stream source audio |
| `POST /jobs/{id}/save` | diff submitted tokens vs original → write `correction` rows |
| `GET /jobs/{id}/export/{srt,vtt}` | download corrected subtitles |

Run: `uvicorn transcribe.editor.server:app --port 8000`.

---

## 10. Config — `transcribe/config.yaml`

Drives the whole system without code edits: `engine_a`/`engine_b` selection, ingestion
(denoise, VAD thresholds), `boundary_tol_ms`, the `normalization` policy + exception lexicon,
`regression_tolerance`, and `flywheel` (min_occurrences, stale_engine_weight).

**To swap an engine:** add adapter in `engines/` → `@register` it → update `config.yaml` →
re-run harness. No pipeline code changes — that's the whole point of the contract.

---

## Data-flow summary (one line)

`audio → ingest → Engine A ⟂ Engine B (sequential) → align_hyp → reconcile(select-only) →
normalize → align_force → DB → editor → diff → corrections → biasindex → (gated by eval) → next run`
