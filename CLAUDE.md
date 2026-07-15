# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Full file-by-file system spec, structure, and workflow: see [SYSTEM_SPEC.md](SYSTEM_SPEC.md).

## Commands

```bash
# Install
pip install -r requirements.txt
pip install -e .

# Initialize DB
python -c "from transcribe.db.store import init_db; init_db()"

# Run pipeline on a file
python -m transcribe.pipeline.run path/to/audio.wav --config transcribe/config.yaml

# Start web editor
uvicorn transcribe.editor.server:app --host 127.0.0.1 --port 8000

# Run eval harness
python -m transcribe.eval.harness --config transcribe/config.yaml

# Run tests
python -m pytest tests/test_smoke.py -v

# Run a single test
python -m pytest tests/test_smoke.py::test_reconciler_no_generation -v
```

## Architecture

**Pipeline flow (batch, offline):**
```
audio → ingest.py (denoise + VAD → chunks)
      → Engine A (faster_whisper) → EngineResult   # sequential, not parallel
      → Engine B (passthrough, none active) → EngineResult   # VRAM freed between engines
      → align_hyp.py (hypothesis-to-hypothesis alignment → AlignSlots)
      → reconcile.py (select-only → (RecognizedToken, source_engine) pairs; llm_fn hook
        optionally tiebreaks disagreements via local Ollama, gated off by default)
      → normalize.py (script-boundary spacing + Thai cleanup)
      → align_force.py (final timestamps → token table + SRT/VTT)
      → editor/ (human corrections → diff.py → correction table → biasindex.py)
```

**The Engine Contract (`contracts.py`) is the most important boundary.** Every ASR model is accessed only through `EngineInput → EngineResult`. No code outside `engines/` may import a concrete model or reference model-specific logic. The pipeline consumes only the contract types.

**The reconciler selects, never generates.** It picks a candidate word from Engine A or B. An assertion enforces that every output token's text exists in the slot's candidate set — this prevents hallucination. Agreeing tokens skip the LLM entirely; only disagreements invoke it.

**VRAM discipline (RTX 3070, 8GB ceiling):** engines load → run → `unload()` → `del` → `torch.cuda.empty_cache()` sequentially. Never load two models simultaneously.

**Flywheel regression gate:** any bias-index update or engine swap auto-runs the eval harness. Changes are rejected if WER or boundary error rate regresses beyond `regression_tolerance` (default 2%) vs the last passing `eval_run` row.

## Key design rules

- `db/store.py` is the only place raw SQL is allowed — all other code calls typed store functions.
- `db/schema.sql` is the single source of truth for the schema.
- Engine choices live in `config.yaml` (`engine_a`, `engine_b`). To swap an engine: add an adapter in `engines/`, register it in `engines/registry.py`, update `config.yaml`, re-run the harness.
- `speaker_id` on the `token` table is nullable and reserved for v2 diarization — do not remove it.
- Corrections in the `correction` table carry `source_engine` so stale corrections from swapped-out models can be down-weighted by the flywheel (`stale_engine_weight: 0.2`).
- The normalization exception lexicon (brands, mixed-script proper nouns, COVID-19, etc.) lives in `config.yaml` under `normalization.exception_lexicon`.
- `job.job_phase` (`ingested → engine_a_done → engine_b_done → reconciled → written`) plus the `engine_result` table make jobs resumable: re-running a `failed` job for the same media sha256 reuses cached per-engine token lists instead of redoing finished work. `EngineResult.raw["words"]` (raw per-word timestamps, e.g. for CutDeck filler excision) is persisted there too.

## Current engines

The working venv is **Python 3.11.9** (not 3.13, despite older comments
elsewhere) — `funasr` and `editdistance` import fine in it. Engine-B
candidates below are eval-gated, not environment-blocked.

- **Engine A** (`faster_whisper`, active): `biodatlab/whisper-th-medium-combined`
  converted to CTranslate2 (`models/whisper-th-medium-ct2`). Whole-file engine
  (`prefers_whole_file=True`) run through `BatchedInferencePipeline` (VAD-batched
  parallel decode; auto-halves `batch_size` on CUDA OOM). Returns phrase cues with
  final timestamps. Convert the model per the comment in `requirements.txt`.
  `typhoon-whisper-turbo` was tried as a replacement (2026-07) and **reverted**
  — it regressed `cer_thai` to 0.1336 vs 0.1069 on the gold set despite its
  published benchmark; see IMPLEMENT_IMPROVEMENTS.md Phase 1.
- **Engine A alt** (`whisper_thai`): same checkpoint via HF `transformers` — kept
  as a fallback; per-chunk, word-level, much slower on 8 GB VRAM.
- **Engine B active config: `passthrough`** (null) — single-engine fallback,
  Engine A only, no agreement signal. Decorrelated candidates below are wired
  and eval-tested but deliberately left inactive because the current 4-clip
  gold set has zero Thai↔Latin code-switching (`switches=0`), so the harness
  can't yet prove any of them earns its 2× runtime. See
  IMPLEMENT_IMPROVEMENTS.md Phase 2.
- **`funasr`** (`FunAudioLLM/SenseVoiceSmall`): adapter registered, deps import
  fine on this venv (`hub="hf"` needed in `AutoModel(...)` — funasr defaults to
  ModelScope, which 404s for this model outside China). Activating it produced
  byte-identical harness metrics to `passthrough` until the `_script_fallback`
  circularity was fixed (see reconciler note below) — still gated off pending
  gold-set evidence.
- **`whisper_multi`**: `openai/whisper-large-v3` — multilingual generalist /
  code-switch slot, a real second hypothesis so cross-engine agreement would
  be a live confidence signal if activated.
- **`typhoon_rt`**: SCB10X Typhoon ASR Real-time (FastConformer-Transducer,
  ~115M) via NeMo — decorrelated Engine B candidate. Adapter built + mock-tested;
  NeMo not yet installed (should install clean on this Py3.11 venv, unlike the
  Py3.13 risk originally logged). Do not install before growing the gold set —
  it would hit the same "can't prove a lift" wall as `funasr`, not a
  `typhoon_rt`-specific blocker.
- **MockEngine** (`mock`): canned tokens, no GPU required — used for all pipeline tests

**LLM reconciler tiebreak (`transcribe/pipeline/llm_reconcile.py`):** on an
Engine A/B disagreement, `reconcile._pick()` can call an `llm_fn(ta, tb,
bias_terms) -> 0|1` hook instead of falling straight to `_script_fallback`.
`make_llm_fn()` wires this to a **local Ollama** instance (`qwen2.5:3b-instruct`
over stdlib `urllib`, no external API) — an unreachable/unpulled model falls
through to `_script_fallback` automatically. Gated off by default
(`reconciler.llm_enabled: false` in config.yaml); the wiring is verified
end-to-end but not yet proven to move `cer_thai`/BER for the same gold-set
reason as Engine B above. `_script_fallback` no longer trusts Engine A's own
script classification of its own output on every Thai disagreement — when both
engines report a confidence, confidence decides first and script is only the
final tiebreak.

**Token granularity (5.4):** tokens persisted to the DB are **phrase cues** (not
words). `EngineResult.timestamps_final` (formerly `word_level_timestamps`) signals
that a cue's timestamps are final, so the pipeline skips forced alignment + word
expansion. Word granularity is **re-derived on demand** — faster-whisper keeps its
raw per-word list in `EngineResult.raw["words"]` for CutDeck Phase 5 filler excision.

**Per-engine config (2.3):** construction knobs live under `config["engines"][<name>]`
(model_id, compute_type, beam_size, batch_size, cue thresholds, bias budget). `run.py`
forwards the matching block as kwargs — an engine/model/compute swap is a YAML edit.

## Eval golden set format

See `transcribe/eval/README.md` and `STYLE_GUIDE.md`. Three signals, each on a
well-defined unit: **`cer_thai`** (character error rate over the Thai stream —
tokenization-free, the primary Thai signal), **`wer_latin`** (case-insensitive
word error over Latin runs), and **`boundary_error_rate`** (temporal: `1 − F1` of
Thai↔Latin switch *timestamps* within `boundary_tol_ms`). Plain `wer` is a coarse
sanity number, never the gate. The harness normalizes gold and hypothesis with the
same `normalize()` before scoring, so policy changes can't desync them.
