# CLAUDE.md

Guidance for AI agents working in this repository. Full file-by-file spec:
[SYSTEM_SPEC.md](SYSTEM_SPEC.md). Engine history and numbers: [docs/ENGINES.md](docs/ENGINES.md).

## Rules (read first)

### 1. How to write code

Applies to every write, review or refactor. For a trivial change, use judgment.

- **Think before coding.** State your assumptions. If the request has more than one
  reading, name them instead of picking one silently. If something is unclear, stop and
  ask. If a simpler approach exists, say so.
- **Simplicity first.** Write the minimum code that solves the problem: no features,
  options or abstractions nobody asked for, no error handling for impossible cases. If
  200 lines could be 50, rewrite it.
- **Surgical changes.** Touch only what the request needs. Match the existing style;
  don't reformat or refactor adjacent code. Mention unrelated problems instead of
  fixing them. Remove only what your own change made unused.
- **Goal-driven.** Turn the task into a check before starting ("fix the bug" → a test
  that fails, then passes; "refactor" → the same tests green before and after). For
  multi-step work, list each step with how it will be verified. Loop until the check
  passes.

The test: every changed line traces to the request.

### 2. Prove an Adobe API exists before using it

Applies to anything in the UXP panel (`uxp/cutdeck/`) or any Premiere / UXP call. Never
write an Adobe API from memory. All sources are pinned in the repo
(`reference/adobe/README.md`); nothing needs downloading. Check them in this order:

1. **`docs/PREMIERE_FACTS.md`**: what each API actually did when run live (catches,
   BROKEN, ABSENT, proven enum values). Add a row after every live run.
2. **`reference/adobe/api/premierepro.txt`** and **`reference/adobe/api/uxp.txt`**: one
   line per declared member (`grep "^SequenceEditor\." …`), generated from
   `@adobe/premierepro@26.5.1` (the installed Premiere) and `@adobe/cc-ext-uxp-types`.
   `NOT IN 26.2.1` marks members missing at the manifest's `minVersion` 26.2.0.
3. **`reference/adobe/docs/`** (Adobe's `uxp-premiere-pro` docs) and
   **`reference/adobe/samples/`** (Adobe's sample panels).
4. **Live probe** for what typings can't tell you: numeric enum values and runtime
   semantics (e.g. keyframe time units; `InterpolationMode` is LINEAR 0 / HOLD 4 /
   BEZIER 5).

Enforcement: `node tools/adobe/check-api.mjs` (also run by
`tests/cutdeck_adobe_api.test.cjs`) fails on any member name no Adobe source explains.
Its TypeScript tooling installs on the first test run, or by hand with
`npm ci --prefix tools/adobe`. Test fakes build on `tests/fakes/premiere.cjs`, which
enforces the proven rules and is itself checked against the typings.

In the change, name the source that confirmed the API. **If UXP doesn't have the
feature, don't fake or approximate it in the panel.** Build it in the CutDeck helper
(`python -m cutdeck.xml_bridge`, `ws://127.0.0.1:7891`, exposed to agents by the MCP
server `cutdeck/mcp_server.py`) and have the panel call it through `core/rpc.js`.

## Commands

```bash
# Install
pip install -r requirements.txt
pip install -e .

# Initialize DB
python -c "from transcribe.db.store import init_db; init_db()"

# Run the pipeline on a file
python -m transcribe.pipeline.run path/to/audio.wav --config transcribe/config.yaml

# Start the web editor
uvicorn transcribe.editor.server:app --host 127.0.0.1 --port 8000

# Run the eval harness
python -m transcribe.eval.harness --config transcribe/config.yaml

# Python tests (all, or one)
python -m pytest tests/test_smoke.py -v
python -m pytest tests/test_smoke.py::test_reconciler_no_generation -v

# CutDeck panel tests, including the Adobe API check
node --test tests/*.cjs
```

## Architecture

Pipeline (batch, offline; engines run one after another, never in parallel):
```
audio → ingest.py        denoise + VAD → chunks
      → Engine A         faster_whisper → EngineResult
          └─ cues/       split_cues: word pieces + CuePolicy → phrase cues
      → Engine B         passthrough (no second engine today) → EngineResult
      → align_hyp.py     hypothesis-to-hypothesis alignment → AlignSlots
      → reconcile.py     select-only → (RecognizedToken, source_engine) pairs
      → normalize.py     script-boundary spacing + Thai cleanup
      → align_force.py   final timestamps → token table + SRT/VTT
      → editor/          human corrections → diff.py → correction table → biasindex.py
```

Boundaries that must hold:

- **The Engine Contract (`contracts.py`) is the most important boundary.** Every ASR
  model is reached only through `EngineInput → EngineResult`. No code outside
  `engines/` imports a concrete model or model-specific logic.
- **No engine adapter imports another adapter.** Code two adapters share lives in its
  own module: audio preparation (VAD spans, zero-gap merge, long-window splitting) in
  `transcribe/audio/`, cue segmentation in `transcribe/cues/`. Both import without
  torch or CTranslate2. If a new adapter needs something another adapter has, lift it
  into one of these.
- **The reconciler selects, never generates.** Every output token's text must exist in
  its slot's candidate set (an assertion enforces it). Agreeing tokens never reach the
  LLM tiebreak, which is off anyway (see Current engines).
- **VRAM (RTX 3070, 8 GB):** load → run → `unload()` → `del` →
  `torch.cuda.empty_cache()`, one engine at a time. Never load two models at once.

## Key design rules

- Raw SQL only in `db/store.py`; everything else calls its typed functions.
  `db/schema.sql` is the single source of truth for the schema.
- Swapping an engine: add an adapter in `engines/`, register it in
  `engines/registry.py`, set `engine_a` / `engine_b` in `config.yaml`, re-run the
  harness. Per-engine settings live under `config["engines"][<name>]`, so a model or
  compute change is a YAML edit.
- `token.speaker_id` is nullable and reserved for v2 diarization. Don't remove it.
- Corrections carry `source_engine` so the flywheel can down-weight ones from
  swapped-out engines (`stale_engine_weight: 0.2`).
- The normalization exception lexicon (brands, mixed-script names, COVID-19…) is
  `normalization.exception_lexicon` in `config.yaml`.
- Jobs are resumable: `job.job_phase` (`ingested → engine_a_done → engine_b_done →
  reconciled → written`) plus the `engine_result` table let a re-run of a `failed` job
  (same media sha256) reuse cached per-engine results instead of redoing them.
- **Tokens are phrase cues, not words.** `EngineResult.timestamps_final` skips forced
  alignment. Per-word timings stay in `EngineResult.raw["words"]`, persisted in
  `engine_result`, and CutDeck uses them for filler excision.

## Current engines

Venv is **Python 3.11.9**.

| Engine | Status |
|---|---|
| `faster_whisper` (Engine A) | **Active.** `biodatlab/whisper-th-medium-combined` as CTranslate2 (`models/whisper-th-medium-ct2`, convert per `requirements.txt`), whole-file, batched. `typhoon-whisper-turbo` tried and reverted (worse `cer_thai`). |
| `passthrough` (Engine B) | **Active**: single-engine setup, so no agreement signal. |
| `whisper_thai` | Fallback: same checkpoint via HF `transformers`; slow. |
| `whisper_multi` | Candidate (`whisper-large-v3`), Thai-capable; not activated. |
| `qwen3_asr` | Built, **not activated**: transliterates English loanwords into Thai script (model quality, not a reconciler bug). |
| `typhoon_rt` | **Rejected**: worse `cer_thai` and `wer_latin`. Don't retry without new evidence. |
| `funasr` | **Retired**: SenseVoiceSmall has no Thai. Don't re-probe without a different model. |
| `mock` | Canned tokens, no GPU; used by all pipeline tests. |

**LLM reconciler tiebreak** (`transcribe/pipeline/llm_reconcile.py`, local Ollama
`qwen2.5:3b-instruct`): wired, bias-fixed and tested, but **off**
(`reconciler.llm_enabled: false`) because it made `cer_thai` worse. Don't revisit its
wiring or prompt framing. Still open: a larger model or a richer prompt.

## Eval and the regression gate

Gated signals: `cer_thai` (primary), `wer_latin`, `boundary_error_rate` (Thai↔Latin
switch timing) and `cue_boundary_error_rate` (cue starts, the Premiere-recut signal).
Plain `wer` is recorded but never gates.

- Any bias-index update or engine swap runs the harness. A change is rejected if a
  gated signal regresses beyond `regression_tolerance` (0.02) against the last passing
  `eval_run` row.
- A regression whose bootstrap CI still contains the baseline is `UNRESOLVED`, not a
  fail. Any overlapping cue is a hard fail.
- Baselines are partitioned by `metrics.METRICS_VERSION`: bump it on any change to a
  metric's definition.

Full rules: `transcribe/eval/README.md` and `STYLE_GUIDE.md`.

## Agent workflow

- **Issues:** GitHub Issues on `thanaponai01-collab/B-transcriber`, via the `gh` CLI.
  See `docs/agents/issue-tracker.md`.
- **Triage labels:** the five canonical roles, each label equal to its name. See
  `docs/agents/triage-labels.md`.
- **Domain docs:** single-context (`CONTEXT.md` + `docs/adr/` at the repo root, created
  when first needed; neither exists yet). See `docs/agents/domain.md`.
