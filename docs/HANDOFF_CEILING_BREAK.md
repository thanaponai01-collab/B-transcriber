# HANDOFF — B-transcriber: Breaking the Thai Accuracy Ceiling

**For:** Claude Code, working in the B-transcriber repo
**Hardware:** RTX 3070, 8 GB VRAM. Working venv is **Python 3.11.9** (not 3.13 — see TODO_LEDGER 2026-07-14). Windows host.
**Prime directive:** Accuracy first. Nothing activates without the eval harness proving it. The reconciler selects, never generates.
**Discipline:** Read `CLAUDE.md`, `SYSTEM_SPEC.md`, `TODO_LEDGER.md` before touching anything. Every phase ends with the full suite green plus new acceptance tests. Every engine/config probe runs as `--experiment` so it can never become the baseline by accident. Update `TODO_LEDGER.md` as phases complete.
**Date of audit:** 2026-08-04. External evidence current as of the same date.

---

## 1. Where the ceiling actually is (measured, not guessed)

The live baseline (metrics v2, 5-clip gold set, Engine A = `biodatlab/whisper-th-medium-combined` via CTranslate2, Engine B = passthrough):

| Signal | Baseline | What it means |
|---|---|---|
| `cer_thai` | **0.1451** | 1 in 7 Thai characters wrong. On the hand-recut Short4 reference it is 0.0433 — clean-audio shorts are much better than the corpus number. |
| `wer_latin` | **1.0452** | > 1.0 — the Latin/English stream is effectively *all* wrong or missing. Not degraded: absent. |
| `boundary_error_rate` | **0.8592** | Engine A emits 38 switch points against 104 in the reference and only 10 match. It finds barely a third of Thai↔English switches. |
| Segmentation / cue timing | **unmeasured** | On the user's real production loop (pure-Thai shorts, hand-recut in Premiere), `wer_latin` and BER score zero events — 2 of 3 gate metrics are inert, and the thing the human actually fixes (cue boundaries: 31 hand cues vs 22 pipeline cues on Short4) is invisible to the gate. |

So the ceiling has **four independent walls**, in impact order:

1. **Engine A itself is no longer near the open-weights frontier for Thai** (§2, the biggest and cheapest win).
2. **Code-switching is unsolved** — no active second hypothesis, and every Engine-B candidate tried so far was correctly rejected (§4).
3. **Segmentation quality is both the user's real pain and unmeasured** — the greedy `cue_target_chars` fill is the diagnosed blocker, and no gate metric sees it (§3, §5).
4. **The gold set was 5 clips at audit time; now 8 (~10.4 min), growth in progress (§3.2)** — every one of the above decisions was gated on a sample too small and too skewed to be trusted for fine margins, and is now due for re-probe against the grown corpus (§3).

Everything below is organized to knock these walls down in an order where each phase makes the next one measurable.

---

## 2. External evidence: the 2026 Thai ASR landscape vs this repo

The Typhoon ASR Real-time paper (arXiv 2601.13044, SCB10X, Jan 2026) publishes a directly relevant benchmark table (CER, canonical Na-Thalang normalization):

| Model | TVSpeech (hard) | GigaSpeech2 | FLEURS-th (norm.) |
|---|---|---|---|
| **Typhoon Whisper Large-v3** (offline) | **6.32%** | **4.69%** | 5.69% |
| Pathumma-Whisper Large-v3 (NECTEC) | 10.36% | 5.84% | 7.88% |
| Typhoon ASR Realtime (already tried, rejected) | 9.99% | 6.81% | 9.68% |
| Gemini 3 Pro | 10.95% | 12.50% | 6.91% |
| **Biodatlab Whisper Large** | **18.96%** | **13.22%** | 15.26% |

Read that last row carefully: the **large** Thonburian model scores 2–3× the CER of Typhoon/Pathumma Whisper Large-v3 — and this repo runs the Thonburian **medium**. The current Engine A lineage is simply behind the 2026 frontier, on every test set, under neutral normalization. This is not a marginal tuning question; it is the single largest accuracy lever available, and it is nearly free to try:

- **Typhoon Whisper Large-v3** (`scb10x/typhoon-whisper-large-v3`) and **Pathumma-Whisper-th-large-v3** (`nectec/Pathumma-whisper-th-large-v3`) are both plain Whisper large-v3 fine-tunes → both convert with `ct2-transformers-converter` exactly like the current model → both run through the **existing `faster_whisper` adapter with zero code changes** — a CT2 conversion plus a YAML `model_id` edit.
- VRAM: large-v3 in CT2 `int8_float16` is ~1.6 GB weights; comfortably inside 8 GB even with `BatchedInferencePipeline` (drop `batch_size` to 4–6 for the first run; the OOM auto-halving is already in place).
- **Do not conflate with the two prior Typhoon rejections.** `typhoon-whisper-turbo` (a distilled turbo) lost the gate in 2026-07 and `typhoon_rt` (FastConformer) lost in 2026-07-16 — *Typhoon Whisper Large-v3 is a different model from both* and has never been probed in this repo.

Other 2026 arrivals that matter (details in §4):

- **Qwen3-ASR-1.7B / -0.6B** (Alibaba, Apache 2.0): open-weights LLM-decoder ASR, **Thai among 30 languages**, language ID, timestamps via the companion `Qwen3-ForcedAligner-0.6B`, transformers + vLLM inference. This is the architecture class (LLM decoder = semantic context) that the 2026 literature says wins code-switching — and the repo's own config comment already names "a Qwen3-ASR adapter" as the next untried Engine-B candidate.
- **Fun-ASR-MLT-Nano-2512** (FunAudioLLM, ~800M): **Thai genuinely supported** (31 languages — unlike SenseVoiceSmall, whose 5-language card is why `funasr` was retired), **hotword biasing**, timestamps, llama.cpp/GGUF runtime down to ~484 MB, diarization via the FunASR pipeline. This satisfies the ledger's "don't re-probe without a *different underlying model*" clause for the retired `funasr` adapter, and its CPU/GGUF path sidesteps VRAM sequencing entirely.
- **Generative error correction (GER/GenSEC)** is now a mature literature (Whispering-LLaMA, FlanEC, task-activating prompting; ICASSP 2026 sessions): an LLM rewrites/corrects ASR hypotheses from N-best lists. Note the tension: **this repo's select-only reconciler deliberately forbids generation** as its anti-hallucination guarantee. GER is *not* a license to break that — see §6 for the constrained way in.
- Cloud engines (Gemini 3 Pro, GPT-4o-transcribe, ElevenLabs Scribe): Gemini 3 Pro loses to local Typhoon Whisper Large-v3 on 2 of 3 Thai benchmarks above, and the repo is deliberately local-only (the Ollama rule). **Not recommended** — the open-weights path is currently *ahead* for Thai, which is unusual and worth exploiting.

---

## 3. PHASE 1 — Make the gate see what matters (do this before any engine swap)

> **STATUS (2026-08-05): §3.1 (metrics v3) DONE. §3.2 (gold-set growth) IN
> PROGRESS — 3 clips added by the user since the 2026-08-04 audit
> (`Short1_D5`, `PeterWolf`, Wealthy40 DCA-update), corpus now 8 clips /
> ~10.4 min, clearing the low end of the 10–15 min target. 2 of 3 strata
> covered; the noisy/hard-clip stratum is still missing. Current baseline:
> `eval_run.id=46`.**
>
> **Done, verified, wired end-to-end:**
> - `transcribe/eval/metrics.py`: `METRICS_VERSION` bumped 2→3. `EvalMetrics` gained
>   `cue_boundary_error_rate` (F1@`boundary_tol_ms` between ref/hyp cue-start
>   timestamps — reuses the same match-and-micro-F1 machinery as the existing
>   switch-point BER, since a token's `start_ms` already **is** a cue boundary at
>   5.4 granularity; no gold-schema change was needed), `overlapping_cues` (hard
>   invariant, not a rate), and descriptive-only `cue_count_delta` /
>   `shortest_cue_ms` / `nonzero_gap_count`.
> - `transcribe/eval/harness.py`: aggregates all of the above across the gold set
>   (cue-BER via corpus micro-F1, exactly like switch-point BER); added
>   `cue_boundary_error_rate` to the regression-tolerance gate alongside
>   `cer_thai`/`wer_latin`/`boundary_error_rate`; `overlapping_cues > 0` **hard-fails
>   the run unconditionally**, even on a first run with no baseline to compare
>   against (this is the "assertion of 0, not a rate" from the spec below).
> - `transcribe/db/schema.sql` + `store.py`: `eval_run` gained the 5 matching
>   columns (idempotent `_migrate` ALTERs, so existing DBs upgrade automatically —
>   but note `run_harness` does **not** call `init_db` on the caller's `db_path`
>   itself; a pre-existing `transcriber.db` needs one manual
>   `python -c "from transcribe.db.store import init_db; init_db()"` after this
>   change lands, same as every prior `eval_run` column addition).
> - `transcribe/eval/README.md` updated with the new metric + invariants.
> - New test file `tests/test_metrics_v3.py` (11 tests: cue-F1 matching/mismatch/
>   tolerance, overlap detection, gap stats, missing-timestamp safety, harness
>   hard-fail-with-no-baseline, store roundtrip). **Full suite: 310 passed** (was
>   216 at the 2026-07-30 ledger entry; grew via intervening phases + these 11).
> - Incidental fixes made in the touched files (both were merge-artifact
>   duplicates, not new bugs): a duplicated `regressed()` function definition in
>   `metrics.py`, and a duplicated `shutil.rmtree(scratch_dir, ...)` call in
>   `harness.py`.
> - **Fresh v3 baseline recorded** on the existing 5-clip gold set
>   (`python -m transcribe.eval.harness --config transcribe/config.yaml --db
>   transcriber.db`, `eval_run.id=25`, `metrics_version=3`, `passed=True`):
>
>   | Signal | v3 baseline | Note |
>   |---|---|---|
>   | `cer_thai` | 0.1415 | vs 0.1451 in the §1 table — within run-to-run noise (bias index / minor drift since the audit), not a regression signal since this *is* the new baseline |
>   | `wer_latin` | 1.0452 | matches §1 exactly |
>   | `boundary_error_rate` | 0.8169 | vs 0.8592 in §1 — same-direction drift as cer_thai |
>   | `cue_boundary_error_rate` (**new**) | **0.3590** (F1 ≈ 64%) | first-ever measurement of this signal |
>   | `overlapping_cues` | 0 | hard invariant clean |
>   | `cue_count_delta` | −20 | hyp emits 20 fewer cues than gold, summed over 5 clips — pipeline under-segments vs the hand-recut references |
>   | `shortest_cue_ms` / `nonzero_gap_count` | 320.0 / 17 | descriptive, for trend-watching once Phase 3's DP cue split lands |
>
>   Acceptance line-by-line: "`wer_latin` and BER both score nonzero events on
>   ≥3 clips" — **met** (both nonzero on the corpus aggregate; the underlying
>   5-clip corpus is the same one the §1 numbers were measured on). "cue-F1
>   scored on ≥2 hand-recut references" — **met**: all 5 existing gold JSONs
>   carry `start_ms` per token, and per the Premiere-recut-loop workflow
>   (`tools/make_gold.py from-srt`) these are already hand-authored cue
>   boundaries, not synthetic ones.
>
> **IN PROGRESS — the schedule-critical human task:** growing the gold set to
> 10–15 minutes across three strata (§1.2). As of 2026-08-05, three clips
> have landed: `Short1_D5` (12 cues, 9/12 mixed script — the first genuinely
> code-switch-dense sample), `PeterWolf` (88 cues, dense classical-music
> code-switch content), and the Wealthy40 DCA-update clip (48 cues, finance
> vlog with heavy Thai/English switching). Corpus is now **8 clips, ~10.4
> minutes** — the low end of the 10–15 min target is cleared. Strata covered:
> production-style pure-Thai shorts (`Short1/2/3`, `orchestra_sections`) and
> real Thai-English code-switch material (the three new clips plus the
> pre-existing `Short2_D1`). **Still missing: one noisy/hard clip** — the
> TVSpeech-lesson stratum from §1.2 item 3. Tooling unchanged:
> `python -m tools.make_gold from-srt <clip>.srt --audio <clip>.wav` is the
> fastest path when a hand-recut Premiere SRT already exists, otherwise
> `draft` → hand-correct `.draft.json` → `freeze` (see `tools/make_gold.py`
> docstring).
>
> **Baseline reset twice as the corpus grew** (`eval_run.id=42` after
> `Short1_D5`, `id=44` after `PeterWolf`, **`id=46`** after Wealthy40 — the
> current active baseline: `cer_thai 0.1751`, `wer_latin 0.8291`,
> `boundary_error_rate 0.5324`, `cue_boundary_error_rate 0.3904`,
> `passed=True`). `wer_latin` and BER are no longer near-inert (were
> 1.0452/0.8169 on the old 5-clip baseline) now that real code-switch content
> is in the corpus — the un-blinding this whole handoff was chasing is
> starting to show up for real, not just via the metrics-v2/v3 machinery.
>
> **Every later phase (§4 Engine A swap, §5 DP cue split, §6 Engine B, §7
> item 4 bias terms) was rejected on the old 5-clip corpus by margins this
> handoff itself called too small to trust — those verdicts are now due for
> re-probe against `eval_run.id=46`, and again once the noisy-clip stratum
> lands.**
>
> Housekeeping (§8) was explicitly out of scope for this pass and is
> untouched — the CLAUDE.md merge-conflict marker, duplicate `make_gold.py`,
> and stale `transcribe.db` still need their own pass.



An engine swap judged by the current gate could wreck cue timing on pure-Thai production content and pass clean (ledger, 2026-07-30: "two of three gate signals were inert, and segmentation error 0.31 is invisible"). Fix the measurement floor first.

### 1.1 Cue-structure metrics → metrics v3 (`transcribe/eval/metrics.py`)
Already specified as open in TODO_LEDGER. Add to `compute_metrics`:
- **Cue-boundary F1 @300 ms** against gold cue starts (the Short4 work already computed this ad hoc: 0.717/0.691 — promote it to a first-class metric).
- **Overlapping-cue count as a hard assertion of 0** (not a rate — one overlap is a shipped bug).
- Optional descriptive stats (cue count delta vs gold, shortest-cue ms, non-zero-gap count) recorded on the run for trend-watching, not gated.
- **Bump `METRICS_VERSION` to 3** — baseline partitioning already handles the fresh start.

Gold cue boundaries need to exist: extend the gold JSON schema with optional cue-start times, sourced from the hand-recut Premiere SRTs the user already produces (the `srt_io.parse_srt` + `align_srt` machinery from the flywheel path parses them today).

### 1.2 Grow the gold set with intent (human-in-the-loop, tooling exists)
5 clips cannot arbitrate 1–2% CER margins nor represent the production mix. Target **10–15 minutes** across three deliberate strata:
1. **Production-style pure-Thai shorts** (what the user actually ships) — with hand-recut cue boundaries, feeding 1.1.
2. **Real Thai-English code-switch material** (tech/business creator speech: "ผมอยากจะ share screen ให้ดู") — this is what un-blinds `wer_latin` and keeps BER honest.
3. **One noisy/hard clip** (the TVSpeech lesson: hard-condition rankings differ from clean rankings).

Tooling: `tools/make_gold.py` draft→freeze already works end-to-end; the hand-recut-SRT ingestion path exists. This is authoring hours, not code. **Every phase below is gated on this set, so it is the schedule-critical item.**

**Acceptance for Phase 1:** metrics v3 live with tests; fresh v3 baseline recorded on the grown gold set; `wer_latin` and BER both score nonzero events on ≥3 clips; cue-F1 scored on ≥2 hand-recut references.

---

## 4. PHASE 2 — Engine A swap probes (the biggest single win)

> **STATUS (2026-08-04): DONE — both candidates REJECTED, production config
> unchanged.** Executed ahead of §1.2's gold-set growth (the suggested order
> in §10 gates this phase on that human task, but the probe itself is a
> mechanical YAML+harness exercise that doesn't require it — see the note at
> the end of this section on why the verdict should still be treated as
> provisional). Full numbers in TODO_LEDGER.md ("Engine A large-v3 swap
> probes"); summary:
>
> - **Repo-ID correction:** `scb10x/typhoon-whisper-large-v3` (as written
>   below) does not exist on the Hub. The real repo is
>   `typhoon-ai/typhoon-whisper-large-v3`. `nectec/Pathumma-whisper-th-large-v3`
>   was correct.
> - Both converted to CT2 (`int8_float16`) with zero adapter code, as
>   predicted. Pathumma's repo lacks `tokenizer.json` — generated one via
>   `transformers.WhisperTokenizerFast` before probing (see ledger for why:
>   `faster_whisper` silently falls back to the wrong-vocab `whisper-tiny`
>   tokenizer otherwise).
> - **Typhoon Whisper Large-v3** (`eval_run.id=26`) vs baseline
>   (`eval_run.id=25`, `cer_thai 0.1415`, `boundary_error_rate 0.8169`,
>   `cue_boundary_error_rate 0.3590`): `cer_thai 0.1731`, `boundary_error_rate
>   1.0000` (0 of 104 reference switch points matched — total failure on
>   code-switching on this gold set), `cue_boundary_error_rate 0.5926`. Worse
>   on every gated signal.
> - **Pathumma Whisper Large-v3** (`eval_run.id=27`): `cer_thai 0.1464`
>   (inside the regression-tolerance abs floor — not itself disqualifying),
>   `boundary_error_rate 0.8615`, `cue_boundary_error_rate 0.5741`. BER and
>   cue-BER regress past the gate; harness verdict `passed=False`.
> - **Production config.yaml: unchanged** (`engine_a: faster_whisper`,
>   `models/whisper-th-medium-ct2`). Both CT2 conversions kept on disk
>   (`models/typhoon-whisper-large-v3-ct2`,
>   `models/pathumma-whisper-th-large-v3-ct2`) for a cheap re-probe once §1.2
>   lands — no need to re-download.
>
> **Why this is a real result but not yet the final word:** this is now the
> *second and third* time a published-SOTA Whisper large-v3 lineage model has
> lost to the in-repo th-medium baseline on this specific 5-clip corpus
> (`typhoon-whisper-turbo` was the first, 2026-07). §7's normalization-policy
> divergence (this repo's mai-yamok/colloquial choices vs the Na-Thalang
> convention these models were likely evaluated under upstream) is the prime
> suspect for why published 2–3× headroom doesn't reproduce — but that's
> unverified against a corpus of 5 clips. Treat "th-medium wins" as the
> current best-evidence answer, not a closed question; re-run this phase once
> §1.2's grown gold set exists, and consider auditing §7's mai-yamok policy
> against what these models actually emit before re-probing.
>
> **Hardware note:** this probe actually ran on an RTX 4070 Ti, 12 GB
> (confirmed via `nvidia-smi`) — this repo isn't tied to one machine, so
> "RTX 3070, 8 GB" in CLAUDE.md/this doc should stay read as the conservative
> floor to design and gate against, not a literal spec of whichever box runs
> a given session. Doesn't change any conclusion above since the CT2
> int8_float16 models fit comfortably within the 8 GB floor anyway.

With the v3 baseline in place:

1. Convert both candidates to CT2 (same command as the comment in `requirements.txt`):
   - `models/typhoon-whisper-large-v3-ct2` from `scb10x/typhoon-whisper-large-v3`
   - `models/pathumma-whisper-th-large-v3-ct2` from `nectec/Pathumma-whisper-th-large-v3`
2. Probe each via YAML only (`engines.faster_whisper.model_id`, `compute_type: int8_float16`, `batch_size: 4`), harness with `--experiment`.
3. Judge on **all** signals — `cer_thai` is the headline, but 1.1's cue metrics are exactly the regression risk of a new model's word-timestamp behavior (`_group_words_into_cues` consumes raw word timings; a large-v3 fine-tune may time sub-word pieces differently than th-medium).
4. Winner (if any beats the gate) becomes the production baseline; keep th-medium-ct2 on disk as the fallback, mirroring the turbo precedent.

**Expected outcome, stated honestly:** the published table says 2–3× CER headroom over the Biodatlab *large*; the repo runs the *medium*, so the gap should be at least that — but published benchmarks use Na-Thalang normalization and clean test sets, and `typhoon-whisper-turbo`'s published numbers also failed to reproduce here (CER 0.1336 vs 0.1069 — reverted). That precedent is exactly why this is a gated probe and not a recommendation to swap blind. If *both* large-v3 fine-tunes lose to th-medium on the grown gold set, that is a major finding about the gold set's domain (record it; suspect the mai-yamok/colloquial policy divergence of §7 first).

**Also in this phase — speed guardrail:** large-v3 is ~3× the compute of medium. Record RTF alongside; the standing target from the speed handoff (≥3× realtime on the 3070) still applies. `int8_float16` is the expected mitigation.

---

## 5. PHASE 3 — Cost-minimizing cue split (the user's actual pain)

> **STATUS (2026-08-04): DONE — built, tested, probed; NOT ACTIVATED.** The DP
> split is real, correctly wired behind `config.yaml`'s
> `engines.faster_whisper.cue_split_algorithm` flag (`greedy` default |
> `dp`), and beats greedy on two of three cue-structure signals — but still
> regresses the specific `cue_boundary_error_rate` metric this phase exists
> to win, so it stays off. Full numbers, the tuning sweep, and the honest
> read on why: TODO_LEDGER.md "DP cue split probe" (2026-08-04). Summary:
>
> - Candidate breaks are every pythainlp word boundary (a real upgrade over
>   greedy, which could only see Whisper's sporadic emitted spaces); the two
>   STYLE_GUIDE §7 vetoes are excluded from the candidate set outright
>   (illegal, not just costly); sentence boundaries and real silence gaps
>   stay hard splits, same invariant as greedy.
> - Best-tuned probe (`eval_run.id=32`/`34`): `cue_boundary_error_rate
>   0.3865` vs baseline `0.3590` — a **regression**, `passed=False`.
>   `cue_count_delta` improved from -20 to **-3** and switch-point matching
>   from 10/104 to **13/104**; `cer_thai`/`wer_latin` were bit-identical to
>   baseline on every single probe (correctly verifies cue-splitting can't
>   move text accuracy — it only changes where the same text gets cut).
> - **Not activated.** `cue_split_algorithm` stays `greedy` in production
>   config.yaml; production output is byte-identical to before this session.
> - **Same caveat as §4's Engine A rejections:** gated on the same 5-clip
>   corpus §1.2 already flagged as too small for fine margins — the 0.0275
>   absolute cue_BER gap here is exactly what that gold-set growth would
>   disambiguate from noise. Don't hand-tune further without new evidence;
>   re-probe once §1.2 lands, or score candidate breaks against `cue_BER`
>   directly instead of the char/duration proxy next time (see ledger).

Diagnosed precisely in TODO_LEDGER (2026-07-30): `_group_words_into_cues` closes a cue the instant `n_chars >= cue_target_chars` and breaks at whatever word boundary it stands on — measured splitting subject from verb (`ฉัน | จะรอ`), particle from clause (`นะคะให้ | น้อง`). The space-break signal (3) was built and measured F1-neutral *because* the greedy fill relocates the arbitrary boundary — "the blocker is the greedy fill itself."

**Replace greedy fill with a dynamic-programming split:** over each uninterruptible word run, choose cue boundaries minimizing a cost = deviation from `cue_target_chars` + penalty for breaking inside a `pythainlp` clause (use `sent_tokenize`/token-boundary strength as the linguistic prior; the Whisper-space and gap signals become boundary-cost *discounts* instead of hard triggers) + STYLE_GUIDE §7 vetoes as infinite cost (mai yamok orphaning, numeral+classifier). Classic subtitle line-breaking DP — O(n·k), trivial at cue scale.

This is the highest-leverage change for the Premiere recut loop, and Phase 1.1 is what makes its win/loss measurable (cue-F1 against the hand recuts). Keep the greedy path behind a config flag for one release for A/B, then delete.

**Acceptance:** cue-F1 improves on ≥2 hand-recut references; no `cer_thai` movement (this phase must not touch text); suite green.
**Acceptance verdict:** `cer_thai` invariance held exactly (met); suite green (met, 323 passed); cue-F1 did **not** improve (not met — it's the one criterion that decides activation, so the flag stays off). See status block above.

---

## 6. PHASE 4 — Engine B that can actually earn its runtime (code-switch wall)

> **STATUS (2026-08-05, third pass same day): §4.3's two "next lever" ideas
> both INVESTIGATED WITH REAL EVIDENCE and REJECTED — Engine B still NOT
> ACTIVATED.** Continuing straight from the second-pass status block below
> (kept verbatim further down for history), on the same RTX 4070 Ti machine
> with real gold-set audio.
>
> **Root cause was NOT the confidence=None bias the second pass diagnosed —
> it was a span-granularity mismatch, found by instrumenting real
> disagreement pairs instead of theorizing.** Every logged `_script_fallback`
> disagreement showed Engine A's ~2-5s phrase cue matched against ONE
> Qwen3-ASR token spanning up to 25s (the adapter inherited
> `faster_whisper`'s `_LONG_SPAN_SAFE_S=25.0` with no override) — `align_hyp.py`
> compares each short A cue against whichever B token's time window
> overlaps it, so every A cue inside a long VAD segment was being compared
> against the *same* giant multi-sentence B blob. Not a real head-to-head at
> any confidence-tiebreak logic could act on. **Fixed:** the adapter now
> takes a `max_span_s` param (default 8.0, `config.yaml`'s
> `engines.qwen3_asr.max_span_s`) capping its own span splitting well under
> Whisper's 25s ceiling, so candidates are finally scale-comparable to A's
> cues. Re-probed: gate numbers came back **byte-identical** to the
> pre-fix probe (`cer_thai 0.1415`, `wer_latin 1.0452`, `BER 0.8056`) —
> the fix makes the comparison real, but doesn't change the outcome, because
> `_script_fallback`'s null-confidence branch (`ta.confidence or 0.0` vs
> `tb.confidence or 0.0`) makes A win literally every disagreement when
> Qwen3-ASR reports `None`, regardless of candidate size.
>
> **The actual §4.3 null-confidence tiebreak was then tested for real** (an
> env-var-gated probe branch: prefer B when A's own confidence drops below a
> threshold) — at threshold 0.75: `cer_thai` **regressed** 0.1415→0.1614
> (fails the gate) for a marginal `wer_latin`/BER gain. Rejected and
> reverted — `reconcile.py` is byte-identical to before this pass. The
> instrumented disagreement log explains why: the one flip this threshold
> causes has Qwen3-ASR **transliterating** an English loanword ("Jazz",
> "Symbolic") into Thai script rather than preserving it — a real,
> observed case of Engine A's lower confidence correlating with
> *code-switch content A still gets right*, not with A being wrong. This is
> now a documented model-quality finding (§9), not an open reconciler
> question — Qwen3-ASR does not clearly outperform Engine A on code-switch
> content on this corpus, contrary to the architectural hypothesis in §4.1.
>
> **What shipped from this pass:** `max_span_s=8.0` (real fix, zero
> regression, kept — needed groundwork for any future reconciler-tiebreak
> probe to mean anything) + 2 new tests. `_script_fallback` unchanged.
> `engine_b: passthrough` unchanged in production config. Full numbers:
> TODO_LEDGER.md "Qwen3-ASR span-granularity fix + null-confidence tiebreak
> investigated and REJECTED" (2026-08-05). **Next real lever, if revisited:
> §3.2's grown gold set** — this verdict rests on one 5-clip corpus and the
> one data point that mattered came from a single clip; no further
> reconciler-heuristic tuning without new evidence, matching the discipline
> that already closed DP-cue-split and the LLM reconciler.
>
> <details><summary>Second-pass status block (2026-08-05, superseded above — kept for history)</summary>
>
> **STATUS (2026-08-05, second pass same day): §4.1 adapter BUILT, a wiring
> bug FIXED, and a real (first-ever) probe run — NOT ACTIVATED, but for a
> new and more informative reason than any prior rejection.**
> The RTX 4070 Ti machine used for §4/§5's probes turned out to already have
> the gold-set audio (`transcribe/eval/goldenset/*.mp3`) — the "blocked, no
> audio" note directly below was specific to a different (RTX 3070) machine.
> `qwen-asr==0.0.6` installed cleanly into that machine's project `.venv`
> with no dependency downgrades needed (its `transformers`/`huggingface_hub`
> were already at compatible versions).
>
> **First probe was a false negative, not a verdict.** The adapter (as
> originally built, see the unchanged history below) emitted ONE token per
> file spanning the whole clip at a placeholder `start_ms=0, end_ms=0`,
> deferring real timestamps to the forced-alignment pass. That plan doesn't
> match the pipeline order: `align_hyp.py` (hypothesis-to-hypothesis
> alignment, a pure temporal-window match) runs **before** reconciliation;
> forced alignment runs **after**. A zero-duration token at t=0 can only be
> considered against Engine A tokens in the first ~1.5s of a clip, so on any
> real multi-cue file Engine B was a silent no-op — confirmed by the first
> probe coming back byte-identical to the passthrough baseline on every
> metric to 4 decimals, despite a standalone adapter call proving the model
> itself produces a real, coherent Thai transcript.
>
> **Fixed:** the adapter now runs its own internal VAD (reusing
> `engines.faster_whisper._vad_speech_spans`) and emits one token per real
> speech span with a genuine span-derived timestamp — `timestamps_final`
> flipped `False`→`True`. Verified on `Short1.mp3`: 4 real-timestamped
> tokens instead of one 0–0 blob. Tests updated, suite 335 green.
>
> **Re-probed — first real signal ever from an Engine B candidate on this
> gold set** (vs baseline `eval_run.id=25`): `cer_thai` **unchanged**
> (0.1415, no dilution), `boundary_error_rate` **improved** (0.8169→0.8056),
> `cue_boundary_error_rate` +0.0027 (inside tolerance), but `wer_latin`
> **flat** (1.0452, no movement at all). `passed=True`, no regression — but
> this doesn't clear the activation bar below, which needs BOTH BER and
> `wer_latin` to improve.
>
> **Why `wer_latin` didn't move (diagnosed, not chased further this
> session):** `reconcile._script_fallback` routes on Engine A's own script
> label and Qwen3-ASR honestly reports `confidence=None` — the exact
> structural bias §4.3 already predicted would recur ("Qwen3-ASR will
> likely report confidence=None too, so this fires immediately"). The BER
> gain likely comes from solo Engine-B slot insertions, not won
> disagreements. **Distinguish this from the four standing rejections in
> §9**: those had real regressions; this has zero regression and a small
> real improvement, just not enough to activate — and it makes §4.3's
> null-confidence tiebreak finally testable against a real Engine B. Full
> numbers: TODO_LEDGER.md "Qwen3-ASR internal VAD chunking fix" (2026-08-05).
>
> **Production config.yaml unchanged**: `engine_b: passthrough`. Everything
> above ran via `--engine-b qwen3_asr --experiment`.
>
> <details><summary>Original (now-superseded) blocked-probe note from earlier the same day</summary>
>
> `transcribe/engines/qwen3_asr.py` exists, is registered (`"qwen3_asr"` in
> `engines/registry.py`), config-wired (`config.yaml`'s `engines.qwen3_asr`
> block, `engine_b` still `passthrough` — not activated), and unit-tested
> (`tests/test_qwen3_asr.py`, 11 tests, model faked — suite 329 green).
> `qwen-asr==0.0.6` was installed for real on this machine (system Python
> 3.13 — no project venv here; this downgraded the shared `transformers`
> 5.9.0→4.57.6 / `huggingface_hub` 1.16.4→0.36.2, no test regression from
> that but worth knowing). Introspecting the real package corrected two
> things vs the model-card example: `transcribe()` takes audio as an
> `(np.ndarray, sample_rate)` tuple directly (no temp-WAV round-trip needed)
> and a `context: str` slot the adapter now uses for `bias_terms` via the
> same GAP-5 `build_prompt` budget-packer every other engine uses.
> `Qwen3ASRModel.from_pretrained("Qwen/Qwen3-ASR-1.7B", ...)` loads for real
> on the RTX 3070 (~4.08GB VRAM, well inside the 8GB ceiling) and a full
> `load()`→`transcribe()`→`unload()` round-trip against synthetic audio
> returned a correctly-shaped `EngineResult` and freed VRAM cleanly.
> Running `harness.py` for real printed "no audio for \<name\>.json,
> skipping" for all 5 gold-set entries on that (RTX 3070) machine — resolved
> on the RTX 4070 Ti machine as described above, which already had the
> audio all along.
>
> </details>
>
> </details>

Every prior candidate was rejected for cause; the ledger's standing conclusions hold (**do not re-probe** SenseVoiceSmall-funasr, typhoon_rt, or plain whisper_multi without new evidence). The two candidates below are genuinely new:

### 4.1 Qwen3-ASR adapter (`engines/qwen3_asr.py`) — the priority candidate
- **Why it's different in kind:** LLM-decoder ASR — the decoder *is* a language model, so intra-sentential Thai↔English switching is a semantic prediction, not an acoustic-only guess. This targets exactly the two dead metrics (`wer_latin` 1.0452, BER 0.8592). Fully open (Apache 2.0), local, 1.7B → fits the 8 GB budget sequentially under the existing load→run→unload discipline.
- Adapter contract notes: `prefers_whole_file` per its long-audio behavior (the official toolkit chunks long audio — mirror that inside the adapter); timestamps via `Qwen3-ForcedAligner-0.6B` **or** return `timestamps_final=False` and let the existing forced-align path do it (start with the latter — smaller diff); `confidence=None` (never fake it); Thai language hint honored.
- Probe ladder, each step `--experiment` gated: (a) Engine B alone behind the reconciler; (b) if BER/`wer_latin` improve but `cer_thai` dilutes (the whisper_multi failure mode — unmatched solo-B slots), consider a **script-scoped merge policy**: B's candidates only enter slots whose audio region the reconciler judges Latin/mixed (this is select-only-compatible — it narrows *which* slots B may win, generates nothing).
- **Stretch (measure before believing):** Qwen3-ASR-1.7B might beat the Whisper fine-tunes as *Engine A* outright. Only entertain after (a) is measured.

### 4.2 Fun-ASR-MLT-Nano-2512 — the cheap decorrelated fallback
Different underlying model from the retired SenseVoiceSmall (the retirement clause is satisfied). Two distinct attractions: **hotword biasing** (the bias index could inject into Engine B, which Whisper-prompt biasing can't reach today) and the **GGUF/CPU runtime** (an Engine B with zero VRAM contention — could even run concurrently with Engine A, though keep sequential first for simplicity). Probe only if 4.1 disappoints or as the third hypothesis later.

### 4.3 LLM reconciler, next round (only after a real Engine B exists)
The wiring, prompt framing, and positional-bias fix are **done — do not revisit**. The open question is model quality. In order: `qwen2.5:7b-instruct` (already named in the code's own docstrings), then few-shot examples + surrounding-token context in the prompt. Also still open from the ledger: `_script_fallback` needs a tiebreak *within* the fallback for null-confidence engines (length/completeness heuristic) — Qwen3-ASR will likely report `confidence=None` too, so this fires immediately.

**On GER (generative correction) and the select-only rule:** the honest 2026 read is that GER gets large WER wins *by generating*, which this system's core guarantee forbids in the reconciler. The compatible shape, if ever wanted, is a **separate, config-gated post-pass** (off by default, experiment-gated like everything else) that may only *re-space/re-segment or pick among engine-attested variants* — never introduce text absent from all engines. Do not build it in this handoff; recorded here so a future session doesn't "discover" GER and bolt it on inside `reconcile.py`.

**Acceptance for Phase 4:** a probe row where BER and `wer_latin` improve **and** `cer_thai` holds within tolerance → activate Engine B in config; otherwise record the rejection with numbers, same discipline as the four previous rejections.

---

## 7. PHASE 5 — Policy debts that silently tax CER forever

> **STATUS (2026-08-05): items 1, 2 DECIDED (documentation-only, both
> STYLE_GUIDE); item 3 already decided in a prior session; item 4 PROBED
> and REJECTED.** Full reasoning in TODO_LEDGER.md ("Housekeeping + policy
> debts pass", 2026-08-05, and "Bias-index debt (Short4 candidates) probed
> and REJECTED", same date). Summary: mai-yamok contraction (item 1) and
> colloquial-vs-formal register (item 2) both resolved to "transcribe as
> spoken on both sides, no canonicalization" — the same principle §2
> already established for number verbalization — recorded in
> `STYLE_GUIDE.md` §3a and §8 respectively. Neither required a
> `normalize.py` change (both match existing default behavior), so neither
> needed a harness run to ship safely. Item 4 (bias-index debts) turned out
> to be unblocked on this machine (RTX 4070 Ti, real gold-set audio present,
> same machine §6's probes ran on) — the four candidates (`พรีเซนต์`, `เนี่ย`,
> `ชิบเป๋ง`, `คบซ้อน`) were manually added to `transcriber.db`'s bias index
> (they had zero correction rows, so the normal occurrence-based promotion
> path could never surface them) and gated as a production run: `cer_thai`
> regressed 0.1415→0.1483 (past the gate), `wer_latin` marginally regressed,
> `BER`/`cue_BER` marginally improved. **`passed=False` — rolled back
> immediately**, bias index restored to empty, `eval_run.id=25` still the
> active baseline. This answers GAP-5's "does prompt biasing measurably help
> at all" with a real *no, not on this corpus* — but honestly, only one of
> the four terms (`เนี่ย`) actually appears in the current 5-clip gold set,
> so this is a real but thin result; re-check once §3.2's grown gold set
> exists rather than trusting it as the final word on prompt biasing.

These are decisions, not code (ledger, 2026-07-30):

1. **Mai-yamok contraction:** Whisper emits `ดีดี`/`ใหม่ใหม่` inconsistently vs `จริงๆ`. STYLE_GUIDE fixes the gold side but nothing contracts the hypothesis side → permanent CER tax. Decide: add hypothesis-side contraction (`XX` → `Xๆ` for the closed class of true reduplications) to `normalize.py` under the same exception-lexicon guard, or accept the tax explicitly in STYLE_GUIDE. Note this is also a **cross-engine alignment risk** for Phase 2/4: Typhoon/Pathumma were trained on Na-Thalang normalization (expansion-flavored), the gold set deliberately diverges (attach, no expansion) — since the harness normalizes both sides identically this can't desync the gate, but it can *understate* a Na-Thalang-trained model's true quality. Re-check the exception lexicon covers what those models emit.
2. **Colloquial-vs-formal:** `คนนึง` vs `คนหนึ่ง` — unstated policy, same class. Decide once, write it into STYLE_GUIDE, enforce in `normalize.py`.
3. **Number verbalization** (Na-Thalang's other half): spoken "สิบ" vs written "10" currently scores as an error in both directions. At minimum document the gold-authoring rule; a verbalization-aware normalizer is optional and only worth it if the gold set shows real hits.
4. ~~**Bias-index debts:** the four candidates from Short4 (`พรีเซนต์`, `เนี่ย`, `ชิบเป๋ง`, `คบซ้อน`) were never added; GAP-5's residual question — does prompt biasing measurably help at all — is answerable once Phase 1.2's gold set exists. Run the harness with and without the bias prompt once and record it.~~ **Done 2026-08-05 — rejected.** Added, gated as a production run, `cer_thai` regressed past the gate; rolled back. See status block above / TODO_LEDGER.md.

---

## 8. PHASE 6 — Housekeeping (small, do opportunistically)

> **STATUS (2026-08-05, first pass): first four items DONE.** Merge marker
> removed from `CLAUDE.md`; `scripts/make_gold.py` deleted
> (`tools/make_gold.py` confirmed as the only referenced copy); the stale-DB
> item turned out to be a non-issue (no `transcribe.db` exists at repo root,
> only `transcriber.db` + an unrelated `memory.db`, both already gitignored);
> Python-version docs were already correct from a prior session, and
> `transcribe/README.md` now has a "Running tests" section with the correct
> venv invocation. Full detail: TODO_LEDGER.md 2026-08-05.
>
> **STATUS (2026-08-05, second pass): checked the three remaining items
> against their stated triggers instead of forcing action.**
> - **DeepFilterNet** — trigger is "chunk-engine activation." Config is
>   still whole-file-only (`engine_a: faster_whisper`, `prefers_whole_file`),
>   so `denoise` never runs in production regardless of whether `df` even
>   imports (confirmed it doesn't: `ModuleNotFoundError: No module named
>   'df'` — `deepfilternet>=0.5.6` is in `requirements.txt` but not
>   installed in this venv). Trigger hasn't fired — correctly left alone,
>   not deleted or patched.
> - **Editor GAP-7** — the "one-tap reason UI" bullet below was **stale**.
>   It was already built: `transcribe/editor/static/index.html` has had the
>   reason-bar (click a token → tag it misheard/spelling/code-switch/
>   name-term/style → persists through `saveCorrections()` to
>   `/jobs/{id}/save`) since commit `9a618f8` (2026-07-15) — before this
>   handoff was even written. Corrected below. The other half, **merged-group
>   corrected-state display**, was checked with the user directly (no spec
>   for it existed anywhere in the repo or git history, and `diff.py`'s data
>   model has no merge/split concept to hang it on) — **user confirmed: drop
>   it, not a real need.** Removed from §8 below.
> - **CutDeck real-Premiere XML import acceptance** — needs an actual
>   Premiere Pro session with real footage to verify frame accuracy at the
>   60-min mark and confirm no offline media. Not executable from this
>   session; still blocked on the user doing that check.

- ~~**`CLAUDE.md` contains a stray merge-conflict marker** (`>>>>>>> d405aac…` above the "Token granularity (5.4)" section) — resolve it; the file is the first thing every session reads.~~ **Done.**
- ~~Two `make_gold.py` copies (`tools/` and `scripts/`) — keep one, re-export or delete the other.~~ **Done — `scripts/make_gold.py` deleted.**
- ~~Both `transcribe.db` and `transcriber.db` sit at repo root; only `transcriber.db` is used — remove or gitignore the stale one.~~ **Non-issue — no `transcribe.db` file exists on this machine.**
- ~~Docs still claim Python 3.13 in places (CLAUDE.md, config comments); the venv is 3.11.9 — fix on next touch. The 1 perpetually-failing `pycrfsuite` test only fails on the wrong (3.13) shell; note the correct invocation in README/CLAUDE.md.~~ **Done — docs were already correct; invocation now documented in `transcribe/README.md`.**
- DeepFilterNet denoise is silently dead (torchaudio 2.x removed `torchaudio.backend`) — irrelevant while the production engine is whole-file; **decide at chunk-engine activation**: pin/patch, or measure denoise-off and delete (INFRA-6 suspected it never helped). **Still not due — re-checked 2026-08-05, trigger hasn't fired.**
- ~~Editor GAP-7 (one-tap reason UI)~~ **already done, 2026-07-15 (`9a618f8`) — this line was stale, corrected 2026-08-05.**
- ~~Merged-group corrected-state display~~ **dropped, 2026-08-05 — asked the user directly.** No spec for this ever existed anywhere in the repo or git history; it was a speculative note from an earlier planning session with no concept to hang it on (`diff.py`'s data model is strictly one-token-in → one-token-out by index, no merge/split at all). User confirmed: drop it, not a real need.
- CutDeck: the real-Premiere XML import acceptance is still the gate blocking Phases 5–6 of that track and `segment` mode promotion — unchanged, tracked in TODO_LEDGER, out of scope here.

---

## 9. What NOT to do (standing rejections — evidence on file)

| Idea | Status | Where the evidence lives |
|---|---|---|
| SenseVoiceSmall (`funasr`) for Thai | **Structurally incapable** (5-language model, misdetects Thai as Cantonese) | TODO_LEDGER 2026-07-16, `engines/funasr.py` docstring |
| `typhoon_rt` (FastConformer) as Engine B | Rejected — regresses CER & WER_latin | TODO_LEDGER 2026-07-16 |
| `typhoon-whisper-turbo` as Engine A | Rejected — CER 0.1336 vs 0.1069 | docs/IMPLEMENT_IMPROVEMENTS.md Phase 1 |
| `whisper_multi` + qwen2.5:3b tiebreak | Rejected — dilution + model too weak; wiring/bias fixes done, don't redo | TODO_LEDGER 2026-07-16 (four probes) |
| Re-tuning `cue_space_min_*` knobs | Measured flat — the greedy fill is the blocker (§5) | TODO_LEDGER 2026-07-30 |
| Cloud ASR engines | Local-only design; open weights currently *lead* on Thai anyway (§2 table) | arXiv 2601.13044 Table 6 |
| Generation inside the reconciler (GER) | Violates the core anti-hallucination guarantee; constrained shape only, later | §6 note |
| `_script_fallback` null-confidence tiebreak favoring Qwen3-ASR on low-A-confidence | Rejected — regresses `cer_thai` 0.1415→0.1614 for marginal `wer_latin`/BER gain; A's low confidence correlates with hard-but-correct code-switch content, not with A being wrong | TODO_LEDGER 2026-08-05 "Qwen3-ASR span-granularity fix" |
| Qwen3-ASR as a code-switch improvement over Engine A (on this corpus) | Not supported by evidence — observed transliterating English loanwords into Thai script rather than preserving them | TODO_LEDGER 2026-08-05, same entry |
| GAP-5 bias-prompt injection for the 4 Short4 terms (`พรีเซนต์`, `เนี่ย`, `ชิบเป๋ง`, `คบซ้อน`) | Rejected — `cer_thai` regressed 0.1415→0.1483 past the gate for a marginal BER/cue_BER gain; only 1 of 4 terms even appears in the current gold corpus, so treat as thin evidence, not a verdict on biasing generally | TODO_LEDGER 2026-08-05 "Bias-index debt (Short4 candidates) probed and REJECTED" |

---

## 10. Suggested execution order (one line each)

1. **Metrics v3 + gold-set growth** (§3) — the measurement floor; gold authoring is the schedule-critical human task. **§3.1 DONE 2026-08-04; §3.2 gold-set growth IN PROGRESS as of 2026-08-05 — 8 clips / ~10.4 min, 2 of 3 strata covered, noisy/hard clip still missing. See §3 status block.**
2. **Engine A probes: Typhoon Whisper Large-v3, Pathumma Large-v3** (§4 §2) — biggest expected CER win, near-zero code. **DONE 2026-08-04 — both REJECTED, production config unchanged. See §4 status block for numbers and why the verdict is provisional pending §1's gold-set growth.**
3. **DP cue split** (§5) — the user's real pain, now measurable. **DONE 2026-08-04 — built, tested, probed; NOT ACTIVATED (regresses `cue_boundary_error_rate` 0.3865 vs 0.3590 baseline on the current 5-clip gold set, though it beats greedy on cue-count and switch-matching). See §5 status block / TODO_LEDGER.md for full numbers and the re-probe conditions.**
4. **Qwen3-ASR Engine B adapter + probe ladder** (§6) — the code-switch wall. **Adapter built, a timestamp-wiring bug fixed, a span-granularity bug fixed, and both §4.3 null-confidence tiebreak ideas tested with real harness evidence and rejected 2026-08-05 — NOT ACTIVATED. `wer_latin` stays flat not because of an unexplored reconciler bias but because trusting Qwen3-ASR more costs real `cer_thai` for only a marginal gain, and the model itself was observed transliterating code-switched English into Thai on this corpus. See §6 status block / TODO_LEDGER.md for numbers.**
5. **LLM reconciler round 3 (7B, few-shot)** — only after 4 produces a real second hypothesis. Given §4's finding that Qwen3-ASR itself doesn't clearly beat A on code-switch content here, this is now lower-priority than §3.2's gold-set growth — a bigger/smarter reconciler can't fix a candidate-quality problem.
6. **Policy decisions** (§7) and **housekeeping** (§8) — opportunistic. **§7 fully closed 2026-08-05** (items 1–3 documentation-only, item 4 probed and rejected — see §7 status block).

### Sources (external)
- Typhoon ASR Real-time paper + Thai benchmark table: https://arxiv.org/html/2601.13044v1
- Typhoon ASR release note: https://opentyphoon.ai/blog/en/typhoon-asr-realtime-release
- Qwen3-ASR: https://github.com/QwenLM/Qwen3-ASR · https://huggingface.co/Qwen/Qwen3-ASR-1.7B
- Pathumma-whisper-th-large-v3: https://huggingface.co/nectec/Pathumma-whisper-th-large-v3
- Fun-ASR (MLT-Nano-2512, 31 langs incl. Thai, GGUF): https://github.com/FunAudioLLM/Fun-ASR · https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512
- GER/GenSEC background: https://arxiv.org/pdf/2310.06434 (Whispering-LLaMA) · https://arxiv.org/pdf/2501.12979 (FlanEC) · https://arxiv.org/pdf/2508.07285 (survey)
