# Thai-English Code-Switch Transcription System — Build Plan (v1)

This document is a build specification for Claude Code. It defines a batch
transcription system optimized for Thai-first, English-seamless code-switching
content, plus a correction-capture web editor and a self-improving flywheel.

Read this whole document before writing any code. Build phase by phase. Do not
start a phase until the previous phase meets its acceptance criteria.

---

## 0. Core principles (these override convenience)

1. **The ASR model is a plugin, not a foundation.** Every model is reached only
   through the Engine Contract (Phase 2). No component except an engine adapter
   may import or reference a specific model. If you find yourself writing
   model-specific logic outside an adapter, stop — it belongs in the adapter.

2. **Durable vs disposable.** Durable (invest here): the schema, the engine
   contract, normalization, the eval harness, the flywheel data. Disposable
   (keep thin, never optimize): the models, alignment, VAD. Do not hand-tune
   the disposable layer.

3. **The reconciler SELECTS, it never GENERATES.** It chooses between
   candidate words produced by engines. It is forbidden from producing text
   that no engine proposed. This is a hard rule — it prevents fluent
   hallucination. Enforce it in code, not just prompt.

4. **Every change is gated by the eval harness.** Engine swaps and flywheel
   updates must re-run the frozen eval set and are rejected on WER regression.

5. **Hardware ceiling: RTX 3070, 8GB VRAM.** Never assume two models fit in
   VRAM simultaneously. Models load → run → unload sequentially. Verify VRAM
   is freed between stages (`torch.cuda.empty_cache()` and explicit `del`).

---

## 1. System overview

Pipeline (batch, offline):

```
audio file
  → [Phase 3] Ingestion: denoise + VAD → speech chunks
  → [Phase 4] Engine A (Thai specialist)  ─┐
  → [Phase 4] Engine B (code-switch model) ─┤ run sequentially, not parallel
  → [Phase 5] Hypothesis alignment (align A to B)
  → [Phase 6] Reconciler (select-only)     → merged token stream
  → [Phase 7] Normalization (script hygiene + Thai cleanup)
  → [Phase 8] Forced alignment → final token timestamps
  → output: transcript in DB + SRT/VTT export
  → [Phase 9] Web editor: human corrects → diff → flywheel
  → [Phase 10] Flywheel: corrections feed bias index + regression gate
```

Tech stack: Python 3.11, SQLite, FastAPI (editor backend), plain HTML/JS or a
light framework (editor frontend). PyTorch with CUDA. No cloud APIs — fully
local. Keep dependencies minimal.

---

## 2. Repository layout

```
transcribe/
  contracts.py        # Engine Contract dataclasses — the durable interface
  db/
    schema.sql        # single source of truth for the schema
    store.py          # all DB access goes through here
  engines/
    base.py           # abstract Engine; load(), transcribe(), unload()
    whisper_thai.py    # adapter — Engine A
    funasr.py          # adapter — Engine B  (final pick set in Phase 1)
    registry.py       # name → adapter; config-driven, no hardcoded choice
  pipeline/
    ingest.py         # Phase 3
    align_hyp.py       # Phase 5  hypothesis-to-hypothesis alignment
    reconcile.py       # Phase 6
    normalize.py       # Phase 7
    align_force.py     # Phase 8
    run.py            # orchestrates the full batch pipeline
  eval/
    harness.py        # runs any config over the frozen set, reports metrics
    metrics.py        # WER + code-switch boundary error rate
    goldenset/        # frozen audio + ground-truth transcripts
  editor/
    server.py         # FastAPI
    static/           # frontend
  flywheel/
    diff.py           # raw ASR vs human-corrected → correction pairs
    biasindex.py      # typed knowledge base; produces per-job bias lists
  config.yaml         # engine choices, thresholds, paths — all tunables
  README.md
```

---

## 3. The data layer — SQLite, one schema (`db/schema.sql`)

One database, shared by pipeline, editor, eval, and flywheel. Build this FIRST.

Tables:

- **`media`** — one row per audio file. `id, path, duration_ms, sha256,
  created_at`.
- **`job`** — one pipeline run over a media file. `id, media_id,
  engine_a, engine_b, pipeline_version, created_at, status`. Recording the
  engine names per job is mandatory — the flywheel needs it (see Phase 10).
- **`token`** — the unit of transcription. `id, job_id, idx, text,
  start_ms, end_ms, script (thai|latin|other|mixed), confidence,
  source_engine (a|b|both|reconciler), speaker_id`.
  **`speaker_id` is nullable and unused in v1** — reserved for v2 diarization.
  Do not remove it.
- **`correction`** — flywheel fuel. `id, job_id, token_idx, raw_text,
  corrected_text, error_type, source_engine, created_at`.
  `source_engine` records which engine produced the wrong text, so stale
  corrections can be filtered when a model is swapped.
- **`bias_term`** — typed knowledge base. `id, term, term_type
  (brand|asset|technical|person|loanword), script, added_by (manual|flywheel),
  weight, created_at`.
- **`eval_run`** — regression history. `id, config_hash, wer,
  boundary_error_rate, ran_at, passed`.

`db/store.py` exposes typed functions. No raw SQL anywhere else.

**Acceptance:** schema applies cleanly; `store.py` has create/read for every
table; a smoke test inserts and reads back one row per table.

---

## 4. The Engine Contract (`contracts.py`) — the durable interface

This is the most important file. It is the boundary that makes models
disposable. Define exactly:

```
EngineInput:
    audio_path: str
    bias_terms: list[str]      # from the bias index
    language_hint: str | None  # "th", "en", or None

RecognizedToken:
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None   # None if engine gives none — do NOT fake it
    script: str                # thai | latin | other | mixed

EngineResult:
    tokens: list[RecognizedToken]
    engine_name: str
    raw: dict                  # untouched native output, for debugging
```

`engines/base.py` — abstract `Engine` with `load()`, `transcribe(EngineInput)
-> EngineResult`, `unload()`. Adapters convert native model output into this
contract and nothing else. Pipeline code consumes ONLY this contract.

**Acceptance:** a `MockEngine` returning canned tokens lets the entire
downstream pipeline run with no real model. The pipeline must never import a
real engine directly — only via `registry.py` + config.

---

## 5. Phase 1 — Eval harness + engine bootstrapping (BUILD THIS BEFORE THE PIPELINE)

The harness is durable infrastructure and the tool that picks your engines.

1. **Golden set.** `eval/goldenset/` holds 2–3 hours of audio representative of
   the real content, with hand-verified ground-truth transcripts. The harness
   code is built now; you (the user) supply the audio/transcripts. Provide a
   documented format (audio file + aligned `.json` ground truth).

2. **Code-switch boundary labeling rule** (resolves a known ambiguity — put
   this in `eval/README.md` and follow it consistently):
   - A *boundary* is a transition between a Thai-script word and a Latin-script
     word within one utterance.
   - A loanword written in **Thai script** (คอมพิวเตอร์) is **Thai**, not a
     boundary.
   - A brand/term written in **Latin script** inside Thai speech **is** a
     boundary.
   - Boundary error rate = word error rate computed **only** over words within
     2 positions of a boundary. This is the metric that actually matters;
     plain WER hides code-switch failure.

3. **`metrics.py`** — overall WER + boundary error rate.

4. **`harness.py`** — takes a config (engine A, engine B, thresholds), runs the
   full pipeline over the golden set, writes an `eval_run` row.

5. **Bootstrapping (a real task, not an assumption):** wrap 3–4 candidate
   open-weight models as engines — candidates: a Thai-fine-tuned Whisper
   (Thonburian lineage) for the Thai-specialist slot; FunAudio-ASR and
   Qwen3-ASR for the code-switch slot. **All must be open-weight and fit the
   8GB sequential-load budget.** Run each through the harness. Pick the best
   Thai specialist as Engine A and the best code-switch model as Engine B.
   Record the choice in `config.yaml`. Verify current availability and VRAM
   footprint at build time — the landscape moves; the harness is what makes
   the choice swappable later.

**Acceptance:** harness runs end-to-end on the mock engine and on ≥2 real
candidates; produces WER + boundary error rate; writes `eval_run` rows.

---

## 6. Phase 2 — Ingestion (`pipeline/ingest.py`)

Keep this thin (disposable layer).

- Decode audio to 16kHz mono.
- **Rolling-window** noise profile (RMS + SNR) — not just the first 5 seconds;
  conditions drift across a long video. Per-window, route noisy windows
  through a denoiser (DeepFilterNet).
- VAD (Silero) to produce speech chunks. Start from documented thresholds;
  do not over-tune — this layer is disposable.

**Acceptance:** given a noisy test file, outputs timestamped speech chunks;
denoiser engages only on windows that exceed the noise threshold.

---

## 7. Phase 3 — Dual-engine transcription (`pipeline/run.py`)

- Load Engine A → transcribe all chunks → `EngineResult` → **`unload()` →
  `torch.cuda.empty_cache()`**.
- Load Engine B → same → unload.
- Sequential, never concurrent — 8GB VRAM ceiling.
- Verify VRAM is released between engines (assert/log free memory).

**Acceptance:** both engines run on a real file within VRAM limits; logs
confirm memory freed between stages.

---

## 8. Phase 4 — Hypothesis alignment (`pipeline/align_hyp.py`)

Resolves a known flaw: two engines produce **unaligned** outputs (different
segmentation, timestamps, tokenization). They must be aligned to *each other*
before reconciliation.

- Align the two token sequences (timestamp overlap + text-similarity edit
  distance) into a list of comparison slots. Each slot holds candidate(s) from
  A and/or B.

**Acceptance:** on two deliberately divergent transcripts, produces a sane slot
alignment; identical inputs produce 1:1 slots.

---

## 9. Phase 5 — Reconciler (`pipeline/reconcile.py`) — SELECT ONLY

- For each slot, **choose** A's word, B's word, or (if both agree) the agreed
  word. The reconciler **must not emit text neither engine proposed.** Enforce
  with an assertion: every output token's text must exist in that slot's
  candidate set.
- **Confidence proxy** (resolves a known flaw — raw cross-engine confidences
  are not comparable): the primary signal is **agreement**. If A and B agree →
  finalize, `source_engine = both`, high confidence; skip the LLM entirely.
  This is the cheap path and most tokens take it.
- Only on **disagreement** invoke the local LLM reconciler, given both
  candidates + surrounding agreed context + bias terms, asked to pick the
  index of the better candidate (it returns a choice, never free text).
- LLM is small, 4-bit quantized (3–4B class) or CPU — VRAM budget.
- Default per-script lean as fallback when the LLM is unavailable: Thai-script
  slot → Engine A; Latin-script slot → Engine B.

**Acceptance:** agreeing inputs never call the LLM; disagreements produce a
selection from the candidate set; the no-generation assertion is present and
tested.

---

## 10. Phase 6 — Normalization (`pipeline/normalize.py`)

- **Script-boundary spacing**, with the lookbehind bug fixed:
  ```python
  text = re.sub(r'(?<=[\u0e00-\u0e7f])(?=[a-zA-Z0-9])', ' ', text)
  text = re.sub(r'(?<=[a-zA-Z0-9])(?=[\u0e00-\u0e7f])', ' ', text)
  ```
- **Exception lexicon** — do not split units, model numbers, URLs, COVID-19,
  or mixed-script proper nouns. Lexicon lives in config.
- Thai cleanup via PyThaiNLP: tone/sara order, repeated-char (ๆ), numerals.

**Acceptance:** glued scripts get spaced; exception-lexicon items survive
intact; a regression test covers both.

---

## 11. Phase 7 — Forced alignment (`pipeline/align_force.py`)

- Use a code-switch-capable forced aligner (Qwen3-ForcedAligner-0.6B or
  current equivalent) to set final per-token `start_ms`/`end_ms`. Do not
  hand-roll DTW. Wrap it behind a small interface so it too is swappable.
- Write final tokens to the `token` table; export SRT/VTT.

**Acceptance:** timestamps are monotonic and within audio bounds; SRT opens in
a standard player aligned to speech.

---

## 12. Phase 8 — Web editor (`editor/`) — correction capture only

Scope tightly. This is a correction-capture tool, not a product. No accounts,
no dashboard, no polish.

- FastAPI backend; static frontend.
- Load a job: audio player + transcript with **synced highlighting** of the
  current token during playback.
- **Inline text editing** of tokens.
- On save: diff corrected text against the raw ASR output (`flywheel/diff.py`),
  write `correction` rows. Each correction records `source_engine`.
- Export corrected SRT/VTT.

Out of scope for v1: timestamp editing UI, speaker labels, multi-user.

**Acceptance:** load a real job, play with synced highlight, edit a word, save,
confirm `correction` rows written with correct `source_engine`.

---

## 13. Phase 9 — The flywheel (`flywheel/`)

- **`diff.py`** — raw vs corrected → correction pairs → `correction` table.
- **`biasindex.py`** — turns recurring corrections into `bias_term` rows
  (typed: brand/asset/technical/person/loanword). Produces the per-job
  `bias_terms` list fed into `EngineInput`.
- **Staleness:** when filtering corrections to build bias terms, weight down
  corrections whose `source_engine` no longer matches the active engines —
  old-model mistakes shouldn't bias a new model.
- **Regression gate:** any bias-index update or engine swap auto-runs the eval
  harness; if WER or boundary error rate regresses vs the last passing
  `eval_run`, the change is rejected and rolled back. The flywheel must not be
  able to poison itself.

**Acceptance:** a simulated correction flows into a `bias_term`; an injected
bad correction that worsens eval WER is rejected by the gate.

---

## 14. Build order & global acceptance

Build strictly in this order:

1. DB schema + `store.py`
2. `contracts.py` + `MockEngine`
3. Eval harness + metrics  (Phase 1)
4. Engine bootstrapping — pick A and B
5. Ingestion (Phase 2)
6. Dual-engine run (Phase 3)
7. Hypothesis alignment (Phase 4)
8. Reconciler (Phase 5)
9. Normalization (Phase 6)
10. Forced alignment (Phase 7)
11. Web editor (Phase 8)
12. Flywheel (Phase 9)

**System done when:** a real Thai-English video goes in → accurate transcript
out → editable in the web UI → a correction visibly improves the next run's
bias terms → the regression gate blocks a harmful change. Every model is
reachable only via config + the Engine Contract.

---

## 15. Appendix — v2 streaming tier (do not build now)

The streaming tier reuses this harness; it is not a separate system.

- New streaming engine adapters conforming to the **same Engine Contract**,
  emitting partial + finalized tokens.
- A **stability window** (the tunable latency dial) decides when a partial
  token is committed.
- **Thai word-boundary problem:** run a separate lightweight PyThaiNLP
  re-segmentation stream that may retroactively re-split committed Thai text —
  Thai boundary correction is its own revision channel, independent of token
  revision.
- **Tiered latency:** Tier 1 live (English-dominant), Tier 2 near-live (Thai,
  generous window), Tier 3 = this v1 batch pipeline (archival accuracy, feeds
  the flywheel).
- Normalization, reconciler logic, schema, flywheel, and eval harness are all
  reused unchanged.

Build v1 fully — including the flywheel producing measurable improvement —
before starting v2.
