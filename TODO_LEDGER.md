# TODO_LEDGER

Deferred work from the IMPLEMENT_CUTDECK.md build. Each entry has a trigger that
makes it due. Owner: build-discipline.

## Metrics v2 — intra-cue switch points (BER un-blinded) — executed 2026-07-16

Suite: **184 passed** (was 176; +8 in `tests/test_metrics_v2.py`).

**The finding:** `metrics._switch_points` derived Thai↔Latin switches from the
token-level `script` field only. Tokens are phrase cues, so every real
code-switch sits *inside* a `mixed` cue — invisible by construction. The whole
gold set therefore scored `switches=0` regardless of content, BER was pinned
at a structural 0.0, and every "grow the gold set to unblock Engine B / the
LLM reconciler" plan was chasing a gate that could never fire. (The
code-switch clips added 2026-07-15 were already in the set — they just
couldn't register.) Second, smaller defect: corpus BER was a ref-weighted
mean, so hypothesis switches hallucinated on zero-switch samples carried
weight 0 and were never penalized.

**The fix (metrics v2, `metrics.METRICS_VERSION = 2`):**
1. Switch points walk every *character* of every token; an intra-cue switch's
   timestamp is linearly interpolated across the cue's `[start_ms, end_ms]`
   by char offset (same approximation on both sides). Digits/punct are
   script-neutral. Pure-script token streams behave exactly as v1.
2. Corpus BER = `1 − micro-F1` over summed matched/ref/hyp switch counts
   (`metrics.boundary_f1_error`; per-sample counts now on `EvalMetrics.
   hyp_switches/matched_switches`).
3. **Baseline partitioning:** `eval_run.metrics_version` column (additive
   `_migrate`, pre-existing rows default v1). `get_last_passing_eval` and
   `create_eval_run` default to the current `METRICS_VERSION` — a metric
   change starts a fresh baseline instead of tripping the gate against
   incomparable numbers (the old v1 baseline had BER 0.0 with zero weight; any
   real v2 score would have "regressed" forever). Bump the version on any
   future metric-definition change.

**Proven on the real gold set (2026-07-16):** migrated `transcriber.db`
(16 rows stamped v1), ran the production harness: `CER_thai 0.1451`
(unchanged from the 2026-07-15 baseline — Thai scoring untouched),
`WER_latin 1.0452`, **`switches=104 (hyp 38, matched 10)` → `BER 0.8592`**,
passed=True as the fresh v2 baseline. The system's real code-switch gap is
now visible and gated: Engine A finds barely a third of the reference
switches.

**First decidable Engine-B probe (same session):** `harness --engine-b
funasr` (experiment row, baseline untouched): **BER improved 0.7882 vs
0.8592** (hyp switches 66 vs 38, matched 18 vs 10 — the decorrelated engine
genuinely finds switches Engine A misses) but **WER_latin regressed 1.2258
vs 1.0452** → gate blocked, correctly. CER_thai 0.1451 unchanged. Verdict
recorded at the time: a decorrelated Engine B is worth having for BER;
funasr specifically is too inaccurate on Latin words.

**⚠ CORRECTION (same session, after probing the LLM reconciler): the above
verdict is WRONG — retracted, not just superseded.** Probing `--engine-b
funasr --llm-enabled` produced metrics **byte-identical** to the plain
funasr run above (down to hyp_switches/matched_switches), which meant the
LLM tiebreak fired zero times. Instrumenting `align_hyp.align()` directly on
a gold clip confirmed why: **0 of 52 slots had both an A and a B candidate**
— faster_whisper and funasr's outputs never overlap enough to be treated as
a disagreement at all. Inspecting funasr's raw output explained that:
`result["text"]` carries an explicit `<|yue|>` (Cantonese) tag, and every
"word" token is a CJK Unified Ideograph codepoint (e.g. `困` '困'), not
Thai script. Checked SenseVoiceSmall's own model card: it documents exactly
five supported languages — `zh, en, yue, ja, ko` — **Thai is not one of
them**. With `language="auto"` (`engines/funasr.py`), its language-ID
misdetects Thai speech as Cantonese and decodes Chinese-script garbage
throughout. **The "BER improved 0.7882" and "WER_latin regressed 1.2258"
numbers above were measuring that garbage — not a genuine Thai-code-switch
accuracy tradeoff.** They are not evidence that a decorrelated Engine B is
or isn't worth having; they are evidence that SenseVoiceSmall cannot
transcribe Thai. This also retroactively explains the *older*,
pre-2026-07-16 "byte-identical to passthrough" funasr result noted elsewhere
in this ledger/CLAUDE.md — consistent with zero real A/B overlap having
existed the whole time, for the same underlying reason. **funasr/
SenseVoiceSmall is retired as a Thai-code-switch candidate** (see
`engines/funasr.py`'s corrected docstring) — not gated pending more gold
data, structurally incapable regardless of gold-set size. Don't re-probe it
without a different underlying model. Tests unaffected (no test asserted the
old, wrong conclusion — this was a documentation/interpretation error, not a
code defect with a regression test to write).

**Second probe: typhoon_rt (same session, 2026-07-16).** Installed
`nemo_toolkit[asr]==2.7.3` cleanly on this 3.11.9 venv (the Py3.13 wheel risk
in the code comments doesn't apply here). First attempt crashed with
`CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH` on typhoon_rt's very first conv
forward — traced to a real, separate bug (see "PATH-scoping bugfix" entry
below) and fixed. Re-run after the fix: **all 5 clips transcribed cleanly**,
but the result is a clear regression across every signal: `CER_thai 0.1601`
(vs 0.1451 baseline), `WER_latin 1.1290` (vs 1.0452), `BER 0.8537` (vs 0.8592
— a marginal 0.6pp gain, far short of funasr's 0.71). switches hyp=60,
matched=12. **Verdict: typhoon_rt does not currently earn Engine-B activation
— worse than funasr on every axis except a negligible BER edge.** Plausible
causes not yet investigated: this specific NeMo release/checkpoint pairing,
audio preprocessing mismatch (16kHz mono float32 assumed but not verified
against what `typhoon-asr-realtime.nemo`'s manifest expects), or the model
being tuned for streaming/short-utterance input rather than the ~30s+ whole-
file spans this adapter feeds it. **Due when:** don't re-try without new
evidence (mirrors the typhoon-whisper-turbo Engine-A precedent) — either
diagnose why NeMo's own reference eval numbers don't reproduce here, or move
on to a Qwen3-ASR adapter / `--llm-enabled` probe instead.

**PATH-scoping bugfix (same session, real bug, not NeMo/typhoon_rt-specific):**
`engines/faster_whisper.py`'s `_register_cuda_dll_dirs()` prepended nvidia
pip wheels' bin dirs (incl. a CUDA-12 `cudnn64_9.dll`) onto process-wide
`PATH` so CTranslate2 could find `cublas64_12.dll` — but never reverted it.
Any NeMo-based engine (torch 2.13+cu130, a different CUDA generation) loaded
afterward in the *same process* inherited that prepended cuDNN and crashed on
its first conv forward with `CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH`.
Confirmed via a minimal repro: calling only `_register_cuda_dll_dirs()` (zero
CTranslate2 model loaded) was sufficient to break typhoon_rt; typhoon_rt
worked fine standalone. **Fix:** the function now returns the pre-mutation
PATH; `FasterWhisperEngine.load()` captures it, `unload()` restores it — the
mutation is now load()-scoped instead of process-lifetime. This was silent
and untested before because no test or eval run had ever loaded a CTranslate2
engine and a NeMo engine in the same process — Engine B has been
`passthrough` since typhoon_rt's adapter was built. Would have bitten anyone
activating typhoon_rt in production. Tests: `tests/test_faster_whisper_
path_scoping.py` (3 new; suite 187 green).

**Third probe: whisper_multi + the LLM reconciler (same session, 2026-07-16)
— the first genuine test bed, and a real diagnosed finding.** Unlike funasr,
`whisper_multi` (Whisper large-v3) genuinely supports Thai, so this was the
first candidate where the LLM tiebreak could actually be exercised on real
disagreements.

`harness --engine-b whisper_multi --llm-enabled` (Ollama serving
`qwen2.5:3b-instruct` locally): **CER_thai regressed sharply to 0.2323**
(vs 0.1451 baseline — a ~60% relative increase), `WER_latin 1.0903` (mild
regression vs 1.0452), `BER 0.8616` (not better than 0.8592). An isolation
re-run (`--engine-b whisper_multi`, no `--llm-enabled`) produced **byte-
identical** numbers — the LLM tiebreak made zero measurable difference here
too, same symptom as the retired funasr probe but a *different* root cause
(whisper_multi is not broken like funasr — align_hyp genuinely produces
overlapping A+B slots against it, 12 of 26 on a sample clip, several with
real text differences).

Instrumenting `reconcile._pick()`'s `llm_fn` directly on one clip (11 real
disagreements) explains why: **the LLM picked Engine A (index 0) on all 11
of 11 calls** — including cases where Engine B's text was visibly longer and
more complete than Engine A's truncated cue. A 100% rate across diverse,
non-trivial disagreements is not credible as genuine semantic judgment; it
reads as a positional/first-option bias in `qwen2.5:3b-instruct` under the
current prompt. Two compounding, real defects found along the way:
1. **Prompt staleness bug** (`llm_reconcile.py`'s `_PROMPT_TEMPLATE`): it
   still says *"Two Thai speech-recognition engines disagree on **one
   word**"* — but tokens have been phrase cues since 5.4 (CLAUDE.md), so the
   model is actually shown two full sentences while being told to expect one
   word. Never updated when token granularity changed.
2. **`_script_fallback` degrades to pure script-routing here for an
   unrelated reason:** `engines/whisper_multi.py` hardcodes
   `confidence=None` on every token (deliberate — the contract's "never fake
   a confidence" rule, correctly followed), which means
   `_script_fallback`'s confidence-tiebreak branch never fires against it.
   Since most disagreements here are both-Thai-script, the script-routing
   fallback then also trivially picks A every time. So on every reconciled
   ("both A+B") slot, *neither* path — LLM or fallback — ever selects
   Engine B; the only way whisper_multi's content enters the final
   transcript at all is via the 12 unmatched "only-B" solo slots that pass
   straight through un-reconciled, and that's what drives the CER_thai
   regression (whisper_multi's own segmentation/accuracy on those unmatched
   spans is worse, diluting rather than correcting Engine A's output).

**Verdict: whisper_multi + LLM reconciler rejected on the current gold set —
but unlike funasr/typhoon_rt, this is NOT evidence the architecture can't
work.** It's evidence the *current* prompt and local model provide no
discriminative signal, compounded by a null-confidence engine collapsing the
fallback to a routing rule that happens to always favor A on same-script
disagreements. **Due next (in order of cheapest-to-test):**
(a) fix the prompt's stale "one word" framing to describe phrase-cue
comparison: (b) test with per-call randomization of which candidate is
presented as "A" vs "B" to separate genuine judgment from positional bias —
if index 0 still wins ~100% after randomization, the bias is confirmed and a
larger/better local model is needed; (c) reconsider whether `_script_fallback`
should have a non-confidence tiebreak (e.g. length/completeness heuristic)
for exactly this null-confidence-engine case, since the contract correctly
forbids faking confidence but the fallback currently has no fallback *within*
the fallback when confidence is absent on one side.

**Known limitation (accepted):** intra-cue interpolation assumes uniform
character rate; on long cues the placement error can approach
`boundary_tol_ms` (300 ms). Both sides share the bias, so matches survive in
practice. **Due when:** if real A/B probes show BER noise swamping signal,
widen `boundary_tol_ms` or re-derive switch timestamps from
`engine_result.raw_words_json` word timings instead of interpolation.

**Environment finding (same session):** DeepFilterNet denoise is silently
dead on this venv — `df.enhance` imports `torchaudio.backend`, which
torchaudio 2.x removed, so `_apply_rolling_denoise` warns and returns the
raw audio whenever a chunk engine activates (`denoise: true` is a no-op).
Harmless today (the production engine is whole-file, denoise already skipped
by design), and possibly net-positive to leave dead (INFRA-6 in the 2026-06
audit questioned whether denoise helps at all). **Due when:** a chunk engine
is activated for production — either pin/patch DeepFilterNet for torchaudio
2.x, or measure a denoise-off baseline and delete the path.

## Four confirmed-issue fixes — executed 2026-07-15 (after the diff-srt pass)

Suite: **176 passed** (was 167; +9 new tests across three new files).

1. **Eval regression-baseline partitioning (integrity).** An A/B probe
   (`harness --engine-b X` / `--llm-enabled`) wrote a normal `eval_run`; if it
   passed, `get_last_passing_eval` would hand it to the next production run as
   the baseline. Fixed with an `eval_run.is_experiment` column (schema.sql +
   idempotent `_migrate` add): `run_harness(..., experiment=True)` marks the
   row, `get_last_passing_eval` excludes it, and the harness CLI implies the
   flag for `--engine-b`/`--llm-enabled` (plus an explicit `--experiment`).
   An experiment is still *judged against* the production baseline — it just
   can never *become* it. **Design note:** the alternative fix — filtering the
   baseline by the current run's `engine_pair`/`bias_hash` — was rejected
   deliberately: the flywheel gate exists to compare an engine swap or bias
   update AGAINST the previous config's baseline, so partitioning lineage by
   those columns would hand every swap/update an empty baseline and a free
   pass. Partition on intent (experiment vs production), not on config
   identity. Tests: `tests/test_eval_baseline_partitioning.py` (store-level
   exclusion + the baseline → passing-experiment → production round-trip).
   **Migration note:** any pre-existing `transcriber.db` (the live/local DB —
   gitignored, not shipped in the repo) predates the `is_experiment` column
   and must run `init_db()` once (idempotent `_migrate`, additive-only, no
   data touched) before the harness will run against it — it fails fast with
   `sqlite3.OperationalError: no such column: is_experiment` otherwise.
   **Confirmed on the real gold set (2026-07-15):** ran
   `python -m transcribe.eval.harness --config transcribe/config.yaml --db
   transcriber.db` after migrating — passed, cer_thai 0.1451 vs prior baseline
   0.1486 (improved), wer_latin/BER unchanged. No regression from this pass's
   four fixes. `switches=0` still holds (gold set has no code-switch samples
   yet), so BER/Engine-B activation remain unproven either way — unchanged
   from the pre-existing known gap.

2. **Stitch seam-window dedup.** `stitch()` compared each candidate only
   against `kept[-1]`, so an A-B-A' pattern (duplicate copies of a seam word
   separated by an intervening token from the other chunk) kept the duplicate.
   It now scans all recently-kept tokens whose span ends within
   `seam_window_ms` of the candidate's start (interiority/confidence
   tie-breaks unchanged; output re-sorted since an interior replacement can
   nudge ordering). Call sites thread the real overlap: `run.py` passes config
   `chunk_overlap_ms`, faster_whisper's long-span path passes its 4 s window
   overlap. Tests: `tests/test_stitch_seam_window.py`.

3. **Cue target width in config.** `_CUE_TARGET_CHARS` (42) was hardcoded
   while its siblings `cue_gap_ms`/`cue_max_ms` were config-driven — and
   `transcribe()` wasn't even passing it, silently always using the default.
   Now `engines.faster_whisper.cue_target_chars` in config.yaml → constructor
   kwarg → `_group_words_into_cues`. Named `cue_target_chars` (not bare
   `target_chars`) to match the `cue_*` kwarg family. Tests:
   `tests/test_cue_target_chars_config.py` (constructor override, default =
   module constant, capture test proving the value reaches the grouping,
   functional shorter-cues test).

4. **Engine-reuse state-bleed audit — CLEAN; don't re-investigate blind.**
   No `language_hint`/`bias_terms` bleed exists across chunks or jobs within a
   process. Checked (2026-07-15): `registry.get_engine` returns a fresh
   `cls(**kwargs)` per call, and nothing in `transcribe/` caches an engine
   instance (grep `get_engine|lru_cache|_ENGINE|engine_cache` — only run.py
   calls it); `run.py` engine instances live for exactly one `run_file` and
   are `del`'d, `bias_terms`/`bias_weights` are re-read from the DB per job,
   and language hints are per-call literals ("th" for A, None for B); every
   adapter builds its per-call kwargs *inside* `transcribe()`/
   `transcribe_batch()` (whisper_thai/whisper_multi: `generate_kwargs` +
   `prompt_ids` fresh each call; faster_whisper: `initial_prompt` + `common`
   dict fresh, and the OOM-halved `bs` is a local never written back to
   `self._batch_size`; funasr: `cache={}` fresh per call — the classic FunASR
   bleed vector — and hotword rebuilt per call; typhoon_rt holds only the
   model); `_batch.py` retries hand the HF pipeline fresh dict wrappers
   (fixed 2026-06-18) and never mutate `generate_kwargs`; `inject.build_prompt`
   uses `sorted()` (copies) and fresh `BiasTerm` objects, so the *shared*
   `bias_terms` list that rides in every chunk's `EngineInput` is never
   mutated. Two non-bleed observations recorded for posterity: (a)
   `language_hint` is *honored* only by faster_whisper — whisper_thai forces
   `"th"`, whisper_multi/funasr force auto-detect (each documented/deliberate);
   (b) whisper_* `transcribe_batch` builds its bias prompt from `inputs[0]`
   under a documented same-job assumption. **Due when:** any caller ever
   batches `EngineInput`s across jobs or bias sets in one `transcribe_batch`
   call — the `inputs[0]` prompt assumption then breaks silently.

## diff-srt flywheel path — executed 2026-07-15

The web editor's correction capture (diff.py) only matches original vs.
corrected tokens by `idx`, which breaks the moment a final NLE pass (Premiere
Pro: re-time, re-cut, merge, split cues) is fed back in — there was previously
no path for that at all, and `update_bias_index` had zero production call
sites (only tests called it, confirmed via grep).

Built: `transcribe/srt_io.py` (parse_srt relocated out of tools/make_gold.py,
which now re-exports it); `transcribe/flywheel/align_srt.py` (connected-
components-over-time-overlap grouping — handles merge/split/deletion/insertion
without special-casing each; a timebase-divergence guard measured as *matched
coverage* rather than raw min/max span, so a normal edit that adds a trailing
title/outro card doesn't false-positive as a wrong-file mismatch); promoted
`diff.py`'s `_extract_changed_span` to public `extract_changed_span` for reuse
(second concrete use). `scripts/learn_from_srt.py` CLI: prints a match/mismatch
summary before writing anything (mirrors make_gold's draft→freeze ceremony),
requires `--yes` or an interactive confirm, then writes corrections and (unless
`--no-promote`) calls `update_bias_index(..., run_regression_gate=True)` —
closing the promotion gap above. 19 new tests (`test_align_srt.py`,
`test_learn_from_srt.py`); full suite 167 green.

**Known simplification, not a bug:** a merged/split group's correction row is
owned by the group's *lowest* original `token_idx` (the `correction` table is
keyed one row per original token; there is no schema concept of a many-token
group). Reopening that job in the web editor will only show that one idx as
"corrected" — the other merged-away idxs still display raw text. **Due when:**
the web editor needs accurate per-idx corrected-state display for a job that
went through an SRT re-import — would need either a nullable
`group_token_idxs` JSON column (additive migration, low regret) or a separate
join table.

**Also deferred:** `update_bias_index`'s real GPU regression-gate path (run_harness
with pipeline_fn=None) is exercised only via monkeypatch in
`test_learn_from_srt.py` — the gate's own pass/rollback correctness is already
proven in `test_phase5_flywheel.py`, so this wasn't re-proven end-to-end on real
audio. **Due when:** the gold set grows enough to make a real `learn_from_srt`
promotion worth measuring (same gate as Engine B/LLM-reconciler, see the
2026-07-15 entry below).

## IMPLEMENT_IMPROVEMENTS.md pass — executed 2026-07-14

Fixed with tests (`tests/test_improvements_202607.py`, suite 116 green):
harness scratch-DB bias-index mirroring (eval was running prompt-less);
correction upsert per (job, token) + revert deletion (re-saves were stacking
duplicate rows and inflating flywheel counts); editor job view merges saved
corrections; empty corrected text never promoted as a bias term;
`get_last_passing_eval` filters kind + id tie-break; mai-yamok spaced-repeat
collapse; `sent_tokenize` import inside its best-effort try; exception lexicon
expanded; dead `_config()` removed from editor server.

**Environment truth (2026-07-14):** the working venv is **Python 3.11.9** —
`funasr` and `editdistance` import fine. The "no Py3.13 wheel" blocker recorded
below for FunASR/NeMo does not apply to this venv; Engine-B activation is
eval-gated only. CLAUDE.md/config comments still say 3.13 — update them when
Engine B lands.

**Update (2026-07-15): all six phases executed.** Gold set live (4 clips);
typhoon-whisper-turbo Engine A tried and reverted (lost the gate); decorrelated
Engine B (`funasr`) wired and eval-tested but left `passthrough` (correctly
gated — see below); LLM reconciler (`llm_reconcile.py`, local Ollama) wired and
gated off (`llm_enabled: false`); resumability/raw-word persistence
(`job_phase` + `engine_result` table) done; editor reason-tag/confidence/
corrected-state UI done. `pytest tests/` → 148 passed. Full detail and
resolution notes: IMPLEMENT_IMPROVEMENTS.md §2 (each phase now has a
**Resolution** block). **Remaining due-when:** Engine B / LLM-reconciler
activation is still gated on a gold set with real code-switch-heavy or
noisy material — the current 4 clips have `switches=0`, so the gate can't yet
prove either feature earns its runtime. Grow the gold set to make that call.

## HANDOFF_SPEED_AND_ROBUSTNESS — executed 2026-07-06

Phases 1–7 landed; full suite 97 green (`pytest tests/`). New acceptance tests:
`test_phase1_robustness`, `test_phase2_config`, `test_phase3_ingest`,
`test_phase4_typhoon`, `test_phase5_flywheel`, `test_phase6_evalperf`,
`test_phase7_makegold`.

- **P1 corruption:** loop-collapse defanged (digits/short-unit safe, logged);
  empty gold set no longer writes an eval_run (returns None, CLI exits non-zero);
  reconciler assert → `ReconcilerViolation` raise.
- **P2 config:** VAD threaded (was already) + Silero migrated to the `silero-vad`
  pip package (torch.hub fallback); flywheel constants threaded through
  `update_bias_index`/`build_prompt_ids`; per-engine `config["engines"][name]`
  kwargs (YAML-only engine/compute swap).
- **P3 speed:** faster-whisper now runs `BatchedInferencePipeline` with OOM-halving
  (`tools/bench_transcribe.py` added); ingest decodes **once**, skips denoise for
  whole-file engines, and emits `chunk_overlap_ms` overlap so stitch works.
- **P5 flywheel:** budgeted+weighted bias prompt with a CT2 token counter; harness
  is the single gate authority (returns `HarnessResult`, no self-comparison,
  `_passed_gate` deleted); sub-cue span diffing (`corrected_span` column) +
  ≤30char/≤6word promotion guard; `word_level_timestamps` → `timestamps_final`,
  raw per-word list kept in `EngineResult.raw["words"]`.
- **P6 hygiene:** rapidfuzz Levenshtein (pure-Python fallback); scratch-DB eval
  isolation (already in); `align_hyp` sliding-window linearization (property-tested
  vs brute force); `CREATE_NEW_CONSOLE` guarded by `sys.platform`.
- **P4 Engine B:** `typhoon_rt` NeMo adapter built + contract-tested (mock), `--engine-b`
  harness override added. **NOT activated** — see below.
- **P7 gold set:** `tools/make_gold.py` draft→freeze round-trip, end-to-end tested.

**Remaining (hardware / human, not code):**
- **P3 real-footage bench:** run `tools/bench_transcribe.py <5-min clip> --compare-sequential`
  on real Thai speech — record RTF (target ≥3× sequential) + confirm <1% batched-vs-
  sequential CER. Validated only on synthetic audio here (wiring proven on the 3070).
- **P4 NeMo Py3.13:** `nemo_toolkit[asr]` install on Python 3.13 is **unverified**
  (heavy C-dep tree; this is what killed FunASR). Do NOT install into the working env
  until activating; if it won't install, check the model's ONNX export / standalone
  inference path. Activation is eval-gated regardless (engine_b stays `passthrough`).
- **P4.3 two-pass `--draft` mode:** deliberately **not built** (YAGNI — a workflow
  luxury the handoff marks optional; build when a real fast-draft need appears).
- **P7 human step:** transcribe-and-correct 10–15 min of representative own footage
  (code-switch-heavy + noisy) so the eval-gated Engine-B / bias decisions can be measured.

## Transcriber gaps (Part A)

- **Engine default switched to `faster_whisper` (CTranslate2), single-engine
  (2026-06-18).** `config.yaml` now runs `engine_a: faster_whisper` /
  `engine_b: passthrough`. Whole-file transcription (capability flag
  `Engine.prefers_whole_file`) on the RTX 3070: 5-min clip in ~1m30 (was 10m+ and
  the HF transformers dual-engine path never finished). Also fixed this session:
  HF `array`→`raw` input-key break (transformers 5.9.0), OOM-retry reusing
  mutated dicts (`_batch.py`), repetition-loop survival, and the align_hyp
  far-match producing file-spanning timestamps.
- **Cue granularity — DONE (2026-06-18).** faster-whisper now runs with
  `word_timestamps=True` and `_group_words_into_cues` re-joins the sub-word Thai
  pieces into phrase cues, breaking only at word boundaries on a >700 ms gap or a
  >6 s span. Result on the 5-min clip: ~37 cues, median ~7 s, no mid-word cuts;
  runtime ~1m40 (word timestamps roughly double the engine pass, still sub-
  realtime). Tested in `tests/test_faster_whisper_cues.py`. Residual: occasional
  long cue when Whisper drifts a single word's end timestamp — cosmetic.
- **Engine B re-introduction is eval-gated.** Cross-engine agreement only earns
  its 2× cost if the harness proves it lowers `cer_thai`. **Due when:** a real
  bias-sensitive gold set exists to measure it.

- **GAP-4 chunk overlap (other half). ✅ DONE (2026-07-06).** `ingest.ingest`
  now emits `chunk_overlap_ms` (default 750) overlap between adjacent VAD chunks
  via `_materialize_chunks`, so stitch.py dedupes seam words instead of being a
  no-op. Only active when a chunk engine runs (whole-file engines skip chunking
  entirely). Tested in `test_phase3_ingest`.
- **GAP-5 prompt injection — GPU verification. ✅ DONE (2026-06-11).** Proven on
  the RTX 3070 with transformers 5.9.0: `get_prompt_ids` exists and the pipeline
  accepts `prompt_ids`; transcribe ran clean with and without bias terms.
  Residual: whether bias terms measurably *improve* accuracy is an eval question,
  not a wiring one — settle it once the gold set has real bias-sensitive samples.
- **GAP-2 VFR conform.** `is_vfr` is probed and persisted; `ingest.conform_vfr`
  config flag exists but no CFR-proxy transcode is implemented, and XML export
  does not yet refuse to run against a VFR original. **Due when:** `xml_export.py`
  (CutDeck Phase 2) is built.
- **GAP-6 gold-set promote CLI. ✅ DONE (2026-07-06).** `tools/make_gold.py`:
  `draft` (from a corrected editor job via `--job-id`, or `--run` the pipeline) →
  hand-correct the `.draft.json` → `freeze` (validates schema/script/monotonic
  time, refuses to overwrite a frozen file without `--force`). End-to-end tested
  (`test_phase7_makegold`). **Human step remains:** author 10–15 min of real gold.
- **GAP-7 editor reason UI.** Column + API + diff plumbing done; the one-tap tag
  UI in `static/index.html` is not. **Due when:** editor front-end is next touched.
- **GAP-8 job resumability** — not started. **Due when:** a multi-hour file is
  run for real and a crash costs a full re-run.
- **A.2 loudness pre-pass + editor confidence highlighting** — not started.

## CutDeck (Part B)

- **Phase 0 — DONE.** timebase + VAD persistence + schema migration in place.
- **Phase 1 — DONE (2026-06-12).** `cutdeck/` package built:
  `contracts.py` (Segment/Label/CutSpan/CutPlan/CutConfig + Timebase re-export),
  `segment.py` (gap/VAD utterance segmentation), `rules.py` (deterministic
  silence cuts shrunk by padding + config-gated filler removal + min-clip merge),
  `plan.py` (contiguous/exhaustive CutPlan, JSON round-trip, store glue, and a
  `python -m cutdeck.plan --job-id N` CLI). `cut_plan` table + store CRUD added.
  18 acceptance tests green in `tests/test_cutdeck_phase1.py`; Phase 0 + smoke
  unaffected. Determinism, padding-no-overlap, and min-clip invariants all proven.
- **Phase 2 — BUILT (2026-06-19), real-import acceptance PENDING.**
  `cutdeck/xml_export.py`: CutPlan → FCP7 (xmeml v5) XML. One `<sequence>`, video
  track + 2 linked audio tracks (stereo), one clipitem per KEEP span laid
  end-to-end, all referencing a single `<file>` listing. Frame math via
  `timebase.ms_to_frame` only; rate emitted as integer timebase + ntsc flag.
  GAP-2 satisfied: VFR timebase → export refuses. Round-trip key
  `cd{job}_p{plan}_s{span}` on clip name + comments. CLI:
  `python -m cutdeck.xml_export --job-id N` (or `--plan-id N`), writes the file
  and flips plan status to `exported`. 3 acceptance tests in
  `tests/test_cutdeck_xml_export.py` (frame accuracy/contiguity, VFR refusal, no-
  keep refusal); phase0/1 + smoke unaffected (35 green). **The acceptance that
  actually matters is still open:** a real 29.97 file must import clean into
  Premiere, frame-accurate at the 60-min mark, audio linked, no offline media —
  verify on the real machine. Untested in the wild: stereo link layout and the
  Windows `file://localhost/C%3A/` pathurl form.
- Deferred within Phase 1: `cut_correction` table is **not** added yet (it is the
  Phase 3 flywheel artifact); only `cut_plan` exists. The `Label` contract type
  exists but is unused until the LLM classifier (Phase 5) produces judgement
  labels — rules currently emit cut reasons directly on spans.
