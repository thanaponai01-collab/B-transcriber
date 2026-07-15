# IMPLEMENT_IMPROVEMENTS.md — 2026-07 improvement pass

Full-system review of the B-transcriber pipeline against the July-2026 open-source
Thai ASR landscape: what was broken, what was fixed in this pass, and the ordered
implementation plan for everything that remains. This file is the handoff — any
future session should be able to execute the phases below from this document alone.

**Evidence tags** (per the engineering protocol): **(proven)** = executed and
observed here · **(trace-only)** = concluded by reading code, chain complete ·
**(assumed)** = unverified premise, logged with its cost.

**Status at time of writing:** `pytest tests/` → **116 passed** (108 pre-existing
+ 8 new acceptance tests) **(proven)**. Branch `master`, working tree carries this
pass's changes uncommitted.

**Status update (2026-07-15):** all six phases in §2 landed and are committed
(`e9f8ed4` Phase 3, `3ed175f` Phase 4, `e6f58a1` Phase 6, `9a618f8` Phase 5).
`pytest tests/` → **148 passed (proven)**. Two phases resolved to a deliberate
"off" state rather than an activation — Phase 1 (Engine A swap reverted, lost
the gate) and Phase 2 (Engine B stays `passthrough`, correctly gated pending a
code-switch-heavy gold set) — see their resolution notes in §2 for why that is
not unfinished work but an evidence-based decision. Nothing in this document
remains to be executed; the only durable follow-up is the human step in Phase
2's resolution (grow the gold set) and the residual risks in §3 below.

---

## 0. Ground truth discovered during the audit

### 0.1 The working venv is Python **3.11.9**, not 3.13 **(proven)**

`./.venv/Scripts/python.exe --version` → `Python 3.11.9`, and both `funasr` and
`editdistance` **import successfully** in it. This contradicts CLAUDE.md,
config.yaml comments, and TODO_LEDGER, which all say FunASR is dead ("editdistance
has no Python 3.13 wheel") and NeMo is "Py3.13 unverified".

**Consequence:** the two shelved decorrelated Engine-B candidates are *not*
blocked by the environment:

- `funasr` (SenseVoiceSmall) — adapter already registered, dependencies already
  installed. Activation is purely eval-gated now.
- `nemo_toolkit[asr]` for `typhoon_rt` — NeMo supports Python 3.11 well
  **(assumed** until installed**)**; the "3.13 wheel risk" documented in
  TODO_LEDGER does not apply to this venv.

Update the stale docs when Engine B is activated (CLAUDE.md "Current engines",
config.yaml header comment, requirements.txt comment).

### 0.2 The gold set is still empty — every gate is inert

`transcribe/eval/goldenset/` contains nothing **(proven)**. This has been the #1
blocker since the June audit and it still is: the regression gate, bias-term gate,
and any engine-swap decision are all unmeasurable until it exists. Nothing in
this plan that says "eval-gated" can fire before Phase 0 completes.

**You already have gold material:** `output/Bangkok Festivals_CT6_Short2_D1 mine.srt`
is a hand-corrected SRT sitting next to the machine output for the same clip.
That correction effort is exactly what a gold sample is made of (Phase 0).

---

## 1. Defects found and FIXED in this pass

All fixes are small, mechanically tested, and landed together with
`tests/test_improvements_202607.py` (8 tests, one per defect class).

### 1.1 Eval harness ran the pipeline with an empty bias index — HIGH

`run_harness` isolates eval writes in a scratch DB (correct), but `run_file`
reads its bias terms *from the DB it runs against* — the freshly-created scratch
DB, which had zero bias terms **(trace-only, now test-pinned)**. So the flywheel's
regression gate — whose entire job is to measure whether a bias-index update
helps — evaluated a pipeline that never saw the bias terms. Meanwhile the run's
`bias_hash` was computed from the *real* DB, so the attribution claimed the terms
were active when they weren't.

**Fix:** `harness.py` now mirrors the live `bias_term` table into the scratch DB
before any sample runs. Test: `test_harness_scratch_db_receives_live_bias_terms`.

### 1.2 Repeated editor saves stacked duplicate corrections — HIGH

`correction` has no uniqueness on `(job_id, token_idx)` and the save endpoint
re-inserted every diff pair on every save. Saving the same job three times could
push a term across `flywheel.min_occurrences: 3` by itself — the flywheel would
learn from one human action as if it were three independent confirmations.

**Fix:** `store.create_correction` now replaces any prior row for the same
`(job_id, token_idx)` (latest correction wins); added `store.delete_correction`.
Tests: `test_repeated_saves_do_not_stack_duplicate_corrections`,
`test_refined_save_keeps_only_latest_text`.

### 1.3 Reopening a corrected job showed raw ASR text — MEDIUM

`GET /jobs/{id}` returned raw tokens only; saved corrections were invisible in
the editor (exports used them, the UI didn't). A user re-opening a job would
re-correct from scratch — and a revert had no path to delete the stale row.

**Fix:** the job view now merges corrections into `text` (with `raw_text` and a
`corrected` flag per token), and the save endpoint deletes corrections for tokens
the user reverted to their raw text. Test: `test_delete_correction_removes_reverted_edit`
plus the upsert tests above.

### 1.4 Deleting a hallucinated cue could promote `""` as a bias term — MEDIUM

Correcting a cue to empty text (the normal way to kill a hallucination) produced
`corrected_text=""`; three of those and the flywheel would upsert an empty bias
term (and `_classify_term("")` would crash on `term[0]`).

**Fix:** `biasindex.update_bias_index` skips blank terms before promotion.
Test: `test_empty_correction_text_is_not_promoted_to_bias_term`.

### 1.5 Eval baseline could cross `kind` boundaries; same-second ties — LOW

`get_last_passing_eval` ignored the `kind` column (a future CutDeck cut-quality
run would have become the transcription gate's baseline) and ordered by
`ran_at` alone (second resolution — two runs in one second tie unpredictably).

**Fix:** filter `kind='transcribe'` (parameterized) and tie-break on `id DESC`.
Tests: `test_last_passing_eval_ignores_other_kinds`,
`test_last_passing_eval_tiebreaks_same_second_by_id`.

### 1.6 Mai-yamok normalization missed space-separated repeats — LOW

`\s*ๆ+` collapses `เร็วๆๆ` but turns `เร็ว ๆ ๆ` into `เร็วๆๆ` (each ` ๆ` replaced
independently). Whisper emits spaced yamok often enough for this to desync
hyp-vs-gold scoring. **Fix:** `(?:\s*ๆ)+` → `ๆ`. Test: `test_mai_yamok_collapses_spaced_repeats`.

### 1.7 Housekeeping — LOW

- `_sentence_boundary_offsets` (faster_whisper.py): the `sent_tokenize` import
  sat *outside* the best-effort `try` its docstring promised — a missing
  pythainlp extra would have raised instead of degrading. Import moved inside.
- Editor server: removed dead `_config()` (it read cwd-relative `config.yaml`,
  which doesn't exist at the server's cwd — always returned `{}`; nothing called it).
- `config.yaml` exception lexicon expanded with common Thai-creator vocabulary
  (Shopee, Lazada, Grab, Instagram, LINE OA, Netflix, Google, Zoom, WiFi,
  Premiere Pro, iPad). Normalization applies identically to gold and hypothesis,
  so this cannot desync scoring.

---

## 2. The implementation plan (ordered by unblock-value)

### Phase 0 — Author the gold set (human, ~2–3 h, unblocks everything) — **DONE (proven)**

**Resolution (2026-07-14):** 4 clips frozen (Bangkok Festivals + Short1-3) via
`tools/make_gold.py`. Baseline: `CER_thai=0.1069, WER_latin=1.0205, BER=0.0,
thai_chars=2171, switches=0`. Note `switches=0` — none of the 4 clips has a
Thai↔Latin boundary, so `boundary_error_rate` is not yet a meaningful gate;
grow the set with code-switch-heavy footage before trusting BER numbers.

Nothing measurable can happen before this. Target: 10–15 min of representative
own footage — code-switch-heavy, some noisy sections.

1. Pick 3–5 clips (2–4 min each). Include the Bangkok Festivals clip — its
   hand-corrected SRT (`output/…D1 mine.srt`) means most of the correction work
   is already done.
2. Per clip: `python tools/make_gold.py draft --run <clip>` (or `--job-id N` for
   already-transcribed jobs) → hand-correct the `.draft.json` → 
   `python tools/make_gold.py freeze <draft>`. The freeze step validates schema,
   script labels, and monotonic timestamps.
3. Run `python -m transcribe.eval.harness --config transcribe/config.yaml` once
   to establish the baseline `eval_run` row.

**Acceptance:** harness prints nonzero `thai_chars`/`switches` and writes a
passing baseline. From here on, every phase below ends with a harness run.

### Phase 1 — Engine A upgrade: `typhoon-whisper-turbo` (YAML + one conversion) — **DONE, model reverted (proven)**

**Resolution (2026-07-14):** converted and evaled against the gold set. Turbo
**regressed** `cer_thai` to 0.1336 vs 0.1069 for `whisper-th-medium-ct2` — lost
the gate despite the published benchmark claim. Engine A stays on
`whisper-th-medium-ct2` (`config.yaml` `model_id` line left commented out).
**Do not re-try turbo without new evidence** — the published CER number does
not transfer to this footage/config combination.

The current Engine A (`biodatlab/whisper-th-medium-combined`, a whisper-medium
fine-tune) is no longer the accuracy/speed frontier. SCB10X's
[typhoon-whisper-turbo](https://huggingface.co/typhoon-ai/typhoon-whisper-turbo)
(Jan 2026, MIT) is Whisper **large-v3-turbo** fine-tuned on ~11,000 h of
normalized Thai — 809 M params but only 4 decoder layers, so it decodes *faster*
than medium while carrying large-v3-class acoustics. Its sibling
`typhoon-whisper-large-v3` reports **5.69 % CER** on Thai, beating Gemini 3 Pro
(6.91 %). The config file already anticipates this swap (`models/typhoon-whisper-turbo-ct2`
comment).

1. Convert once:
   ```
   ct2-transformers-converter --model typhoon-ai/typhoon-whisper-turbo \
     --output_dir models/typhoon-whisper-turbo-ct2 --quantization float16 \
     --copy_files tokenizer.json preprocessor_config.json
   ```
2. In `config.yaml` under `engines.faster_whisper`: set
   `model_id: models/typhoon-whisper-turbo-ct2`. If float16 is tight on the 8 GB
   3070 at `batch_size: 8`, set `compute_type: int8_float16` (the config comment
   already documents this) or halve batch_size — the OOM auto-halving will also
   catch it.
3. Run the harness. Keep whichever model wins `cer_thai` on YOUR footage —
   published benchmarks don't override the gate. **(assumed:** turbo wins on
   creator-style speech; cost if wrong: one conversion + one eval run.)

Note: large-v3-turbo checkpoints are known to have somewhat weaker word-level
timestamp alignment than large-v3 — watch cue boundaries in the first real
export; `_group_words_into_cues`'s sentence-boundary breaks mask most of it.

### Phase 2 — Engine B: a real, decorrelated second hypothesis — **ATTEMPTED, deliberately left off (proven)**

**Resolution (2026-07-14):** got `funasr` (SenseVoiceSmall) actually running —
fixed two real bugs (`hub="hf"` in `AutoModel(...)`, since funasr defaults to
ModelScope which 404s for this model outside China; harness subprocess PATH
needed `.venv/Scripts` so funasr's own pip step could find `pip.exe`). Both
fixes are committed in `engines/funasr.py`. But activating `engine_b: funasr`
produced **byte-identical harness metrics to `passthrough`** — traced to
`reconcile.py`'s `_script_fallback`, which always resolved Thai-script
disagreements to Engine A regardless of what Engine B said. That circularity
is now fixed (see Phase 3 resolution below: confidence decides first, script
is only the final tiebreak). Re-tried with Phase 3's LLM reconciler on: the
harness gate **passes** with `engine_b: funasr` + `llm_enabled: true`, but the
4-clip gold set has near-zero code-switching, so it can't yet show the
reconciler earning its 2× runtime — metrics don't move either direction.
**Config stays `engine_b: passthrough`** pending a gold set with real
disagreement-heavy material (code-switch-dense or noisy clips). Don't spend
effort installing NeMo for `typhoon_rt` before growing the gold set — it would
hit the identical measurement wall, not a `typhoon_rt`-specific issue.

Everything reconciler-related (agreement confidence, `_script_fallback`, LLM
tiebreak, `source_engine` provenance) is dead weight while `engine_b: passthrough`.
The June audit's requirement stands: Engine B must be **non-Whisper** so the two
engines fail differently. Candidates, in order of activation cheapness:

| Candidate | Architecture | Status in repo | Effort |
|---|---|---|---|
| `funasr` / SenseVoiceSmall | non-autoregressive CTC-ish | adapter registered; deps ALREADY importable (§0.1) | config edit + eval |
| `typhoon_rt` (Typhoon ASR Real-time) | FastConformer-Transducer, Thai-specific, CER ≈ 0.098 | adapter built + mock-tested; needs `nemo_toolkit[asr]` (fine on Py3.11) | pip install + eval |
| Qwen3-ASR-1.7B (Jan 2026) | LLM-decoder ASR, 52 langs incl. Thai, timestamps | no adapter yet | new adapter (~150 lines, mirror `whisper_multi`) + eval |

Plan: try `funasr` first (zero install risk), then `typhoon_rt` (Thai-specific,
transducers can't hallucinate over silence by construction). Qwen3-ASR is the
code-switch specialist option — its LLM decoder is exactly the class of model
the 2026 literature says wins intra-sentential Thai↔English switching — build
its adapter if the first two don't move `cer_thai`/`boundary_error_rate`.

Activation is one line (`engine_b: funasr`) + `python -m transcribe.eval.harness
--engine-b <name>` for the A/B. **The gate decides, not the model card.**
Cross-engine agreement must *earn* its 2× runtime by lowering `cer_thai` or BER.

### Phase 3 — Wire the LLM reconciler (only after Phase 2) — **DONE, adapted to local Ollama (proven)**

**Resolution (2026-07-14):** implemented `transcribe/pipeline/llm_reconcile.py`
— adapted to run entirely local (no Anthropic API key, no external network
call): `make_llm_fn(ollama_cfg)` POSTs to a local `ollama serve` instance over
stdlib `urllib`, model `qwen2.5:3b-instruct`. `reconcile._pick()` accepts the
`llm_fn(ta, tb, bias_terms) -> int` hook on disagreement with a built-in
fallback to `_script_fallback` on any exception (unreachable/unpulled model
just falls through). Also fixed the `_script_fallback` circularity described
below: confidence now decides first when both engines report one; script is
only the tiebreak when confidence can't. Gated off by default
(`reconciler.llm_enabled: false`) until the gold set has enough
disagreement-heavy material to prove a lift (see Phase 2 resolution) — the
wiring itself is verified end-to-end (instrumented run confirms the LLM path
fires on a real A/B disagreement), 12 tests in
`tests/test_phase3_llm_reconcile.py`. `harness.py` gained `--llm-enabled` to
mirror `--engine-b` for A/B eval runs.

`reconcile.reconcile(slots, bias_terms=...)` never receives `llm_fn` — every
disagreement falls to `_script_fallback`, which trusts Engine A's script
classification of its own output (circular on exactly the hard cases).

1. Implement `transcribe/pipeline/llm_reconcile.py`: a callable
   `(ta, tb, bias_terms) -> 0|1` using the Anthropic API (claude-haiku-4-5 —
   this is an index-selection task, not generation). Prompt: the two candidates
   plus ±2 neighbor tokens from each engine, bias terms, "return 0 or 1".
2. Batch disagreements into one call per N slots (they're independent); log
   cost-per-job. Timeout/failure falls through to `_script_fallback` (the
   wiring for that already exists in `_pick`).
3. Config: `reconciler.llm_enabled: false` by default; enable via YAML.
   Gate: harness with LLM on vs off.

Also fix the `_script_fallback` circularity while there: when confidences are
present on both sides, prefer confidence; use A's script only as the final tie.

### Phase 4 — Robustness for real daily use — **DONE, all five sub-items (proven)**

**Resolution (2026-07-14):** `job_phase` column added to `job` (additive,
idempotent `_migrate()` pattern) plus a new `engine_result` table storing each
engine's token list + raw word JSON. `run.py` resumes a `failed` job for the
same media sha256 from its last completed phase, reusing cached
`engine_result` rows instead of re-running finished engines (4.1). The raw
per-word list rides on the same table (4.2) — no longer discarded. VFR
sources get an actual ffmpeg CFR-proxy transcode + re-probe via
`transcribe/timebase.py::conform_vfr` (4.3), gated by `conform_vfr: true`.
Denoise switched to in-memory DeepFilterNet `enhance()` calls, no per-window
temp WAV (4.4). `run.py` prints a machine-readable `JOB_ID=N` line;
`transcribe_file.py` parses that instead of scraping a logging line (4.5).
Tests: `test_job_resumability.py`, `test_vfr_conform.py`,
`test_denoise_inmemory.py`.

**4.1 Job resumability (GAP-8).** A crash at minute 45 of a 60-min file costs
everything. Add a `job_phase` column (or extend `job.status`) recording
`ingested → engine_a_done → engine_b_done → reconciled → written`; persist each
engine's token list as JSON alongside (e.g. an `engine_result` table). On re-run
of a `failed` job for the same media sha256, resume from the last completed
phase. This is a schema change — run it through the data-evolution discipline
(additive columns only, no destructive migration; `_migrate()` already has the
idempotent-ALTER pattern to follow).

**4.2 Persist the word-level raw list.** `EngineResult.raw["words"]` (the
per-word timestamps CutDeck Phase 5 needs for filler excision) is currently
**discarded** in `run.py::_transcribe_with` — the "re-derived on demand" claim
in CLAUDE.md 5.4 has no storage behind it **(trace-only)**. Cheapest fix rides
on 4.1's `engine_result` table: store the raw word list JSON per job. Without
this, CutDeck Phase 5 will silently have to re-run the engine.

**4.3 VFR conform (GAP-2 other half).** `xml_export.py` already refuses VFR
sources; the promised ffmpeg CFR-proxy transcode (`conform_vfr: true`) is still
unimplemented. Due when the first real phone-footage clip needs XML export:
`ffmpeg -i in.mp4 -vsync cfr -r <target> -c:a copy proxy.mp4`, re-probe, re-run.

**4.4 Denoise: profile, then decide.** The rolling DeepFilterNet pass writes a
temp WAV per 2-s window and only runs for chunk engines (currently never). When
a chunk engine returns, either switch to in-memory `enhance()` calls or make
denoise opt-in — but only after the gold set shows it helps `cer_thai` on your
actual room-tone footage.

**4.5 `transcribe_file.py` job-id parsing.** It scrapes the job id from a
logging line (`"Job N done:"`). If logging format/level changes, SRT auto-export
silently stops. Have `run.py` print a machine-readable line to stdout
(e.g. `JOB_ID=N`) and parse that instead.

### Phase 5 — Editor and flywheel quality-of-life — **DONE, all three items (proven)**

**Resolution (2026-07-15):** `static/index.html` now sends a one-tap reason
tag (misheard / spelling / code-switch / name-term / style) on the focused
token, carried into the save payload alongside the existing diff plumbing.
`confidence` is populated on faster-whisper cues from `avg_logprob`/word
probabilities in `_words_of` (previously always null) and low-confidence
cues are tinted in the editor. The job API's `corrected: true` per-token flag
(§1.3) now drives a visible style (green border) so a reviewer can see what's
already fixed. Tests updated in `test_faster_whisper_cues.py` and
`test_faster_whisper_truncation_recovery.py`.

- **Reason-tag UI (GAP-7):** backend + schema + diff plumbing all accept
  `reason`; `static/index.html` never sends it. Add a small one-tap tag row
  (misheard / spelling / code-switch / name-term / style) on the focused token,
  stored into the save payload. Purely frontend.
- **Confidence highlighting (A.2):** tokens carry `confidence` (null for
  faster-whisper cues today — populate from `avg_logprob`/word probabilities in
  `_words_of` when available) — tint low-confidence cues so the human eye goes
  where the model is unsure. This is the single biggest correction-throughput
  lever for the flywheel.
- **Show `corrected` state:** the job API now returns `corrected: true` per
  token (§1.3) — style corrected tokens (e.g. green border) so a reviewer can
  see what's already been fixed.

### Phase 6 — Normalization polish (with the gold set as referee) — **DONE (proven)**

- Align number-verbalization policy (สิบ ↔ 10) and mai-yamok expansion policy
  explicitly in STYLE_GUIDE.md with the Na-Thalang-style canonical guideline the
  Typhoon pipeline uses — Engine A (Typhoon-trained) and the gold set must agree
  on the *written form*, or `align_hyp`'s Jaccard similarity and the eval both
  degrade **(trace-only)**.
- Decide the exception-lexicon spacing policy: protected terms currently also
  skip Thai↔Latin *boundary* spacing around them (placeholder side effect,
  consistent on both sides of the eval, but a style choice worth making
  deliberately).

**Resolution (2026-07-15):** Fetched and read the Na-Thalang et al. (2025)
guideline via the Typhoon ASR Real-time paper ([arXiv:2601.13044](https://arxiv.org/abs/2601.13044))
— it's a real, published standard, not a placeholder citation. It normalizes
numbers to full spoken-Thai-word form and expands mai yamok to the repeated
word (`เก่งๆ` → `เก่ง เก่ง`), for word-level benchmark scoring.

**Decision: do NOT adopt either transform.** Both require word-segmentation
ground truth that STYLE_GUIDE §1 deliberately refuses to depend on (Thai has
no orthographic word boundaries — that's *why* this project scores Thai as
character-level CER instead of word-level WER in the first place). Adopting
Na-Thalang's word-form normalization now would also force hand-re-authoring
the gold set frozen in Phase 0 (`transcribe/eval/goldenset/*.json` already
contains real attached-ๆ examples: `จริงๆ`, `ต่างๆ`, `หลายๆ`, `ใครๆ`). The
divergence and its exact trigger to revisit — a Typhoon-trained Engine A (Phase
1) regressing `cer_thai` because its raw output verbalizes numbers/expands ๆ
even when otherwise correct — are written into STYLE_GUIDE.md §2 and §3 so the
harness, not intuition, makes the call when Phase 1 actually runs.

**Exception-lexicon spacing: decided in favor of normal boundary-spacing.**
Read `transcribe/eval/metrics.py` end to end: `_thai_char_stream` and
`_latin_word_stream` extract by character class, not whitespace, and
`_switch_points` uses each token's `script` field — so this style choice was
**never observable by any eval gate**, only by a human reading the text. Since
gluing brand names to Thai neighbors (`ผมใช้iPhoneอยู่`) has no accuracy
upside and reads worse than spacing them like any other code-switch word
(`ผมใช้ iPhone อยู่`, consistent with STYLE_GUIDE §4), `normalize()` was
reordered so boundary-spacing runs before exception protection — the lexicon
now only shields a term's interior from digit/yamok/PyThaiNLP passes, not its
edges. New test: `test_normalization_exception_lexicon_gets_boundary_spacing`
in `tests/test_smoke.py`.

---

## 3. Residual risks and assumptions

| # | Assumption / risk | Cost if wrong | Trigger to revisit |
|---|---|---|---|
| 1 | typhoon-whisper-turbo beats th-medium on YOUR footage | one eval run | Phase 1 harness result |
| 2 | NeMo installs clean on Py3.11 venv | pip failure, fall back to funasr/Qwen | Phase 2 |
| 3 | Gold set of 10–15 min is representative enough to gate on | gates pass/fail on noise; keep `regression_abs_floor` | grows with every corrected job |
| 4 | Long-span stitch (`_LONG_SPAN_SAFE_S=25`) still has one residual gap on very dense speech | occasional missing words in pause-free monologue | revisit if real footage shows gaps; fuzzy dedup in stitch.py is the documented fix |
| 5 | `whisper_multi` (large-v3) stays the fallback Engine B doc'd in config | correlated-error false agreement (June audit BLOCKER 3) | never activate two Whispers together |
| 6 | Gold set + `normalize()` deliberately diverge from Na-Thalang word-form number/ๆ verbalization (Phase 6) | if wrong, a Typhoon-trained Engine A's raw output looks worse than it is — spurious `cer_thai` regression, not a real accuracy loss | Phase 1 harness run on typhoon-whisper-turbo; if `ๆ`-bearing or number-bearing spans specifically regress, build the canonicalizer then |

## 4. Sources

- [typhoon-ai/typhoon-whisper-turbo](https://huggingface.co/typhoon-ai/typhoon-whisper-turbo) — 809M large-v3-turbo Thai fine-tune, MIT, Jan 2026
- [typhoon-ai/typhoon-whisper-large-v3](https://huggingface.co/typhoon-ai/typhoon-whisper-large-v3) — 5.69% Thai CER reference point
- [Typhoon ASR Real-time paper](https://arxiv.org/pdf/2601.13044) — FastConformer-Transducer, CER 0.0984, CPU-capable
- [scb-10x/typhoon-asr](https://github.com/scb-10x/typhoon-asr) — runtime + CLI
- [Na-Thalang et al. (2025) canonical guideline](https://arxiv.org/html/2601.13044v1) — described in §III of the Typhoon ASR Real-time paper; verbalizes numbers to Thai words and expands mai yamok to the repeated word for benchmark scoring (Phase 6: read directly, confirmed real, deliberately not adopted — see §2 above and STYLE_GUIDE.md §2/§3)
- [Qwen/Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) + [technical report](https://arxiv.org/pdf/2601.21337) — 52-language LLM-decoder ASR incl. Thai, Jan 2026
- [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CT2 conversion of fine-tuned checkpoints
