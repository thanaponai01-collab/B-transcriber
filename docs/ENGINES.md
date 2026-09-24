# Engines: status and history

Moved out of CLAUDE.md (2026-09-24) so sessions load less by default; CLAUDE.md keeps a
one-line status per engine and links here. Nothing below was changed in the move.

## Current engines

The working venv is **Python 3.11.9** (not 3.13, despite older comments
elsewhere) — `funasr` and `editdistance` import fine in it. Engine-B
candidates below are eval-gated, not environment-blocked.

- **Engine A** (`faster_whisper`, active): `biodatlab/whisper-th-medium-combined`
  converted to CTranslate2 (`models/whisper-th-medium-ct2`). Whole-file engine
  (`prefers_whole_file=True`) run through `BatchedInferencePipeline` (VAD-batched
  parallel decode; auto-halves `batch_size` on CUDA OOM). Returns phrase cues with
  final timestamps. Convert the model per the comment in `requirements.txt`.
  `typhoon-whisper-turbo` was tried as a replacement (2026-07) and **reverted**
  — it regressed `cer_thai` to 0.1336 vs 0.1069 on the gold set despite its
  published benchmark; see docs/IMPLEMENT_IMPROVEMENTS.md Phase 1.
- **Engine A alt** (`whisper_thai`): same checkpoint via HF `transformers` — kept
  as a fallback; per-chunk, word-level, much slower on 8 GB VRAM.
- **Engine B active config: `passthrough`** (null) — single-engine fallback,
  Engine A only, no agreement signal. Decorrelated candidates below are wired
  and eval-tested but not yet proven to earn their 2× runtime. **The old
  "switches=0 so nothing can be measured" blocker is gone (2026-07-16):**
  metrics v2 derives switch points character-by-character inside mixed cues,
  and the 5-clip gold set now scores `switches=104` with a live baseline of
  `BER 0.8592` (hyp emits only 38 switch points, 10 matched) — a huge, real
  code-switch gap that Engine-B / LLM-reconciler A/B probes can finally be
  judged against. See docs/IMPLEMENT_IMPROVEMENTS.md Phase 2 for history.
- **`funasr`** (`FunAudioLLM/SenseVoiceSmall`): adapter registered, deps import
  fine on this venv. **RETIRED as a Thai candidate (2026-07-16): the model
  itself does not support Thai** — its README documents exactly five languages
  (zh/en/yue/ja/ko), and with `language="auto"` it misdetects Thai speech as
  Cantonese, decoding Chinese-script garbage throughout (confirmed via raw
  output inspection: an explicit `<|yue|>` tag, CJK codepoints). Every prior
  harness number for this engine — including the "byte-identical to
  passthrough" result below and the 2026-07-15/16 WER_latin/BER probes — was
  measuring that garbage, not a real Thai accuracy tradeoff. See
  `engines/funasr.py`'s docstring. Do not re-probe without a different model.
- **`whisper_multi`**: `openai/whisper-large-v3` — multilingual generalist /
  code-switch slot, genuinely Thai-capable (~100 languages incl. Thai) so this
  is the architecturally correct decorrelated candidate, unlike funasr. A real
  second hypothesis so cross-engine agreement would be a live confidence
  signal if activated. Probed 2026-07-16 — see TODO_LEDGER for the result.
- **`typhoon_rt`**: SCB10X Typhoon ASR Real-time (FastConformer-Transducer,
  ~115M) via NeMo — decorrelated Engine B candidate. Adapter built; NeMo
  installed and verified clean on this 3.11.9 venv (`nemo_toolkit==2.7.3`) —
  the Py3.13 wheel risk originally logged doesn't apply here. **TRIED and
  REJECTED (2026-07-16):** regresses CER_thai and WER_latin vs baseline with
  only a marginal BER edge — worse than every other candidate on accuracy.
  Don't re-try without new evidence.
- **`qwen3_asr`**: `Qwen/Qwen3-ASR-1.7B` — LLM-decoder ASR, the code-switch
  priority candidate (decoder *is* a language model, so code-switching is a
  semantic prediction, not acoustic-only). Adapter built; does its own
  internal VAD segmentation (mirrors `faster_whisper`'s contract for
  `prefers_whole_file=True` engines), capped at `max_span_s: 8.0` (config-
  wired) so its candidates stay comparable in scale to Engine A's phrase
  cues — an initial whole-clip placeholder timestamp made it a silent no-op
  in `align_hyp.py` (fixed 2026-08-05), and an uncapped 25s span made every
  disagreement a short-A-cue-vs-giant-multi-sentence-B-blob mismatch (fixed
  2026-08-05, same day, second pass). Probed with real disagreement
  instrumentation: CER_thai unchanged (no dilution), BER improved, WER_latin
  flat. **Root cause is NOT a fixable reconciler bias** — a null-confidence
  tiebreak favoring B on A's low-confidence cues was tested for real and
  regressed CER_thai (0.1415→0.1614) for a marginal WER_latin/BER gain,
  because Qwen3-ASR was observed **transliterating** code-switched English
  loanwords into Thai script rather than preserving them. **NOT activated —
  this is now a model-quality finding, not an open reconciler question.**
  See TODO_LEDGER for the numbers and the instrumented disagreement log.
- **MockEngine** (`mock`): canned tokens, no GPU required — used for all pipeline tests

**LLM reconciler tiebreak (`transcribe/pipeline/llm_reconcile.py`):** on an
Engine A/B disagreement, `reconcile._pick()` can call an `llm_fn(ta, tb,
bias_terms) -> 0|1` hook instead of falling straight to `_script_fallback`.
`make_llm_fn()` wires this to a **local Ollama** instance (`qwen2.5:3b-instruct`
over stdlib `urllib`, no external API) — an unreachable/unpulled model falls
through to `_script_fallback` automatically. Gated off by default
(`reconciler.llm_enabled: false` in config.yaml). `_script_fallback` no longer
trusts Engine A's own script classification of its own output on every Thai
disagreement — when both engines report a confidence, confidence decides
first and script is only the final tiebreak.

**PROBED and FIXED 2026-07-16 (two rounds) — bias eliminated, but the model
still isn't good enough to activate.** Round 1: with `engine_b:
whisper_multi` (the first candidate producing real disagreements — funasr
never does, see above), `llm_fn` was instrumented directly and picked Engine
A on **11 of 11** real disagreements — including cases where Engine B's text
was visibly longer and more complete. Not credible as judgment; positional
bias. Two causes: (1) `_PROMPT_TEMPLATE` said "disagree on **one word**"
though tokens have been phrase cues since 5.4 — the model was shown two full
sentences while told to expect one word; (2) `whisper_multi` correctly
reports `confidence=None` (never faked), so `_script_fallback`'s
confidence-tiebreak never fires against it either, degrading it to
same-script routing that also always favored A. Harness output was
byte-identical with/without `--llm-enabled`.

**Fixed:** `_PROMPT_TEMPLATE` now describes segment/phrase-level candidates;
`make_llm_fn` randomizes per call which of (ta, tb) lands in prompt slot 0 vs
1 and remaps the answer back (`tests/test_phase3_llm_reconcile.py`, +2,
suite 189 green). Round 2 (re-instrumented, same clip): the lock-in is gone
— 7/11 picked A, 4/11 picked B, no longer deterministic. **But the harness
result got WORSE, not better: `CER_thai 0.3505`** (vs round 1's 0.2323, vs
0.1451 baseline). This is the fix correctly exposing a **model-quality**
problem: Engine A (faster_whisper) is empirically the strongest engine on
this gold set, and round 1's degenerate "always A" was *accidentally* a good
heuristic — once `qwen2.5:3b-instruct` can genuinely pick Engine B and does
so ~36% of the time, its judgment isn't reliable enough to beat that
heuristic. `llm_enabled` stays `false`. Do not revisit the wiring, prompt
framing, or bias fix — they're done and tested. What's still open: try a
larger local model (`qwen2.5:7b-instruct`?) or a richer prompt (few-shot
examples, surrounding-token context) before concluding the LLM-tiebreak
*approach* doesn't work — this result only rules out this specific small
model + minimal-context prompt. See TODO_LEDGER.md for full before/after
numbers.

**Token granularity (5.4):** tokens persisted to the DB are **phrase cues** (not
words). `EngineResult.timestamps_final` (formerly `word_level_timestamps`) signals
that a cue's timestamps are final, so the pipeline skips forced alignment + word
expansion. Word granularity is **re-derived on demand** — faster-whisper keeps its
raw per-word list in `EngineResult.raw["words"]` for CutDeck Phase 5 filler excision.

**Per-engine config (2.3):** construction knobs live under `config["engines"][<name>]`
(model_id, compute_type, beam_size, batch_size, cue thresholds, bias budget). `run.py`
forwards the matching block as kwargs — an engine/model/compute swap is a YAML edit.
