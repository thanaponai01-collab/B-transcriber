# Engines: status and history

Moved out of CLAUDE.md (2026-09-24) so sessions load less by default; CLAUDE.md keeps a
one-line status per engine and links here. Nothing below was changed in the move.

## Current engines

The working venv is **Python 3.11.9** (not 3.13, despite older comments
elsewhere) — `funasr` and `editdistance` imported fine in it. Engine-B
candidates below are eval-gated, not environment-blocked.

- **Engine A** (`faster_whisper`, active): `biodatlab/whisper-th-medium-combined`
  converted to CTranslate2 (`models/whisper-th-medium-ct2`). Whole-file engine
  (`prefers_whole_file=True`) run through `BatchedInferencePipeline` (VAD-batched
  parallel decode; auto-halves `batch_size` on CUDA OOM). Returns phrase cues with
  final timestamps. Convert the model per the comment in `requirements.txt`.
  `typhoon-whisper-turbo` was tried as a replacement (2026-07) and **reverted**
  — it regressed `cer_thai` to 0.1336 vs 0.1069 on the gold set despite its
  published benchmark; see docs/archive/IMPLEMENT_IMPROVEMENTS.md Phase 1.
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
  judged against. See docs/archive/IMPLEMENT_IMPROVEMENTS.md Phase 2 for history.
- **`funasr`** (`FunAudioLLM/SenseVoiceSmall`): adapter code removed 2026-11-28
  (git history keeps it). **RETIRED as a Thai candidate (2026-07-16): the model
  itself does not support Thai** — its README documents exactly five languages
  (zh/en/yue/ja/ko), and with `language="auto"` it misdetects Thai speech as
  Cantonese, decoding Chinese-script garbage throughout (confirmed via raw
  output inspection: an explicit `<|yue|>` tag, CJK codepoints). Every prior
  harness number for this engine — including the "byte-identical to
  passthrough" result below and the 2026-07-15/16 WER_latin/BER probes — was
  measuring that garbage, not a real Thai accuracy tradeoff. Do not re-probe without a different model.
- **`whisper_multi`**: `openai/whisper-large-v3` — multilingual generalist /
  code-switch slot, genuinely Thai-capable (~100 languages incl. Thai) so this
  is the architecturally correct decorrelated candidate, unlike funasr. A real
  second hypothesis so cross-engine agreement would be a live confidence
  signal if activated. Probed 2026-07-16 — see TODO_LEDGER for the result.
- **`typhoon_rt`**: SCB10X Typhoon ASR Real-time (FastConformer-Transducer,
  ~115M) via NeMo — decorrelated Engine B candidate. Adapter code removed 2026-11-28 (git history keeps it); NeMo
  had installed clean on this 3.11.9 venv (`nemo_toolkit==2.7.3`) —
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

**Name glossaries make the model invent speech (2026-11-22).** A 15-min window of a 1RaceClub
F1 watch-along (`2026-11-21 07-07-37.mp4`, 4790-5690 s) was transcribed three times into scratch
DBs, with a 21-term name glossary (รัสเซล, นอริส, แม็คลาเรน, อัลไพน์, แฮมิลตัน, ...) through
`transcribe(glossary=...)`:

| run | chars | "รัสเซล" | invented names |
|---|---|---|---|
| no glossary | 2,579 | 1 (plus "ราเซล", "รัสเซีย") | 0 |
| `bias_channel: prompt` (production) | 1,854 (−28%) | 14 | 13 × แม็คลาเรน, plus lists like "แม็คลาเรน อัลไพน์ เลอแคลร์" in place of real speech |
| `bias_channel: hotwords` | 1,805 (−30%) | 11 | แฮมิลตัน ×6, "รัสเซล รัสเซล" |

List size does not save it (prompt channel, same window):

| glossary terms | chars vs no glossary | text agreement | invented |
|---|---|---|---|
| 3 (รัสเซล, แม็คลาเรน, นอริส) | −14% | 0.77 | แม็คลาเรน ×17 |
| 5 | −21% | 0.65 | แม็คลาเรน ×25, อัลไพน์ ×12 |
| 10 | −32% | 0.58 | แฮมิลตัน ×17, เลอแคลร์ ×13 |
| 21 | −28% | 0.60 | lists in place of speech |

**The flywheel's learned bias terms use the same prompt channel** (`bias_prompt_budget`), so this
risk grows as corrections accumulate; re-check it on the harness once the bias index has terms.

The real lines lost under the glossary include "แม็กทีหนึ่งครับ ราเซลที่สอง คิมมิ ที่สามนอนดี".
Don't feed name lists to the decoder. Fix names after decoding, with a reviewed substitution list or
corrections through the flywheel, and measure on the gold set. Scripts and outputs are in
`output/timeline_listen/glossary/`.

**English audio needs `language: en` (2026-11-22).** The pipeline hard-coded Thai as the decode
language. On an English F1 broadcast (`2026-11-21 10-55-45.mp4`) the Thai checkpoint then translated
much of the speech into Thai and looped ("รถหัวแข็งของรถหัวแข็ง…"). The same checkpoint told "en"
transcribes it correctly ("They're not having a good weekend, generally. Haas looks very tricky.").
The language is now `config["language"]` (default `th`, so existing caches keep their identity),
carried on `JobPlan.language`; a per-job override is `transcribe(..., language="en")` (MCP
`transcribe(media_path, language)`), cached apart from the Thai transcript.

**`language: auto` (2026-11-22).** The Thai checkpoint's own language detector calls everything Thai
(0.97-0.99 on the English broadcast). Its decode confidence separates the languages instead: on 12
samples of 4 files (1 English, 3 Thai full of English F1 names), the token-weighted mean
log-probability of a beam-1 decode was higher for the right language every time.
`FasterWhisperEngine._pick_language` scores three 30 s samples each way (at 20/50/80% of the file)
and takes the majority. Live: on the English broadcast it chose English (identical to `en`, job 89 vs
87); on the Gillette review it chose Thai (identical to `th`, job 88 vs 84). It is opt-in
(`transcribe(language="auto")`). The default stays `th`, because changing it would change every
cache identity, and the harness gates on `th`.

Held out on 10 files it never saw (2026-11-22; 30 s samples at 20/50/80%, the per-sample vote the
method uses):

| file | language (checked by ear-decode) | votes | per-sample th−en margin |
|---|---|---|---|
| `1.mp4`, `2.mp4` (the synced F1 feeds, 20261121) | English | en 3/3, en 3/3 | −0.48..−1.24, −0.23..−1.24 |
| `2026-11-20 10-55-50.mp4` | English | en 3/3 | −0.16..−1.24 |
| `07-07-36`, `07-07-37-cam`, `10-40-51` (20261121), `20-56-30` (tss), `LAP1 REAR LOCK`, tss news, `21-54-25` (20261108) | Thai | th, every one | +0.05 .. +1.67 |

10 of 10 right. The closest single samples were +0.05 (Thai) and −0.16 (English), and no majority
was close. Note: the 1RaceClub synced F1 feeds are English commentary, so a Thai transcript of them is
invented text.

## Why the `faster_whisper` adapter and `stitch.py` look the way they do

These notes used to be code comments. They moved here in the no-comments pilot (2026-11-24).

**Long spans (`_LONG_SPAN_SAFE_S` 25 s, `_LONG_SPAN_OVERLAP_S` 4 s).** Whisper decodes at most
~30 s at a time. A pause-free run longer than that makes faster-whisper's VAD cut mid-utterance with
no overlap, and several seconds at the cut come out garbled or missing. Spans over 25 s are split
into our own overlapping windows (`transcribe/audio/windows.py`) and stitched back. Tried: 15-20 s
windows recovered one gap inside a dense 25 s window but stuttered at many seams; 25 s / 4 s was
stutter-free with one small gap. The stutter was later traced to `stitch.py`'s IoU gate (below), not
text matching (2026-07-30), so a shorter window is worth re-measuring. Stutter inside one window is
the model's and no seam handling fixes it.

**Early end-of-speech (`_TRUNCATION_TAIL_MS` 1500 ms).** faster-whisper can stop a window early in
two ways. (A) It stretches the last word's timestamp to cover the gap. Recovery used to require that
word to end within 500 ms of the window end; production audio showed real losses with the word
ending 1.5-4 s short, so it now gates on the word's duration and on leftover audio only
(2026-08-10). (B) It just stops after a normal word: a 45.6 s span's first window ended on a 180 ms
word at 17.58 s with the window running to 25 s, dropping ~3.4 s of speech (2026-08-10). Both cases
redecode the tail alone and concatenate, with no overlap splice: Thai has no word boundaries, so a
fixed-offset splice left a stray syllable on both sides however it was tuned. No recursion.
Short trailing pieces hide (A) as well as 0 ms ones do: on gold Short2 at −1.2 dB the first long
window ends on a 6.8 s vowel mark, then a 20 ms and a 0 ms piece, and 4 s of speech is never decoded
(Short3 at +2.3 dB: 5.9 s, then 40 ms and 0 ms). A gain change under 2.5 dB is enough to tip the
decoder into it, which moved the gold `cer_thai` from 0.053 to 0.093. Trailing pieces of 40 ms or
less now count as collapsed (`_COLLAPSED_PIECE_MS`, 2026-11-25). At −12 dB the same stretch hides
behind a longer piece (Short2: then a 1020 ms piece; Short3: then a 540 ms one), so a piece of 3 s or
more among a window's last 6 non-collapsed pieces is the suspect whatever follows it (`_GROSS_STRETCH_MS`). With both
rules, the gold `cer_thai` stays at 0.050–0.062 across −18 to +6 dB (master: 0.053–0.094), and 0 dB
is unchanged at 0.0530. The cut before the redecoded tail prefers a gap before a word start (a piece
with a leading space), falling back to the largest gap only when none is in range: a cut inside a
word (ไม | ่มี) starts the redecode mid-word and the decoder skips that word. On real files this
brought back "ไม่มีเพื่อนครบ", "อื่นไป" and "ว่า" (2026-11-25).

**VAD thresholds.** This engine is whole-file, so `ingest.py`'s VAD never runs on its audio. Left
alone, faster-whisper uses threshold 0.5 / min silence 2000 ms, which clips soft Thai sentence-final
particles (ครับ/ค่ะ). The adapter windows the audio itself with `config.yaml`'s tuned ingest values.

**`temperature` is a no-op on the batched path (faster-whisper 1.2.1).** `generate_segment_batched`
passes `sampling_temperature` but not `sampling_topk`, so CTranslate2 keeps its default top-k of 1:
beam search at `beam_size` > 1 and argmax at 1, never sampling. The
sequential path sets `sampling_topk: 0`. So the adapter's `temperature` argument changes nothing.
Known and proven since 2026-08-05: byte-identical output at 0.0-1.0 and an unchanged harness run
(`config.yaml` `self_ensemble` notes, TODO_LEDGER "Phase D"). The only caller is the self-ensemble,
which is off and closed; the argument stays in case faster-whisper threads `sampling_topk` through.

**The checkpoint must be CTranslate2.** `WhisperModel` can't load a raw HF checkpoint; convert it
once with `ct2-transformers-converter` (see `requirements.txt`).

**Seam dedup in `stitch.py`.** Whisper emits zero-length combining-mark pieces for Thai, so IoU is
always 0 for them; `_coincident` (centre within `_COINCIDENT_MS` 60 ms) catches those duplicates.
Fuzzy (non-identical text) matches need an anchored overlap of `_MIN_FUZZY_OVERLAP` characters,
because plain character overlap scores distinct 2-character words ('มา'/'นา') like real
split-point matches. Text alone still can't tell a duplicate from two real words sharing a morpheme
(หมา/มานะ, ขนม/นมสด, ตลาด/ลาดยาง all false-merged), so one side must also be brief:
`_FUZZY_FRAGMENT_MAX_MS` 80 ms, the measured 20-80 ms range of real sub-word pieces. 150 ms still
false-merged real pairs; 250 ms rested on a misread measurement (an exact-text token's 160 ms). No
real fuzzy duplicate has ever been measured; recalibrate only from the debug log that path emits.
Two real words both under 80 ms can still merge (`test_brief_zero_gap_real_words_can_still_collide`).
A missed stutter is cheaper than a dropped word.

## Why the rest of `transcribe/` looks the way it does

More notes from code comments, moved here in the no-comments pass over `transcribe/` (2026-11-24).
Claims the pass could not check today are marked *unverified*.

**Ingest and VAD.**
- `ingest.py` decodes `.ts`, `.m2ts`, `.mts`, `.vob`, `.mxf` and `.ogv` through PyAV, because
  librosa can't read them. Audio-only containers such as `.m4a` also go through PyAV.
- Ingest's VAD is the `silero-vad` pip package, not faster-whisper's vendored copy, plus a
  minimum-speech floor and an RMS sub-split. Its output is a timeline of speech and silence, not
  decode windows, so it does not sit behind `transcribe/audio/`. Both paths use config's 0.35 / 500 ms.
- The two VADs can disagree, so a confident token over ingest's "silence" is not by itself a
  hallucination (`normalize.drop_tokens_over_silence`).
- Denoising a whole-file run costs about 1.8k file writes per hour and puts the silence timeline out
  of step with the audio, so whole-file engines skip it (`run.py`).
- A whole-file engine (`prefers_whole_file`) runs its own VAD and segmentation; feeding it chunks adds
  per-call overhead and an alignment pass per chunk.

**Decoding.**
- Whisper's `initial_prompt` is capped at about 224 tokens, and Thai is token-expensive, so an
  unbounded bias list would be truncated. `build_prompt` packs the highest-weight terms into a
  200-token budget (`inject._BUDGET_TOKENS`), counted with the engine's own tokenizer, so the cap
  is not hit.
- transformers' `compression_ratio_threshold` works only in long-form (non-chunked) generation, so
  `no_repeat_ngram_size=3` is the repetition guard on `_hf_whisper`'s chunked path. Older
  checkpoints fall back from `return_timestamps="word"` to segment-level chunks.
- Hugging Face pads each batch to its longest item. `whisper-large-v3` needs about 3 GB in fp16.
- Transducers (`typhoon_rt`) give no usable per-token confidence. FunASR's Paraformer returns
  `sentence_info`; SenseVoiceSmall has none, only per-word text with `[start, end]`.
- `qwen3_asr` uses `overlap_s=0.0` because it has no seam-dedup pass; turning on `merge_max_gap_s`
  needs its own harness probe.
- The review thresholds in `service.py` (avg logprob -0.8, no-speech 0.4, compression 2.2) sit just
  inside the adapter's decode thresholds (-1.0 / 0.6 / 2.4). *Unverified:* that those segments are
  retried at decode time.

**Word and cue timing.**
- Whisper word starts land within one 25 fps frame of the onset about half the time, and word ends
  before a pause about one time in ten. CTC starts after a pause can land ~170 ms late, and CTC's
  last letter stops ~168 ms before the syllable fades; `word_align.py`'s sound snapping covers both.
- OBS's noise gate outputs digital silence and closes up to a second after the voice stops. The
  noise floor leaves that digital silence out, so the room noise before the gate closes counts as quiet.
- `LEAD_IN_MS` = 100 was measured on 2026-11-24 on the hand-cut Short1-3.
- pythainlp's crfcut is trained on unpunctuated running text. pythainlp split "เทส" + 45 s of
  silence + "รอบ" as "เท|สร|อบ", and atom glue once merged "ปะ" + 17 s + "ครับ"
  into one cue (`cues/split.py`).
- *Possible bug, open:* `_frame_start_ms` is right only if Premiere does not round frame times down.
  PREMIERE_FACTS says it does, tested at 30 fps only, so at 29.97 fps a cue may land one frame early.

**Flywheel, reconcile and eval.**
- `flywheel/diff.py` diffs Thai by words: a character-level SequenceMatcher smears across a cue
  when a short syllable recurs nearby.
- `align_srt.py`: `_MATCH_PROX_MS` stops two far-apart copies of a word from matching, and
  `_MAX_UNMATCHED_MASS_FRAC` tolerates a title card or outro with no cue.
- `llm_reconcile` labels candidates "Candidate 0/1", never "Engine A/B", because a model can read
  "A" as the primary.
- `reconcile._script_fallback` breaks ties by confidence first: the script rule alone can't separate
  two Thai candidates.
- The regression gate must not re-read `get_last_passing_eval` after the harness writes its row, or
  the new run is compared with itself. SQLite's `datetime('now')` has one-second resolution, so that
  lookup breaks ties by `id`.
- An empty gold set writes no `eval_run` row: a zero baseline would make every later run look like
  a regression. In metrics v4, clip edges count as clear time for orphan cues.
- Exporting the word-alignment checkpoint once saves ~6 s of transformers import per run (0.4 s to
  load the weights), with bit-identical output.
