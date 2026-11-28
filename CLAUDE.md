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

### 2. Prove the route; never write an Adobe API from memory

UXP is one route into Premiere, not the limit. Before saying an action can't be done, handing it
to the user, or building a workaround, look it up in `docs/PREMIERE_CONTROL_MAP.md`: every route
and the `premiere_*` command for each task. A command may use only routes with a LIVE row in
`docs/PREMIERE_FACTS.md` "Route proof per command"; `tests/cutdeck_route_proof.test.cjs` fails
on any other. When several routes reach an action, prefer UXP, then the menu, then keys, then
the Premiere UI (PREMIERE_FACTS records menu items and key presses that returned yet did
nothing), and read the result back. Keys and the Premiere UI take the user's mouse and keyboard:
approved standing (user, 2026-11-26), no need to ask each time. Never use the AI Assistant
(`premiere_assistant_ask`): it spends the user's Adobe credits, and they have not allowed that.
Don't fake or approximate a feature; if a CutDeck guard blocks a task, name the guard, not
"Premiere can't". A new route or command is built in the helper (`cutdeck/driver_commands.py`, the
table; family code in `cutdeck/commands/`), proved live (verify-cutdeck) and recorded before
agents use it. Premiere's built-in MCP server
and `hSLScripting` are off limits: first-party only, never force them.

For panel code (`uxp/cutdeck/`), never write an Adobe API from memory. Check, in order:
`docs/PREMIERE_FACTS.md` (what each API did live; add a row after every live run);
`reference/adobe/api/premierepro.txt` and `api/uxp.txt` (one line per member; `NOT IN 26.2.1`
marks members missing at `minVersion` 26.2.0); `reference/adobe/docs/` and
`reference/adobe/samples/`; then a live probe for enum values and runtime semantics. Name the
source in the change. `node tools/adobe/check-api.mjs` (in `tests/cutdeck_adobe_api.test.cjs`)
fails on a member no Adobe source explains; its TypeScript installs on the first test run (`npm
ci --prefix tools/adobe`). Test fakes build on `tests/fakes/premiere.cjs`, which enforces the
proven rules and is itself checked against the typings.

## Commands

```bash
# Install (on 3.13 deepfilternet has no wheel and fails; the default pipeline runs without it)
pip install -r requirements.txt
pip install -e .

# Initialize DB
python -c "from transcribe.db.store import init_db; init_db()"

# Run the pipeline on a file
python -m transcribe.pipeline.run path/to/audio.wav --config transcribe/config.yaml

# Start the web editor
uvicorn transcribe.editor.server:app --host 127.0.0.1 --port 8000

# Run the eval harness (piped Windows stdout is cp1252; Thai file names crash it without utf-8)
PYTHONIOENCODING=utf-8 python -m transcribe.eval.harness --config transcribe/config.yaml

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
      → word_align.py    Thai CTC re-times word + cue starts, and ends before a pause (Engine A unloaded first)
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

There is no `.venv`. Every run uses PATH **Python 3.13.4** (torch 2.6.0+cu124, CUDA on).

| Engine | Status |
|---|---|
| `faster_whisper` (Engine A) | **Active.** `biodatlab/whisper-th-medium-combined` as CTranslate2 (`models/whisper-th-medium-ct2`, convert per `requirements.txt`), whole-file, batched. `typhoon-whisper-turbo` tried and reverted (worse `cer_thai`). |
| `passthrough` (Engine B) | **Active**: single-engine setup, so no agreement signal. |
| `whisper_thai` | Fallback: same checkpoint via HF `transformers`; slow. |
| `whisper_multi` | Candidate (`whisper-large-v3`), Thai-capable; not activated. |
| `qwen3_asr` | Built, **not activated**: transliterates English loanwords into Thai script (model quality, not a reconciler bug). |
| `typhoon_rt` | **Rejected**: worse `cer_thai` and `wer_latin`. Code removed (git history keeps it). Don't retry without new evidence. |
| `funasr` | **Retired**: SenseVoiceSmall has no Thai. Code removed (git history keeps it). Don't re-probe without a different model. |
| `mock` | Canned tokens, no GPU; used by all pipeline tests. |

**LLM reconciler tiebreak** (`transcribe/pipeline/llm_reconcile.py`, local Ollama
`qwen2.5:3b-instruct`): wired, bias-fixed and tested, but **off**
(`reconciler.llm_enabled: false`) because it made `cer_thai` worse. Don't revisit its
wiring or prompt framing. Still open: a larger model or a richer prompt.

## Eval and the regression gate

Gated signals (`metrics.CI_METRICS`): `cer_thai` (primary), `wer_latin`,
`boundary_error_rate` (Thai↔Latin switch timing), `cue_boundary_error_rate` (cue starts,
the Premiere-recut signal) and `speech_coverage_miss` (reference cues that no output cue
overlaps). A robustness run also gates `cer_thai_spread`.
Plain `wer` is recorded but never gates.

- Any bias-index update or engine swap runs the harness. A change is rejected if a
  gated signal regresses beyond `regression_tolerance` (0.02) against the last passing
  `eval_run` row.
- A regression whose bootstrap CI still contains the baseline is `UNRESOLVED`, not a
  fail. Any overlapping cue is a hard fail.
- Baselines are partitioned by `metrics.METRICS_VERSION`: bump it on any change to a
  metric's definition.

Full rules: `transcribe/eval/README.md` and `STYLE_GUIDE.md`.

## CutDeck (Premiere)

- **Helper** `python -m cutdeck.helper` on `ws://127.0.0.1:7891` runs ASR jobs and
  the routes outside UXP (menu, keys, Premiere UI, AI Assistant). Agents reach Premiere through the MCP server
  `cutdeck/mcp_server.py`; every route in is listed in `docs/PREMIERE_CONTROL_MAP.md`.
- **Panel** `uxp/cutdeck/` (UXP) calls the helper through `core/rpc.js`. Rule 2 applies to every route.
- **Offline project reads**: `cutdeck/prproj_reader.py` reads a saved `.prproj`.
- **HKS pipeline**: the `cutdeck/hks_*.py` modules build โหนกระแส episodes. The plan and
  its steps are in `projects/hks/build-plan.md`.
- **SubtitleDesk** (`subtitle_desk/`): quote editor on the shared helper; see its README.

## Agent workflow

- **Issues:** GitHub Issues on `thanaponai01-collab/B-transcriber`, via the `gh` CLI.
  See `docs/agents/issue-tracker.md`.
- **Triage labels:** the five canonical roles, each label equal to its name. See
  `docs/agents/triage-labels.md`.
- **Editing projects** (1RaceClub, HKS / โหนกระแส): one folder each under [projects/](projects/README.md)
  with principles, rules, memory and logs. Read [projects/PRINCIPLES.md](projects/PRINCIPLES.md) first,
  then the project's README. New project facts go in its `memory/`, not in `docs/`.

## Memory

Before trying an approach, read `.owner/memory/INDEX.md`: what was tried here, what failed, and when to retry. Record new attempts there.

## Project checks
- `.claude/skills/verify-cutdeck/`: drive CutDeck in live Premiere and keep evidence (`scripts/cdv.py doctor | launch | start | scratch | call | shot | cleanup`). Use it after changing `cutdeck/` or `uxp/cutdeck/`; tests use a fake Premiere.
- `VERIFY.md`: each feature and the command that proves it. Run every check before saying done;
  `verify-loop` builds and maintains it.
- `FEATURES.md`: what the system has and how a user reaches each feature. Read it before driving or
  changing the app; `feature-map` keeps it true.
- Something broken and the cause unknown: `debug-protocol`.
