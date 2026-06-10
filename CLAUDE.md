# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
      → Engine A (whisper_thai) → EngineResult   # sequential, not parallel
      → Engine B (funasr)       → EngineResult   # VRAM freed between engines
      → align_hyp.py (hypothesis-to-hypothesis alignment → AlignSlots)
      → reconcile.py (select-only → (RecognizedToken, source_engine) pairs)
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

## Current engines

- **Engine A** (`whisper_thai`): `biodatlab/whisper-th-medium-combined` — Thai specialist
- **Engine B** (`whisper_multi`): `openai/whisper-large-v3` — multilingual generalist / code-switch slot. Runs on Python 3.13 (transformers). A real second hypothesis, so cross-engine agreement is a live confidence signal.
- **`funasr`** (`FunAudioLLM/SenseVoiceSmall`): registered but unavailable on Python 3.13 (editdistance has no wheel). Alternative generalist.
- **`passthrough`** (null): single-engine fallback — Engine A only, no agreement signal.
- **MockEngine** (`mock`): canned tokens, no GPU required — used for all pipeline tests

## Eval golden set format

See `transcribe/eval/README.md` and `STYLE_GUIDE.md`. Three signals, each on a
well-defined unit: **`cer_thai`** (character error rate over the Thai stream —
tokenization-free, the primary Thai signal), **`wer_latin`** (case-insensitive
word error over Latin runs), and **`boundary_error_rate`** (temporal: `1 − F1` of
Thai↔Latin switch *timestamps* within `boundary_tol_ms`). Plain `wer` is a coarse
sanity number, never the gate. The harness normalizes gold and hypothesis with the
same `normalize()` before scoring, so policy changes can't desync them.
