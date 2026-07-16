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
  and eval-tested but not yet proven to earn their 2× runtime. **The old
  "switches=0 so nothing can be measured" blocker is gone (2026-07-16):**
  metrics v2 derives switch points character-by-character inside mixed cues,
  and the 5-clip gold set now scores `switches=104` with a live baseline of
  `BER 0.8592` (hyp emits only 38 switch points, 10 matched) — a huge, real
  code-switch gap that Engine-B / LLM-reconciler A/B probes can finally be
  judged against. See IMPLEMENT_IMPROVEMENTS.md Phase 2 for history.
- **`funasr`** (`FunAudioLLM/SenseVoiceSmall`): adapter registered, deps import
  fine on this venv. **RETIRED as a Thai candidate (2026-07-16): the model
  itself does not support Thai** — its README documents exactly five languages
  (zh/en/yue/ja/ko), and with `language="auto"` it misdetects Thai speech as
  Cantonese, decoding Chinese-script garbage throughout (confirmed via raw
  output inspection: an explicit `<|yue|>` tag, CJK codepoints). Every prior
  harness number for this engine — including the "byte-identical to
  passthrough" result below and the 2026-07-15/16 WER_latin/BER probes — was
  measuring that garbage, not a real Thai accuracy tradeoff. See
  `engines/funasr.py`'s docstring. Do not re-probe without a different model.
- **`whisper_multi`**: `openai/whisper-large-v3` — multilingual generalist /
  code-switch slot, genuinely Thai-capable (~100 languages incl. Thai) so this
  is the architecturally correct decorrelated candidate, unlike funasr. A real
  second hypothesis so cross-engine agreement would be a live confidence
  signal if activated. Probed 2026-07-16 — see TODO_LEDGER for the result.
- **`typhoon_rt`**: SCB10X Typhoon ASR Real-time (FastConformer-Transducer,
  ~115M) via NeMo — decorrelated Engine B candidate. Adapter built; NeMo
  installed and verified clean on this 3.11.9 venv (`nemo_toolkit==2.7.3`) —
  the Py3.13 wheel risk originally logged doesn't apply here. **TRIED and
  REJECTED (2026-07-16):** regresses CER_thai and WER_latin vs baseline with
  only a marginal BER edge — worse than every other candidate on accuracy.
  Don't re-try without new evidence.
- **MockEngine** (`mock`): canned tokens, no GPU required — used for all pipeline tests

**LLM reconciler tiebreak (`transcribe/pipeline/llm_reconcile.py`):** on an
Engine A/B disagreement, `reconcile._pick()` can call an `llm_fn(ta, tb,
bias_terms) -> 0|1` hook instead of falling straight to `_script_fallback`.
`make_llm_fn()` wires this to a **local Ollama** instance (`qwen2.5:3b-instruct`
over stdlib `urllib`, no external API) — an unreachable/unpulled model falls
through to `_script_fallback` automatically. Gated off by default
(`reconciler.llm_enabled: false` in config.yaml). `_script_fallback` no longer
trusts Engine A's own script classification of its own output on every Thai
disagreement — when both engines report a confidence, confidence decides
first and script is only the final tiebreak.

**PROBED and FIXED 2026-07-16 (two rounds) — bias eliminated, but the model
still isn't good enough to activate.** Round 1: with `engine_b:
whisper_multi` (the first candidate producing real disagreements — funasr
never does, see above), `llm_fn` was instrumented directly and picked Engine
A on **11 of 11** real disagreements — including cases where Engine B's text
was visibly longer and more complete. Not credible as judgment; positional
bias. Two causes: (1) `_PROMPT_TEMPLATE` said "disagree on **one word**"
though tokens have been phrase cues since 5.4 — the model was shown two full
sentences while told to expect one word; (2) `whisper_multi` correctly
reports `confidence=None` (never faked), so `_script_fallback`'s
confidence-tiebreak never fires against it either, degrading it to
same-script routing that also always favored A. Harness output was
byte-identical with/without `--llm-enabled`.

**Fixed:** `_PROMPT_TEMPLATE` now describes segment/phrase-level candidates;
`make_llm_fn` randomizes per call which of (ta, tb) lands in prompt slot 0 vs
1 and remaps the answer back (`tests/test_phase3_llm_reconcile.py`, +2,
suite 189 green). Round 2 (re-instrumented, same clip): the lock-in is gone
— 7/11 picked A, 4/11 picked B, no longer deterministic. **But the harness
result got WORSE, not better: `CER_thai 0.3505`** (vs round 1's 0.2323, vs
0.1451 baseline). This is the fix correctly exposing a **model-quality**
problem: Engine A (faster_whisper) is empirically the strongest engine on
this gold set, and round 1's degenerate "always A" was *accidentally* a good
heuristic — once `qwen2.5:3b-instruct` can genuinely pick Engine B and does
so ~36% of the time, its judgment isn't reliable enough to beat that
heuristic. `llm_enabled` stays `false`. Do not revisit the wiring, prompt
framing, or bias fix — they're done and tested. What's still open: try a
larger local model (`qwen2.5:7b-instruct`?) or a richer prompt (few-shot
examples, surrounding-token context) before concluding the LLM-tiebreak
*approach* doesn't work — this result only rules out this specific small
model + minimal-context prompt. See TODO_LEDGER.md for full before/after
numbers.

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

**Metrics v2 (2026-07-16, `metrics.METRICS_VERSION`):** switch points are derived
character-by-character *inside* every token — tokens are phrase cues, so real
code-switches live inside `mixed` cues, which the v1 token-script rule could never
see (BER was structurally 0.0). Intra-cue switch timestamps are interpolated
across the cue span; corpus BER is a micro-F1 so hallucinated switches on
monolingual clips are penalized. `eval_run.metrics_version` partitions regression
baselines: scores from different metric versions are never compared, so a metric
change starts a fresh baseline instead of wedging the gate. Bump the version on
any metric-definition change that makes old scores incomparable.
