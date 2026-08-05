# HANDOFF — B-transcriber: One Great Engine

**For:** Claude Code, working in the B-transcriber repo
**Hardware floor:** RTX 3070, 8 GB VRAM (design/gate target — actual sessions run on multiple machines, incl. an RTX 4070 Ti 12 GB). Working venv **Python 3.11.9**. Windows host.
**Prime directive:** unchanged — accuracy first, nothing activates without the eval harness proving it, the reconciler selects and never generates.
**Discipline:** read `CLAUDE.md`, `SYSTEM_SPEC.md`, `TODO_LEDGER.md`, `docs/HANDOFF_CEILING_BREAK.md` before touching anything. Every probe runs `--experiment`. Every phase ends suite-green with new acceptance tests. Update `TODO_LEDGER.md` as phases complete.
**Date of audit:** 2026-08-05. External evidence current as of the same date.

---

## 0. The mandate: stop chasing a second engine

**User decision (2026-08-05): this project focuses on ONE great engine.** The two-engine architecture stays in the codebase (the Engine Contract and reconciler are sound plumbing and `engine_b: passthrough` costs nothing), but **no further effort goes into finding, probing, or tuning an Engine B.** The evidence already supports this pivot independently of preference:

- Production has *always* effectively been single-engine (`engine_b: passthrough`).
- Every Engine-B candidate ever probed was rejected for cause: funasr (structurally non-Thai), typhoon_rt (regresses CER+WER), whisper_multi (dilution), Qwen3-ASR (zero regression but zero `wer_latin` gain, observed transliterating English loanwords into Thai script). Five candidates, zero activations.
- Both LLM-reconciler rounds and both null-confidence tiebreak ideas were tested with real instrumentation and rejected.
- The 2× runtime cost of a real Engine B was never once earned.

Everything below is about making the single engine — currently `faster_whisper` on `biodatlab/whisper-th-medium-combined` (CT2) — as good as it can get, and about the measurement/data infrastructure that a single-engine strategy actually depends on.

**What "focus on one engine" does NOT mean:** deleting `align_hyp.py`/`reconcile.py`/the contract. §6 covers what to do with that machinery (short answer: keep, repurpose the reconciler for A's own N-best; do not rip out).

---

## 1. Where the ceiling is (measured, eval_run.id=46, metrics v3, 8 clips / ~10.4 min)

| Signal | Baseline | Honest read |
|---|---|---|
| `cer_thai` | **0.1751** | ~1 in 6 Thai characters wrong on the (now honestly harder) corpus. Clean pure-Thai shorts run ~0.04. |
| `wer_latin` | **0.8291** | The English/Latin stream is still mostly wrong. Improved from 1.0452 only because the corpus finally *contains* scoreable Latin content, not because the engine improved. |
| `boundary_error_rate` | **0.5324** | 83/217 Thai↔English switch points matched. The engine misses ~2 of 3 code-switches. |
| `cue_boundary_error_rate` | **0.3904** | Cue-boundary F1 ≈ 61% vs the user's hand recuts — this is the user's real daily pain (Premiere recut loop). |

Four walls, in impact order for a single-engine strategy:

1. **Code-switching** (`wer_latin` 0.83, BER 0.53) — the biggest measured accuracy gap, and now finally measurable after the gold-set growth.
2. **The model has never seen this domain** — every external SOTA checkpoint probed *lost* to th-medium on this corpus. That pattern (3 published-SOTA models, 3 losses) is itself the finding: this corpus's creator-style speech + normalization policy diverges from every public training/eval distribution. Nobody ships a model trained on *your* data — except you (§4).
3. **Segmentation/cue quality** (cue_BER 0.39) — measured, gated, DP split built but not yet winning.
4. **Statistical resolution** — every rejection to date was decided by margins (0.005–0.03 abs) that the handoffs themselves flagged as smaller than run-to-run drift on a small corpus. The gate cannot currently tell a 1% real win from noise (§3).

---

## 2. Flaws vs comparable systems (what others do that this repo doesn't)

Compared against production-grade single-engine pipelines (WhisperX-style OSS stacks, commercial ASR like Gladia/AssemblyAI/ElevenLabs Scribe, and the 2026 Thai stacks: Typhoon, Pathumma):

| # | Flaw | Who does it better | Severity |
|---|---|---|---|
| F1 | **The flywheel never touches the model.** 348 correction rows + every hand-recut Premiere SRT the user produces = a continuous stream of in-domain supervised data, and 100% of it feeds only `initial_prompt` biasing — which was probed 2026-08-05 and **regressed** the gate. Commercial systems' single biggest lever is exactly this data: fine-tuning/adaptation on user corrections. This repo collects the gold and throws it at the weakest possible mechanism. | Every commercial ASR vendor with custom-model training; the entire LoRA-adaptation literature | **Highest** |
| F2 | **One blunt biasing channel.** `initial_prompt` is a prompt-space hack (and measured harmful here). faster-whisper ≥1.0 has a separate `hotwords` parameter; CTC/transducer stacks have real shallow-fusion contextual biasing; Fun-ASR has native hotword biasing. Never probed. | Commercial keyword boosting; Fun-ASR | Medium |
| F3 | **No statistical machinery in the gate.** Single-run point estimates, no bootstrap CI, no per-clip variance reporting. The harness rejects on 0.005-abs deltas while its own docs admit run-to-run drift of the same magnitude. Open ASR Leaderboard-class evals report CIs for exactly this reason. | Open ASR Leaderboard (arXiv 2510.06961), any published eval | **High** (it silently decides every probe) |
| F4 | **No RTF/latency in the eval row.** The speed handoff set a ≥3× realtime target; nothing records it per run, so an accuracy win that halves speed would pass the gate silently. | Every serious eval harness | Low-medium |
| F5 | **No hallucination/insertion-specific signal.** CER blends substitutions/insertions/deletions; Whisper's characteristic failure (hallucinated fluent text on noise/music) is invisible as a category. The gold set also still lacks its noisy stratum, so the failure mode is doubly unmeasured. | CrisperWhisper eval methodology; Open ASR Leaderboard | Medium |
| F6 | **Timestamp quality is inherited, not engineered.** Cue boundaries come from Whisper's cross-attention word timings as-is. CrisperWhisper showed (Interspeech 2024) that tokenizer adjustment + attention-loss retraining substantially sharpens word timestamps; Qwen ships a dedicated `Qwen3-ForcedAligner-0.6B`. This repo's cue pain (F≈61%) sits directly on top of unrefined timings. | CrisperWhisper, Qwen3-ForcedAligner | Medium |
| F7 | **Dead second-engine machinery taxes comprehension.** ~5 engine adapters, align_hyp, reconciler LLM hooks — all maintained for a passthrough. Not a correctness bug, but every session pays the reading cost. §6 resolves this without deletion. | Single-engine stacks (WhisperX) are simply smaller | Low |
| F8 | **No diarization/speaker features** — reserved for v2 (`speaker_id` nullable), fine to defer, but it is a real gap vs commercial output. | Commercial vendors | Deferred, by design |

---

## 3. PHASE A — Make the gate trustworthy at 1% margins (prereq for everything)

Every past rejection is provisional because the gate can't resolve fine margins. Fix the instrument before spending GPU-days on the levers.

1. **Bootstrap confidence intervals in the harness.** Resample clips (and/or cue-level units) with replacement, ~1000 draws, report 95% CI for each gated metric alongside the point estimate. Store in `eval_run` (new columns, idempotent `_migrate`, bump nothing — CIs are descriptive). The gate rule becomes: *regression = point estimate past tolerance AND CI excludes zero-delta*; a delta inside the CI is recorded as "unresolved, needs more data" instead of a hard verdict. This retroactively explains — and would have softened — most of the §9 rejections.
2. **Record RTF per eval_run** (wall-clock decode time ÷ audio duration). Descriptive, not gated, until a speed floor is chosen.
3. **Finish the gold set** (carry-over from CEILING_BREAK §3.2): the noisy/hard stratum is still missing. Target 15+ min total. Every phase below re-probes against this.
4. **Hold-out discipline, written down now before Phase C makes it urgent:** the gold set is a TEST set. The moment fine-tuning starts (§4), no clip in `eval/goldenset/` — nor any clip from the same source video — may enter training data. Add a `SOURCES.md` in the goldenset dir listing source videos, and make the fine-tune tooling refuse clips whose source matches. Contamination here would invalidate the entire gate silently.

**Acceptance:** harness prints CI per metric; `eval_run` stores them + RTF; a re-run of the id=46 baseline reproduces within CI; goldenset `SOURCES.md` exists.

---

## 4. PHASE B — Re-run the engine bake-off on the grown corpus (cheap, do before fine-tuning)

All prior Engine-A verdicts were reached on the old 5-clip corpus with near-inert `wer_latin`/BER. The corpus changed materially (id=46: switches 104→217, `wer_latin` finally live). The candidates are already on disk — this phase is YAML edits + harness runs.

1. **Typhoon Whisper Large-v3** (`models/typhoon-whisper-large-v3-ct2`, on disk) — rejected on 5 clips; its BER=1.0 total-failure result deserves one re-check now that BER means something.
2. **Pathumma Whisper Large-v3** (`models/pathumma-whisper-th-large-v3-ct2`, on disk) — was within CER tolerance already; lost only on BER/cue_BER, both of which the corpus change redefined.
3. **th-medium baseline** (current production) — the incumbent.
4. **Qwen3-ASR-1.7B as Engine A** (the CEILING_BREAK §4.1 "stretch" idea, never actually run as A): adapter exists, VAD-chunked, `max_span_s` capped. Its known transliteration flaw is real but was observed on 2 tokens of one clip — as a *primary* engine on the grown corpus it gets a fair single-engine trial. Note: per-word timestamps would need the forced-align path (`timestamps_final` currently True with span-level cues only — check cue metrics carefully; this may disqualify it on cue_BER alone, which is itself a valid verdict).
5. **Judge on all gated signals + CI** (Phase A). The winner becomes the fine-tuning base checkpoint for Phase C — that's the real prize here: pick the best *starting point* before investing training compute.

**Expected outcome, stated honestly:** th-medium may still win — its two prior wins weren't flukes, they reflect domain match. That's fine; it just means Phase C fine-tunes th-medium. If a large-v3 fine-tune wins now that code-switch is measurable, even better: large-v3's multilingual base is a stronger code-switch substrate.

**Acceptance:** one table in TODO_LEDGER with all 4 candidates × all gated metrics × CI, and a named fine-tuning base checkpoint.

---

## 5. PHASE C — Fine-tune your own engine (the ceiling-breaker, F1)

**This is the single biggest untried lever in the repo, and the only one that attacks the root cause** (§1 wall 2: no public model was trained on this domain). The 2026 evidence base is mature:

- LoRA on Whisper: train only adapters on `q_proj, v_proj, out_proj, fc1, fc2`, freeze the first ~3 encoder layers, AdamW @ ~1e-4, ~5% trainable params — repeatedly shown to beat full fine-tuning on stability for low-resource adaptation (Springer/MDPI/arXiv 2604.06507 lineage).
- **Data threshold: gains become reliably large past ~800 utterances** (arXiv 2604.06507). At phrase-cue granularity (~3–5 s/cue), that is roughly **60–90 minutes of corrected audio** — well within reach of the user's existing Premiere recut loop output, which produces exactly this artifact (hand-corrected SRT + source audio) as a *byproduct of work they already do*.
- Pipeline: HF `transformers` + `peft` LoRA → `merge_and_unload()` → `ct2-transformers-converter` → drop-in `model_id` YAML edit. **Zero adapter code changes** — the serving path is untouched; the harness gates the swap like any other engine probe.

Concrete steps:

1. **Build the data engine first** (`tools/make_finetune_set.py`): ingest (audio, hand-recut SRT) pairs — the same `srt_io.parse_srt` path make_gold uses — slice audio to cue spans, emit an HF dataset. Enforce Phase A.4's contamination rule mechanically. Include the 348 `correction` rows' corrected text where the audio span is recoverable from `engine_result`/`token` tables.
2. **Inventory what the user already has.** The Premiere recut loop memory says every shipped short gets a hand-recut SRT. Ask the user to point at the folder; each one is training data. Count minutes; don't start training under ~45 min of material — collect instead (the loop generates it weekly anyway).
3. **Train LoRA on the Phase B winner.** 8 GB is enough for medium at fp16 + LoRA; large-v3 LoRA wants the 12 GB box or gradient-checkpointing/8-bit — both machines exist. SpecAugment on, 3–5 epochs, early-stop on a *dev split of the training pool* (never the gold set).
4. **Code-switch augmentation (the F-wall killer), second iteration:** the 2026 Singapore result (arXiv 2506.14177) shows code-switch ASR can be trained largely on **synthetic** code-switch speech — generate Thai/English mixed sentences (the user's own domains: finance/DCA/AMD, music/orchestra, tech), TTS them (Thai TTS is now good — JaiTTS/ThonburianTTS lineage), and mix into the LoRA data. This is the directly-supported 2026 method for exactly this repo's `wer_latin 0.83` wall — no real second engine required.
5. **Gate it** like everything else: harness + CI vs id=46-lineage baseline. Then **make it a loop**: re-train quarterly (or per N new recut SRTs) — this is what the flywheel was always supposed to become; `stale_engine_weight` already anticipates engine turnover.

**Acceptance:** a merged+CT2 fine-tuned checkpoint beats baseline on `cer_thai` AND `wer_latin` with CIs excluding zero, no cue-metric regression → becomes production `model_id`. Record the training-data manifest hash in the ledger so the run is reproducible.

---

## 6. PHASE D — Repurpose the reconciler: N-best self-ensemble (select-only, zero VRAM cost)

The two-engine machinery's one honest single-engine use: **Engine A disagreeing with itself.**

- faster-whisper exposes beam candidates / can be run at a second temperature or with `best_of` sampling in one model residency — no second load, no VRAM sequencing, ~1.3–2× decode cost instead of 2× model cost.
- Feed hypothesis 1 and hypothesis 2 through the *existing* `align_hyp → reconcile` path as pseudo-A/B. The select-only assertion, script fallback, confidence tiebreak all apply unchanged — and unlike every real Engine B tried, both hypotheses come from a model that (a) supports Thai, (b) reports real confidences (so `_script_fallback`'s confidence branch actually functions for the first time), (c) shares normalization behavior.
- The GER literature (Whispering-LLaMA, FlanEC, ProGRes, the 2508.07285 survey) gets its wins from N-best lists — this is the constrained, non-generative slice of that idea this repo's anti-hallucination rule permits. The full generative variant stays banned in the reconciler (CEILING_BREAK §6 note stands).

Probe ladder (`--experiment` each): (a) same params, temperature 0 vs 0.2; (b) beam-5 top-1 vs top-2; (c) only then consider the Ollama tiebreak round 3 (7B, few-shot) — it finally has same-scale, same-model candidates to judge.

**Acceptance:** any variant that improves `wer_latin` or BER with `cer_thai` held (CI-resolved) → activate as production config (it's just decode params + existing wiring). Otherwise record and close the reconciler track entirely.

---

## 7. PHASE E — Cue/timestamp quality (the user's daily pain)

1. **Re-probe the DP cue split** against the grown corpus (due per ledger — the 0.0275 rejection margin was sub-noise). With Phase A's CIs, this becomes decidable. If it wins, flip `cue_split_algorithm: dp` and delete greedy per the original plan; if it loses with CI resolution, close the track.
2. **Timestamp refinement pass (new, optional):** probe `Qwen3-ForcedAligner-0.6B` as a post-pass that re-times cue boundaries (not text) — it's small (~0.6B, trivial VRAM sequentially), and cue_BER is the metric it would move. Select-only-safe by construction (touches timestamps, never text). Only if (1) leaves cue_BER as the worst wall.
3. **CrisperWhisper is evidence, not a candidate** (German/English verbatim focus, no Thai) — but its result (tokenizer + attention-loss → crisp timestamps) is the argument for why Phase C's fine-tune should keep `word_timestamps=True` evaluation in the loop: fine-tuning can *move* timestamp quality, so cue_BER must stay gated during Phase C.

---

## 8. Housekeeping specific to the single-engine pivot

- **Do not delete** `engines/` adapters, `align_hyp.py`, `reconcile.py` — Phase D reuses the pipeline; rejected adapters are cheap documentation of what was tried (their docstrings carry the evidence).
- **Do mark** `funasr`, `typhoon_rt`, `whisper_multi`, `qwen3_asr` (as Engine B) as closed in any doc that still lists them as "candidates" once Phase B's re-probe lands. CLAUDE.md's "Current engines" section should shrink to: Engine A (active), mock, and a one-line pointer to the rejection table.
- DeepFilterNet decision still parks at chunk-engine activation (nothing here changes that); the noisy gold clip (Phase A.3) may *reopen* it — if the noisy clip tanks CER, denoise-before-decode becomes a probeable lever with a real metric for the first time.
- `bias_term` table is empty and prompt biasing is a standing rejection — leave the flywheel biasing code dormant; Phase C's fine-tune loop is its successor as the destination for correction data.

---

## 9. What NOT to do (standing rejections carried forward + new)

| Idea | Status | Evidence |
|---|---|---|
| Any new Engine B candidate hunt | **Closed by mandate (§0)** — five candidates, zero activations | This doc |
| SenseVoiceSmall / typhoon_rt / whisper_multi / turbo | Rejected for cause, unchanged | TODO_LEDGER 2026-07-16, IMPLEMENT_IMPROVEMENTS |
| Qwen3-ASR as Engine **B**, null-confidence tiebreaks, LLM reconciler rounds 1–2 wiring | Rejected/done — do not revisit wiring or prompt framing | TODO_LEDGER 2026-08-05 |
| `initial_prompt` bias injection (GAP-5 terms) | Rejected — regressed `cer_thai` past gate | TODO_LEDGER 2026-08-05 |
| Cloud ASR | Local-only design; open weights lead on Thai anyway | CEILING_BREAK §2 |
| Generation inside the reconciler | Violates core guarantee; constrained N-best selection (§6/Phase D) is the only permitted shape | CEILING_BREAK §6 |
| Re-tuning greedy cue knobs / DP weights by hand | Measured flat / sub-noise; only re-probe with Phase A CIs | TODO_LEDGER 2026-07-30, 2026-08-04 |
| Trusting any sub-CI margin as a verdict | New rule from Phase A — record "unresolved" instead | §3 |
| Fine-tuning on anything sharing a source video with the gold set | **Never** — silently invalidates the gate | §3.4 |

---

## 10. Execution order (one line each)

1. **Phase A** — CIs + RTF in the harness, noisy gold clip, contamination rules. *Small code, huge decision-quality payoff; everything else waits on it.*
2. **Phase B** — 4-way Engine A bake-off on the grown corpus (models already on disk). Names the fine-tune base.
3. **Phase C** — the fine-tune data engine + LoRA loop (with synthetic code-switch augmentation as its second iteration). *The ceiling-breaker; schedule-critical human input is pointing at the recut-SRT archive.*
4. **Phase D** — N-best self-ensemble through the existing reconciler. *Cheap probe, first honest use of the two-engine plumbing.*
5. **Phase E** — DP re-probe + optional forced-aligner post-pass, once A–C settle the accuracy walls.
6. **§8 housekeeping** — opportunistic, after Phase B's verdicts land.

### Sources (external, 2026-08-05)
- LoRA-Whisper best practices + module targeting: https://www.emergentmind.com/topics/lora-finetuned-whisper · https://link.springer.com/article/10.1007/s11042-026-21336-0
- ~800-utterance data threshold, Whisper low-resource fine-tune strategy: https://arxiv.org/pdf/2604.06507
- Synthetic code-switch training (no real CS data needed): https://arxiv.org/html/2506.14177
- Code-switch ASR systematic review: https://arxiv.org/pdf/2507.07741
- CrisperWhisper (timestamps/hallucination, evidence for F6): https://arxiv.org/abs/2408.16589
- GER / N-best correction literature (Phase D framing): https://arxiv.org/pdf/2409.00217 (ProGRes) · https://arxiv.org/pdf/2508.07285 (survey)
- Open ASR Leaderboard (eval methodology, F3): https://arxiv.org/pdf/2510.06961
- Thai landscape table (carried from prior handoff): https://arxiv.org/html/2601.13044v1
