# Transcription Style Guide

The cheapest accuracy gains in Thai ASR are linguistic policy decisions, not GPU
decisions. (Typhoon, Jan 2026: rigorous text normalization matched the impact of
model scaling — a compact model reached Whisper-Large-v3 accuracy at ~45× less
compute, purely by resolving ambiguities like number verbalization and mai yamok.)

This file is the **one place** those decisions are written down. Every decision
here is either enforced deterministically in `transcribe/pipeline/normalize.py`
(marked **[code]**) or is a rule the human follows when authoring the gold set
(marked **[gold]**). The same `normalize()` runs over hypotheses *and* the gold
set during evaluation, so a policy change can never silently desync the two.

If you change a rule here, change `normalize.py` and re-run the eval harness.

---

## 1. Atomic unit

The atomic unit of a transcript is a **character-aligned span**, not a "word".
Thai has no orthographic word boundaries, so word tokenization (newmm vs attacut)
is a *derived view*, computed afterwards, never ground truth. Consequences:

- Thai accuracy is measured as **CER** over the Thai character stream.
- English accuracy is measured as **WER** over Latin word runs.
- Never freeze a gold set around a particular Thai tokenizer's output.

## 2. Numbers — **[code]** + **[gold]**

- **[code]** Thai numerals `๐–๙` are always mapped to Arabic `0–9`. This is
  context-free and lossless, so it is applied unconditionally
  (`normalization.thai_digits`, default on).
- **[gold]** *Verbalization* (สิบ ↔ 10) is **not** normalized automatically — it
  requires semantics and is ambiguous. Gold policy: **transcribe numbers as the
  speaker said them.** "สิบบาท" stays สิบบาท; "10 บาท" (read as a numeral) stays 10.
  Write it the way it was spoken, not the way it is conventionally typed.
- **Divergence from Na-Thalang et al. (2025):** the canonical guideline the
  Typhoon ASR project trains and benchmarks against (see [arXiv:2601.13044](https://arxiv.org/abs/2601.13044))
  normalizes numbers to full spoken-Thai-word form for *scoring* — e.g. an ID
  read digit-by-digit becomes "หนึ่งศูนย์หนึ่งห้าศูนย์", not "10150". We deliberately
  do **not** adopt this: it requires a correct Thai numeral-to-words converter
  (itself context-dependent — Na-Thalang's own examples split "read as a
  quantity" from "read digit-by-digit") and it would force re-authoring every
  gold sample already frozen under the as-spoken policy. **Trigger to
  revisit:** once Engine A is Typhoon-trained (Phase 1), if its raw output
  systematically verbalizes numbers as Thai words even for correct
  transcriptions, `cer_thai` will show a mismatch the gold set didn't earn —
  that harness result, not the paper, decides whether a canonicalizing pass
  gets built.

## 3. Mai yamok ( ๆ ) — **[code]**

- Canonical form: **attached, no preceding space, never doubled** → `เด็กๆ`.
  `normalize()` collapses `เด็ก ๆ` and `เด็กๆๆ` to `เด็กๆ`
  (`normalization.mai_yamok_attach`, default on).
- We do **not** expand `ๆ` into a repeated word (`เด็ก เด็ก`), because expansion
  needs word segmentation and is therefore ambiguous. CER over the character
  stream already credits/penalizes the `ๆ` correctly without expansion.
- **Divergence from Na-Thalang et al. (2025):** the Typhoon canonical guideline
  *does* expand mai yamok contextually — `เก่งๆ` → `เก่ง เก่ง`, `เป็นอย่างๆ` →
  `เป็น อย่าง อย่าง` (the repeated *word*, not the whole phrase) — because it
  scores at word granularity and word-repeat runs need canonical word forms to
  compare. We deliberately keep the attached, unexpanded form instead, for two
  concrete reasons, not just "expansion is hard": (1) §1's atomic unit is the
  character span — CER already treats `ๆ` as a normal character and doesn't
  need word identity to score it correctly; (2) the gold set authored under
  Phase 0 (`transcribe/eval/goldenset/*.json`) already contains real attached
  `ๆ` (`จริงๆ`, `ต่างๆ`, `หลายๆ`, `ใครๆ`) — adopting expansion now means
  hand-editing already-frozen gold data, not just flipping a config flag.
  Implementing a correct expander also requires the word-boundary detection
  §1 explicitly refuses to treat as ground truth (mai yamok always repeats the
  *preceding word*, which Thai's lack of orthographic word breaks makes
  ambiguous to recover deterministically). **Trigger to revisit:** same as
  the number-verbalization divergence above — a Typhoon-trained Engine A
  regressing `cer_thai` specifically on `ๆ`-bearing spans is the signal to
  build a `pythainlp`-based context-aware expander, gated by the harness.

## 4. Loanwords — **[gold]**

A loanword is transcribed **in the script the speaker actually produced.**

- Spoken as Thai phonology, written Thai: `คอมพิวเตอร์`. This is **Thai script**
  and is **not** a code-switch boundary.
- Inserted as an English word (English phonology) inside Thai speech: `computer`.
  This **is** a code-switch boundary and counts toward the switch-point metric.

The test is *how it was pronounced*, not *what the word means*. Pick per token and
write it down; do not let "either is defensible" make the gold set a moving target.

## 5. English casing — **[gold]** / eval-insensitive

- **[gold]** Preserve natural casing in the transcript: proper nouns and brands
  keep their canonical case (`YouTube`, `iPhone`, `API`); ordinary words are
  lowercase unless sentence-initial.
- **Evaluation is case-insensitive** for Latin spans — casing is a presentation
  choice, not an accuracy signal, so it must not move WER. (`metrics.py` lowercases
  Latin runs before scoring.)

## 6. Mixed-script proper nouns / brands — **[code]**

Terms with internal punctuation or digits that must never be split
(`COVID-19`, `GPT-4`) are listed in `normalization.exception_lexicon` in
`config.yaml`. Add new brands there, longest first is handled automatically.

**Spacing policy (decided; was an implicit side effect before):** exception
terms get the *same* Thai↔Latin boundary spacing as any other embedded Latin
word — `iPhone` in `ผมใช้iPhoneอยู่` normalizes to `ผมใช้ iPhone อยู่`, not
`ผมใช้iPhoneอยู่`. A brand name embedded in Thai speech is exactly the
code-switch case §4 describes, and gluing it to the surrounding Thai for no
reason hurt readability with no accuracy benefit (`compute_metrics` extracts
Thai and Latin streams by character class, not by whitespace, so spacing here
was already invisible to every gate — see `transcribe/eval/metrics.py`
`_thai_char_stream`/`_latin_word_stream`). The lexicon's actual job is
narrower than "protect from boundary-spacing": it shields a term's *interior*
characters from the digit-translation, mai-yamok-collapse, and PyThaiNLP
cleanup passes, which run after boundary spacing in `normalize()`. No entry
currently listed contains an internal Thai↔Latin transition, so this only
matters for a future term shaped that way.

## 7. Line breaks in multi-line captions — **[gold]**, **[code]** once implemented

Not yet enforced by any code today — `align_force.py`'s `export_srt`/`export_vtt`
write one line per phrase-cue and never split a cue across display lines, and
CutDeck captions burn-in (`TODO_LEDGER.md`) hasn't been built yet. Recorded here
now so whichever feature ships the first line-wrapper (two-line SRT formatting,
burned captions, etc.) has a policy to implement against, not improvise one.

- **Never break inside a word.** Because Thai has no orthographic word
  boundaries (§1), "word" here is not free — a line-wrapper must call a real
  segmenter (`pythainlp`, already a dependency) to find candidate break points,
  never a naive character-count cutoff.
- **When the character/CPS budget forces a break mid-word, back off to the
  nearest earlier complete-word boundary.** Never truncate or hyphenate to hit
  a length target — a shorter line beats a broken word.
- **Treat `normalization.exception_lexicon` terms (§6) as unsplittable units**
  — the same list that protects `COVID-19`/`GPT-4` from mid-token normalization
  must also block a line-wrapper from breaking inside them.
- **Never separate mai yamok (§3) from the word it repeats** — `เด็กๆ` must
  stay on one line.
- **Never split a number from its unit or classifier** (`100 บาท`, `3 คน`) —
  keep the numeral and its following word together even if that pushes the
  break point earlier.
- **Prefer breaking at a clause or phrase boundary** (before a conjunction like
  แต่/และ/ที่, at a natural pause) over an arbitrary mid-phrase split, and
  prefer a roughly even split across lines over one long line + one short
  orphaned word.
- **Whichever segmenter gets used for this must be the same one `normalize.py`
  already depends on** (not a second, independently-tuned heuristic) — two
  segmentation policies drifting apart is exactly the kind of implicit
  divergence §4/§6 already had to call out once.

---

## Metrics that enforce this guide

See `transcribe/eval/README.md`. In short:

| Signal | Unit | Why |
| --- | --- | --- |
| **CER (Thai)** | character | Thai word boundaries are ambiguous |
| **WER (Latin)** | word, case-insensitive | English words have real boundaries |
| **Switch-point error** | timestamp (±tol) | code-switch is the hardest case; position alone isn't enough |

`wer` (overall, word-level) is reported but is a coarse, tokenizer-sensitive
sanity number — never the gate.
