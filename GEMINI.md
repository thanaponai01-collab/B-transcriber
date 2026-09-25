# GEMINI.md

This file provides guidance to Gemini / Antigravity when working with code in this repository.

> Full file-by-file system spec, structure, and workflow: see [SYSTEM_SPEC.md](SYSTEM_SPEC.md).

## Rules (read first)

1. **Invoke `/karpathy-guidelines` before writing, reviewing, or refactoring code.**
   Surgical changes, no overcomplication, stated assumptions, verifiable success criteria.

2. **Prove an Adobe API exists before writing code that uses it.** Before writing
   anything for the UXP panel (`uxp/cutdeck/`) or any Premiere / UXP call, look the
   API up and confirm it is really there — never write it from memory. Everything is
   in the repo, pinned (`reference/adobe/README.md`); nothing needs downloading:
   - **`docs/PREMIERE_FACTS.md` first**: what each API actually did when run live
     (catches, BROKEN, ABSENT, proven enum values). Add a row after every live run.
   - **`reference/adobe/api/premierepro.txt`** / **`api/uxp.txt`**: every declared
     member, one line (`grep "^SequenceEditor\." …`), generated from Adobe's typings
     (`@adobe/premierepro@26.5.1`, the installed Premiere; `@adobe/cc-ext-uxp-types`).
     `NOT IN 26.2.1` marks APIs missing at the manifest's `minVersion` 26.2.0.
   - `reference/adobe/docs/` (Adobe's `uxp-premiere-pro` docs: Premiere classes and
     the UXP platform) and `reference/adobe/samples/` (Adobe's own sample panels).
   - Typings don't give numeric enum values or runtime semantics (e.g. keyframe time
     frames; `InterpolationMode` is really LINEAR 0 / HOLD 4 / BEZIER 5): live-probe.
   - `node tools/adobe/check-api.mjs` (and `tests/cutdeck_adobe_api.test.cjs`) fails
     on any member name no Adobe source explains. Its tools (TypeScript) install themselves
     on the first test run; by hand: `npm ci --prefix tools/adobe`.
   - Test fakes: build on `tests/fakes/premiere.cjs`, which enforces the proven rules
     and is checked against the typings.

   Say in the change which source confirmed the API. **If the feature does not exist
   in UXP, don't fake or approximate it in the panel — build it in the CutDeck helper**
   (`python -m cutdeck.xml_bridge`, `ws://127.0.0.1:7891`; exposed to agents via the
   MCP server `cutdeck/mcp_server.py`), and have the panel call it over `core/rpc.js`.

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

# CutDeck panel tests (incl. the Adobe API check; installs its tools on first run)
node --test tests/*.cjs
```

## Architecture

**Pipeline flow (batch, offline):**
```
audio → ingest.py (denoise + VAD → chunks)
      → Engine A (faster_whisper) → EngineResult   # sequential, not parallel
        └─ cues/ (split_cues: word pieces + CuePolicy → phrase cues)
      → Engine B (passthrough, none active) → EngineResult   # VRAM freed between engines
      → align_hyp.py (hypothesis-to-hypothesis alignment → AlignSlots)
      → reconcile.py (select-only → (RecognizedToken, source_engine) pairs; llm_fn hook
        optionally tiebreaks disagreements via local Ollama, gated off by default)
      → normalize.py (script-boundary spacing + Thai cleanup)
      → align_force.py (final timestamps → token table + SRT/VTT)
      → editor/ (human corrections → diff.py → correction table → biasindex.py)
```

**The Engine Contract (`contracts.py`) is the most important boundary.** Every ASR model is accessed only through `EngineInput → EngineResult`. No code outside `engines/` may import a concrete model or reference model-specific logic. The pipeline consumes only the contract types.

**No engine adapter may import another engine adapter** — that is the same boundary read in the other direction. Concerns two adapters share live in their own modules, never in whichever adapter grew them first: shared audio preparation (VAD span detection, the zero-gap merge, over-long window splitting) is `transcribe/audio/`, and subtitle cue segmentation is `transcribe/cues/`. Both are importable without torch or CTranslate2. If a new adapter needs something a rival adapter already has, lift it into one of these rather than reaching for the private.

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

Venv is **Python 3.11.9**. Full history, numbers and reasoning: [docs/ENGINES.md](docs/ENGINES.md).

| Engine | Status |
|---|---|
| `faster_whisper` (Engine A) | **Active.** `biodatlab/whisper-th-medium-combined` as CTranslate2 (`models/whisper-th-medium-ct2`, convert per `requirements.txt`), whole-file, batched. `typhoon-whisper-turbo` tried and reverted (worse `cer_thai`). |
| `whisper_thai` | Fallback: same checkpoint via HF `transformers`; slow. |
| `passthrough` (Engine B) | **Active**: single-engine, no agreement signal. |
| `whisper_multi` | Candidate (`whisper-large-v3`), Thai-capable; not activated. |
| `qwen3_asr` | Built, **not activated**: transliterates English loanwords into Thai script (model quality, not a reconciler bug). |
| `typhoon_rt` | **Rejected**: worse `cer_thai` and `wer_latin`. Don't retry without new evidence. |
| `funasr` | **Retired**: SenseVoiceSmall has no Thai. Don't re-probe without a different model. |
| `mock` | Canned tokens, no GPU; used by all pipeline tests. |

- **LLM reconciler tiebreak** (`transcribe/pipeline/llm_reconcile.py`, local Ollama
  `qwen2.5:3b-instruct`): wired, bias-fixed and tested, but **off**
  (`reconciler.llm_enabled: false`): it made `cer_thai` worse. Don't revisit the wiring or
  prompt framing; still open is a larger model or richer prompt (docs/ENGINES.md).
- **Tokens are phrase cues**, not words. `EngineResult.timestamps_final` skips forced
  alignment; per-word timings stay in `EngineResult.raw["words"]` (CutDeck filler excision).
- **Per-engine config** lives under `config["engines"][<name>]`; an engine/model/compute
  swap is a YAML edit.

## Eval

Four gated signals: `cer_thai` (primary), `wer_latin`, `boundary_error_rate` (Thai↔Latin
switch timing) and `cue_boundary_error_rate` (cue starts, the Premiere-recut signal). Plain
`wer` is never the gate. Baselines are partitioned by `metrics.METRICS_VERSION`: bump it on
any metric-definition change. A regression whose bootstrap CI still contains the baseline is
`UNRESOLVED`, not a fail. Full rules: `transcribe/eval/README.md` and `STYLE_GUIDE.md`.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`thanaponai01-collab/B-transcriber`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
