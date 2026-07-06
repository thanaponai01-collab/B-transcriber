# HANDOFF — B-transcriber: Robustness Fixes + Speed Architecture Upgrade

**For:** Claude Code, working in the B-transcriber repo (https://github.com/thanaponai01-collab/B-transcriber)
**Hardware:** RTX 3070, 8 GB VRAM. Python 3.13. Windows host.
**Prime directive:** Accuracy first. Speed gains must never be bought with an eval regression.
**Discipline:** Every phase ends with `tests/test_smoke.py` green plus the new acceptance tests listed per task. Read `CLAUDE.md`, `SYSTEM_SPEC.md`, and `TODO_LEDGER.md` before touching anything. Update `TODO_LEDGER.md` as tasks complete.

---

## Context: what this handoff is

A full-codebase audit (2026-07-06) found seven correctness bugs, three "dead config" breaks, and one architectural bottleneck. Separately, comparison against current state-of-the-art pipelines (faster-whisper BatchedInferencePipeline, WhisperX VAD-batching, Typhoon ASR Real-time FastConformer-Transducer, arXiv 2601.13044) identified a speed architecture the system should adopt: **VAD-batched parallel Whisper decoding + a cheap decorrelated transducer as Engine B**.

Current measured speed: ~3× realtime (5-min clip in ~1m40) because `faster_whisper.py` decodes the whole file sequentially, one 30 s window at a time. Target after this handoff: **10–20× realtime** on the same hardware, with the dual-engine reconciler live at <10% overhead instead of 2×.

Work in the order below. Phases 1–2 are prerequisites for everything else.

---

## PHASE 1 — Stop silent corruption (do first, small diffs)

### 1.1 Defang the loop-collapse regex — `transcribe/pipeline/run.py`
`_collapse_loops` applies `(.+?)\1{2,}` to **every token unconditionally**. This corrupts real text:
- `2000` → `20`, phone numbers mangled (any digit repeated 3+)
- `555` (Thai laughter, extremely common) → `5`
- legitimate emphatic repetition flattened

faster-whisper already kills loops at the source (`condition_on_previous_text=False`, `vad_filter`, compression/log-prob thresholds), so this regex is now net-negative.

**Change:**
- Never apply to tokens whose text is digits-only (or digits + punctuation).
- Raise the repeat threshold from 3 to 5 for units ≤ 2 chars.
- Keep threshold 3 only for units ≥ 3 chars (real Whisper loops are long units).
- Log every collapse at INFO with before/after text so corruption is auditable.

**Acceptance:** unit tests proving `2000`, `555`, `0812345555`, `www` survive intact; a genuine loop like `ฮือฮือฮือฮือฮือ` still collapses; smoke tests green.

### 1.2 Empty gold set must not poison the eval baseline — `transcribe/eval/harness.py`
`eval/goldenset/` does not exist in the repo. When `_load_goldenset()` returns zero samples, the harness currently records a **passing eval_run with all metrics 0.0**. Because the gate is `new > last × 1.02`, one accidental harness run against an empty set makes every future real run fail the regression gate forever.

**Change:**
- If sample count is 0: print the warning, **return without writing an eval_run**, and exit non-zero from the CLI.
- Create `transcribe/eval/goldenset/` with a `.gitkeep` and a README stating the JSON schema expected (`{"tokens": [{"text","script","start_ms"}...]}`) and the audio-file pairing convention.

**Acceptance:** test that `run_harness` with an empty goldenset writes zero `eval_run` rows.

### 1.3 Assertions → real exceptions — `transcribe/pipeline/reconcile.py`
The select-only invariant is enforced by `assert`, which vanishes under `python -O`. Replace with an explicit `raise` of a dedicated `ReconcilerViolation(RuntimeError)`. Same for any other safety-critical `assert` found in pipeline modules (grep for `assert` under `transcribe/pipeline/`).

---

## PHASE 2 — Reconnect dead config (restores the config-driven contract)

Three subsystems ignore their own config keys. Fix all with one pattern: thread the relevant config subsection down; keep current values as defaults so nothing breaks if the key is absent.

### 2.1 VAD — `transcribe/pipeline/ingest.py`
`config.yaml` declares `vad_threshold`, `vad_min_speech_ms`, `vad_min_silence_ms`; ingest hardcodes `0.5 / 250 / 300`. The Thai-tuned values were lost in the drift.

**Change:** `ingest(path, denoise, vad_cfg)` reads the three values from config. Then set config to the Thai-tuned values and document why in a comment:
```yaml
vad_threshold: 0.35        # Thai sentence-final particles (ครับ/ค่ะ/นะ) are soft; generic 0.5 clips them
vad_min_speech_ms: 250
vad_min_silence_ms: 500
```
Also migrate Silero loading from `torch.hub.load` to the pip package `silero-vad` (removes the first-run network dependency and the hub supply-chain surface). Add to requirements.

**Acceptance:** a test that patches config values and asserts they reach `get_speech_ts` (mock the model).

### 2.2 Flywheel constants — `transcribe/flywheel/biasindex.py`, `inject.py`
`min_occurrences`, `stale_engine_weight`, `bias_prompt_budget` exist in config but modules use private constants. Thread them through `update_bias_index(...)` and `build_prompt_ids(...)` signatures (config dict or explicit params). Delete the module constants or keep only as defaults.

### 2.3 Per-engine config — `transcribe/engines/registry.py` + `config.yaml`
`get_engine(name, device=...)` passes nothing else, so the faster_whisper model path, compute_type, beam_size, and cue thresholds are hardcoded — swapping to the Typhoon Turbo CT2 model or `int8_float16` requires a code edit.

**Change:** add an `engines:` section to config keyed by registry name; `run.py` passes `config.get("engines", {}).get(name, {})` as kwargs to `get_engine`. Example shape:
```yaml
engines:
  faster_whisper:
    model_id: models/typhoon-whisper-turbo-ct2   # or whisper-th-medium-ct2
    compute_type: int8_float16                   # 8GB headroom for batching (Phase 3)
    beam_size: 5
    cue_gap_ms: 700
    cue_max_ms: 6000
  typhoon_rt: {}
```
**Acceptance:** engine swap and compute_type change achievable by editing YAML only; smoke test with mock engine accepting arbitrary kwargs.

---

## PHASE 3 — Speed core: batched decoding (the big one)

### 3.1 Adopt `BatchedInferencePipeline` — `transcribe/engines/faster_whisper.py`
Current adapter calls `self._model.transcribe(...)` → sequential 30 s windows → GPU idles → ~3× realtime. faster-whisper ships `BatchedInferencePipeline(model=...)` as a **drop-in replacement**: it VAD-segments the audio, merges voiced regions into ≤30 s chunks respecting speech boundaries (WhisperX-style cut-and-merge), and decodes them as parallel batches. Published results: ~3× over sequential faster-whisper, 12.5× over openai/whisper, with no WER degradation; VAD batching also suppresses hallucination at the source.

**Change:**
- Wrap the loaded `WhisperModel` in `BatchedInferencePipeline` at `load()`.
- Add `batch_size` to the engine's config section (default 8). With `compute_type: int8_float16` on 8 GB, start at 8; the existing OOM-halving philosophy from `_batch.py` should be replicated here: catch CUDA OOM → halve batch_size → retry (do NOT reuse `_batch.py` directly, it's HF-pipeline-specific).
- Keep `word_timestamps=True`, `condition_on_previous_text=False`, and the existing threshold knobs — verify each kwarg is supported by the batched API and drop/relocate any that are not (check the installed faster-whisper version's signature at implementation time; do not assume).
- `_group_words_into_cues` stays unchanged — it consumes the same word list.

**Acceptance:**
- `tests/test_faster_whisper_cues.py` still green (cue invariants: no mid-word cuts, gap/span breaking).
- New benchmark script `tools/bench_transcribe.py` that times a given file and reports realtime factor; record sequential vs batched numbers in TODO_LEDGER. Target ≥3× improvement on the 5-min reference clip.
- Transcript equivalence check: batched vs sequential output on the same clip must differ by <1% CER against each other (guards against silent quality loss from batching).

### 3.2 Kill wasted work in ingest — `transcribe/pipeline/ingest.py`, `run.py`
Two problems, one cause: run.py still runs the full chunk-engine ingest path even when both engines are whole-file/passthrough.

1. **Denoise is 100% discarded compute.** Ingest denoises audio (temp-WAV-per-2s-window DeepFilterNet — ~1,800 file writes per hour of footage), then VAD runs on the denoised signal — but the whole-file engine loads the **raw** file. Result: enormous cost, zero benefit, plus a correctness hazard (silence spans derived from audio the engine never heard → the 0.8 silence-overlap filter can drop valid words).
2. **Audio is decoded up to 3 times** (ingest, `full_audio` load, forced-align reload).

**Change:**
- Decode once in run.py; pass the array into ingest and into engines (`EngineInput.audio` already exists for this).
- When every active engine is whole-file/passthrough: skip denoise entirely and skip chunk materialization; run Silero on the **same raw array** the engine will receive, producing only the span timeline (needed by the silence filter and CutDeck).
- When a chunk engine is active and `denoise: true`: denoise once, then both VAD and the engine consume the **same** denoised array (fixes the mismatch).
- While in this file: implement the GAP-4 other half — emit ~0.75 s overlap between adjacent VAD chunks so `stitch.py` stops being a no-op. This is dormant now but silently becomes a boundary-word-loss bug the day a chunk engine activates. Config key `chunk_overlap_ms: 750`.

**Acceptance:** single-decode verified (count `load_audio` calls via test spy = 1 per job); pipeline-run wall time on the 5-min clip drops accordingly; stitch unit tests exercise a real overlap produced by ingest, not synthetic fixtures.

---

## PHASE 4 — Engine B rebirth: Typhoon ASR Real-time (decorrelated, near-free)

### Why this specific model
- **FastConformer-Transducer, 115M params** (arXiv 2601.13044, SCB10X/Typhoon, Jan 2026). ~45× lower compute than Whisper Large-v3 at comparable CER to the offline Thai SOTA (Pathumma-Whisper Large-v3). At 45× cheaper, Engine B costs ~5–10% extra runtime, not 2×.
- **Architecturally decorrelated from Whisper**: transducer (frame-synchronous, monotonic) vs seq2seq — different failure modes, which is the entire point of the reconciler. Trained on a different corpus (Typhoon's curated ~11k-hour Thai pipeline) → training-data decorrelation too.
- **Structurally cannot hallucinate repetition loops** (monotonic alignment). Cross-engine agreement finally becomes a real confidence signal: Whisper says X over silence, transducer says nothing → drop. Both agree → high confidence.

### 4.1 New adapter — `transcribe/engines/typhoon_rt.py`
- Register as `typhoon_rt`. Runs via NVIDIA NeMo (`nemo_toolkit[asr]`) — **verify the Py3.13 wheel situation first** (this killed FunASR before). If NeMo won't install on Py3.13, check for the model's ONNX export or a standalone inference path before giving up; document the outcome in TODO_LEDGER either way.
- Whole-file or chunked, whichever the model API favors — it's a streaming model, so chunked over the VAD chunks is natural and it's cheap enough not to matter.
- Transducers emit token-level timestamps and (typically) no usable confidence — set `confidence=None` per the contract (never fake it).
- Its output normalization differs from Whisper's; **do not** compensate inside the adapter. `normalize.py` remains the single authority and runs after reconciliation. The adapter emits verbatim model output mapped to `RecognizedToken`s.
- VRAM: 115M params ≈ trivial next to Whisper. Sequential load discipline (`load → run → unload → empty_cache`) still applies unchanged.

### 4.2 Config + eval gate
- `engine_b: typhoon_rt` goes in **only after** the gold set exists and the harness proves it lowers `cer_thai` (or BER) versus passthrough. That is the standing rule; this handoff builds the adapter and leaves `engine_b: passthrough` as default until the eval says otherwise.
- Add a harness convenience: `--engine-b typhoon_rt` CLI override so the A/B comparison is one command.

**Acceptance:** adapter passes contract tests with mock audio; a dual-engine smoke run (mock or real) completes with reconciler producing `source_engine ∈ {a,b,both}`; runtime overhead of Engine B measured and recorded (<15% of total job time expected).

### 4.3 Two-pass "draft fast, refine accurate" mode (optional, after 4.1)
Borrowed from the streaming-first-pass + rescoring pattern the big pipelines use. Add a `--draft` pipeline mode: run **only** typhoon_rt (seconds per file), write tokens flagged `pipeline_version: draft`, so CutDeck can propose a rough cut immediately; the full dual-engine pass replaces the tokens later. Schema needs no change (job status can carry it, or a `job.kind` column via `_migrate`). Only build this if 4.1 lands cleanly — it's a workflow luxury, not a correctness item.

---

## PHASE 5 — Flywheel correctness (must land before the gold set goes live)

### 5.1 Budgeted bias injection in faster_whisper — `transcribe/engines/faster_whisper.py`
The adapter builds `initial_prompt = " ".join(inp.bias_terms)` — raw, unranked, unbudgeted. CT2 truncates ~224 tokens silently; highest-value terms fall off. Use `flywheel.inject.build_prompt` with the budget from config (2.2) and a CT2-appropriate token counter (the CT2 model exposes its tokenizer via `self._model.hf_tokenizer` or similar — verify at implementation; fall back to `_approx_tokens`). Weight/recency come from `bias_term` rows, not insertion order — extend `store.get_bias_term_strings` to a variant returning `(term, weight)`.

### 5.2 Fix the self-comparing regression gate — `transcribe/eval/harness.py`, `flywheel/biasindex.py`
`run_harness` writes the new eval_run (possibly passed=True) **before** `_run_regression_gate` reads `get_last_passing_eval` — so the gate can fetch the run it's supposed to be judging and compare it against itself. Also `biasindex._passed_gate` checks coarse `wer` + BER only (`cer_thai` — the primary signal — is ungated) with a hardcoded 1.02.

**Change:** make the harness the single gate authority. It captures the previous passing baseline *before* writing the new row, gates on `cer_thai`, `wer_latin`, and `boundary_error_rate` using `regression_tolerance` from config, and returns pass/fail + both metric sets. `biasindex._run_regression_gate` consumes that return value; delete `_passed_gate`.

**Acceptance:** test where a synthetic regressed run is correctly blocked and bias terms rolled back; test that a passing run does not compare against itself (two-run sequence).

### 5.3 Sub-cue correction diffing — `transcribe/flywheel/diff.py`
Tokens are now ~7 s phrase cues. A one-word edit produces a whole-phrase `CorrectionPair`, and after 3 recurrences `biasindex` promotes an entire **sentence** as a bias "term" — which then devours the 200-token prompt budget and biases toward sentence repetition.

**Change:** when `raw_text != corrected_text` and either side exceeds a length threshold (~15 chars), run a character-level diff (difflib opcodes) to extract the minimal changed span, then expand to word boundaries — PyThaiNLP newmm for Thai spans, whitespace for Latin. The extracted word/phrase (not the full cue) becomes `corrected_text` on the CorrectionPair; keep the full cue pair in the `correction` row for audit (add a `corrected_span` column via `_migrate`, or store span text in `reason`-adjacent column — your call, keep schema.sql the source of truth).
Add a guard in `biasindex`: never promote a term longer than ~30 chars or ~6 words.

**Acceptance:** test: cue "วันนี้เราจะพูดถึง ChatGBT กันครับ" corrected to "...ChatGPT..." yields a CorrectionPair whose corrected term is `ChatGPT`, not the sentence.

### 5.4 Rename the lying flag — `transcribe/contracts.py` and all consumers
`EngineResult.word_level_timestamps=True` now means "phrase cues with final timestamps," not words. Rename to `timestamps_final` (meaning: skip forced alignment + word expansion). Grep all consumers (`run.py`, tests). Decide-and-document (in CLAUDE.md) the standing position: **tokens persisted to DB are phrase cues; word granularity is derived on demand** — CutDeck filler excision (which needs word-level cuts inside a cue) will re-derive word timestamps from the stored faster-whisper word list. To enable that, persist the raw per-word list into `EngineResult.raw` and store it as a JSON sidecar on the job (new `job_artifact` table or a file next to the DB — smallest thing that works; note it in TODO_LEDGER for CutDeck Phase 5 to consume).

---

## PHASE 6 — Eval + hygiene

### 6.1 rapidfuzz for edit distance — `transcribe/eval/metrics.py`
Pure-Python Levenshtein over Thai char streams is O(n·m); a 15-min gold set ≈ 10⁸ Python ops per signal per harness run, and the harness runs on every bias update. Swap `_edit_distance` internals to `rapidfuzz.distance.Levenshtein.distance` (C, ~100× faster); keep the function signature and the pure-Python version as a fallback when rapidfuzz is absent. Add to requirements.

### 6.2 Eval runs must not pollute the production DB — `transcribe/eval/harness.py`
Harness currently writes real job/token/media rows into `transcriber.db`. Route pipeline runs during eval to a scratch DB (`eval_scratch.db`, recreated per harness run) while `eval_run` rows still go to the main DB. Simplest cut: harness passes a different `db_path` into `pipeline_fn`.

### 6.3 `align_hyp` linearization — `transcribe/pipeline/align_hyp.py`
O(A×B) full scan per A-token. With Engine B live on hour-long files this is millions of pure-Python comparisons. Sort both streams by `start_ms` (they already are) and maintain a sliding window over B bounded by `_MATCH_PROX_MS`; score only inside the window. Behavior-identical, near-linear.
**Acceptance:** existing align tests green; add a property test that windowed and brute-force implementations agree on random token sets.

### 6.4 Portability nit — `transcribe_file.py`
`subprocess.CREATE_NEW_CONSOLE` is Windows-only; guard with `sys.platform` so the entry point doesn't crash elsewhere. Low priority.

---

## PHASE 7 — Gold set enablement (unblocks everything eval-gated)

Build **GAP-6**: `tools/make_gold.py` — the draft → hand-correct → freeze round-trip:
1. `draft` subcommand: run the pipeline on a file, export the tokens as a harness-schema JSON next to the audio in `eval/goldenset/` with a `.draft.json` suffix.
2. Human corrects the JSON (or corrects in the editor and the tool pulls corrected tokens from the DB — support both; the editor path is better since corrections also feed the flywheel).
3. `freeze` subcommand: validate schema (every token has text/script/start_ms; scripts match `detect_script`; timestamps monotonic), strip the `.draft` suffix, and refuse to overwrite an existing frozen file without `--force`.

The gold-authoring **policy** questions (loanword script choice, number verbalization) are STYLE_GUIDE.md territory — the tool validates mechanics only.

**Note the Typhoon benchmark finding (arXiv 2601.13044) as motivation in the tool's docstring:** their strict normalization protocol was worth as much as model scaling on Thai CER, and inflated baselines often stem from formatting mismatches, not recognition errors. The gold set + shared `normalize.py` is this system's version of that discipline.

**Acceptance:** end-to-end: draft a 30 s clip → hand-edit one token → freeze → `run_harness` consumes it and records a real baseline. After this exists, the human step is: transcribe-and-correct 10–15 minutes of representative own footage (include code-switch-heavy and noisy samples — the decorrelation and bias questions can't be measured without them).

---

## Sequencing summary

| Order | Phase | Why this position |
|---|---|---|
| 1 | Phase 1 (corruption + baseline poisoning) | Live bugs corrupting every run / one command from wedging the gate |
| 2 | Phase 2 (config plumbing) | Prerequisite for 3 and 4; re-fixes Thai VAD drift permanently |
| 3 | Phase 3 (batched decode + ingest cleanup) | Biggest speed lever; also fixes the audio-source mismatch |
| 4 | Phase 5 (flywheel correctness) | Must be right **before** corrections start flowing |
| 5 | Phase 7 (gold set tooling) | Unblocks every eval-gated decision |
| 6 | Phase 4 (Typhoon RT Engine B) | Adapter can be built anytime; activation is eval-gated on the gold set |
| 7 | Phase 6 (eval perf + hygiene) | Valuable, not blocking; 6.1 is 30 minutes, do it opportunistically |

## Invariants that must survive every change
- Reconciler **selects, never generates** (now exception-enforced, not assert).
- `normalize.py` is the single normalization authority — engines emit verbatim; ref and hyp normalized identically in eval.
- One model resident in VRAM at a time; load → run → unload → empty_cache.
- `confidence=None` when the engine gives none — never faked.
- No decimal fps literal anywhere; rational `(fps_num, fps_den)` only.
- Config drives engine/threshold selection; a swap must never require a code edit.
- Nothing accuracy-affecting ships without a harness run once the gold set exists.
