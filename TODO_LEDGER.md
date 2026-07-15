# TODO_LEDGER

Deferred work from the IMPLEMENT_CUTDECK.md build. Each entry has a trigger that
makes it due. Owner: build-discipline.

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
