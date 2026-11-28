# HANDOFF — Thai break-atoms: make illegal cue breaks unrepresentable

**For:** Claude Code, working in the B-transcriber repo
**Hardware floor:** RTX 3070, 8 GB VRAM (design/gate target — actual sessions run on multiple machines). Working venv **Python 3.11.9**. Windows host.
**Prime directive:** unchanged — accuracy first, nothing activates without the eval harness proving it. Atoms change *where cues break*, never *what text they contain*.
**Discipline:** read `CLAUDE.md`, `STYLE_GUIDE.md` §7, `TODO_LEDGER.md`, and this file before touching anything. Every lexicon growth step runs `--experiment` through the harness. Every phase ends suite-green with new acceptance tests.
**Date:** 2026-08-06. Gated metric that judges all of this: `cue_boundary_error_rate` (baseline 0.3904, eval_run id=46, metrics v3).

---

## 0. The incident, and what is already fixed (uncommitted, 2026-08-06)

Observed on real output: the greedy splitter's length/gap-forced break fired
wherever the character budget landed, checked no protection rule, and severed

- `ทะเลาะ | กัน` — `กัน` is a bound reciprocal particle (ทะเลาะกัน = "argue
  with each other"), not a free word; stranded at a cue start it reads as a
  broken sentence.
- `ผู้หญิง | คนนั้น` and `ผู้หญิงคน | นั้น` — classifier + demonstrative
  (`คนนั้น` = "that one") re-specifies the preceding noun; pythainlp
  tokenizes it as `คน` / `นั้น`, two tokens that can't be separated from each
  other *or* from the noun before them.

**Already in the working tree (verify before building on it):** four veto
functions in `transcribe/engines/faster_whisper.py` (`_numeral_break_veto`,
`_mai_yamok_break_veto`, `_reciprocal_particle_break_veto`,
`_classifier_demonstrative_break_veto`), now consulted on **all three** break
paths (greedy space-break, greedy length/gap/sentence-forced break, DP
candidate generation), with regression tests in
`tests/test_faster_whisper_cues.py` and the rules recorded in STYLE_GUIDE §7.
Suite green as of this handoff.

That spot fix is correct but it is a patch, not a design. This handoff is the
design.

## 1. The structural defect the spot fix does NOT remove

Break-legality knowledge currently lives as **veto checks at each break
decision point**. Every path that decides "close the cue here" must remember
to call every veto, with the right lookbehind/lookahead, in the right order:

| Break path | Where | Vetoed today? |
|---|---|---|
| Greedy: Whisper-space break | `_may_break_at_space` | yes |
| Greedy: length / gap / sentence-forced break | main loop of `_group_words_into_cues_greedy` | yes (the incident fix) |
| DP: candidate generation | `_dp_split_segment` | yes |
| Future: CutDeck two-line caption wrapper (STYLE_GUIDE §7 "[code] once implemented") | not built | **will start at zero, guaranteed to repeat the incident** |
| Future: any new cue algorithm (the greedy/dp switch invites a third) | — | same |

This shape *caused* the bug: the space path had vetoes, the length path
didn't, and nothing could notice the asymmetry until the user saw it in
Premiere. Four rules × N paths already needs 12 correctly-wired call sites
with fiddly `prev / next / next_next` plumbing at each. Rule five (there will
be one — see §4's gap list) multiplies again.

**The fix is inversion: stop checking legality at break time; make the
unsplittable unit a single token before any splitter runs.** A splitter that
only ever sees atoms can break anywhere it likes and remain legal by
construction. New splitters inherit Thai correctness for free; new rules are
one lexicon entry, zero new call sites.

## 2. The design: `glue_atoms` — one chokepoint, declarative knowledge

### 2.1 Where it lives

`cutdeck/words.py::timed_tokens()` is already the single shared
implementation of Thai word-timeline reconstruction (both cue splitters and
CutDeck consume it). Add the atoms pass **right next to it** so it is
impossible to get tokens without being offered atoms:

```python
# new module: transcribe/thai/atoms.py  (package transcribe.thai — the home
# for Thai linguistic knowledge; do NOT move normalize.py rules here yet)

def glue_atoms(timed: list[TimedToken],
               lexicon: BreakLexicon) -> list[TimedToken]:
    """Merge pythainlp tokens into break-atoms. Same TimedToken shape
    (text, start_ms, end_ms, confidence, char_pos) — an atom is just a token
    the splitters may not look inside. Text is concatenated verbatim
    (including any interior whitespace pieces), start = first constituent's
    start, end = last's end, confidence = mean of non-None, char_pos = first
    constituent's char_pos."""
```

Splitters call `timed_tokens(...)` then `glue_atoms(...)` and operate on the
result. **Delete every veto call site** (the four functions become glue rules;
keep the functions' docstrings' linguistics in the lexicon's comments).
Whitespace handling: whitespace tokens remain separate atoms *except* when
they sit inside a glued pair (Whisper writes mai yamok as a separate ` ๆ`
piece — the space is absorbed into the atom, exactly matching today's veto
behaviour of refusing to break there).

### 2.2 The lexicon is data, not code

```python
@dataclass(frozen=True)
class BreakLexicon:
    bind_left: frozenset[str]        # token glues to the atom BEFORE it
    bind_right_digit: bool           # digit-final token glues to the token after it
    pair_bind_left: frozenset[tuple[str, str]]
        # (classifier, demonstrative) pairs: glue the two together AND glue
        # the result to the preceding token (the noun being re-specified)
    unsplittable_terms: frozenset[str]
        # multi-token spans that must come out as one atom — seeded from
        # config.yaml normalization.exception_lexicon (§6 brands, COVID-19…)
```

Seed contents = exactly today's four rules, no more (Phase 1 is a port, not a
growth step): `bind_left = {"ๆ", "กัน"}` (`ๆ` matching includes the
leading-space form), `bind_right_digit = True`, `pair_bind_left =
_CLASSIFIERS × _DEMONSTRATIVES` as currently defined, `unsplittable_terms`
from the exception lexicon.

Config: a `thai_atoms:` block in `config.yaml` with `extra_bind_left`,
`extra_pairs`, `disable: [rule-name]` — so the user can grow the lexicon from
observed Premiere pain without a code change, same philosophy as
`normalization.exception_lexicon`. `run.py` forwards it like any per-engine
block. STYLE_GUIDE §7 remains the human-readable policy; the lexicon is its
machine-readable mirror — when they disagree, that's a defect, and each §7
bullet should name the lexicon field that implements it.

### 2.3 Interactions to get right (each is a test)

1. **Sentence boundaries (crfcut) snap outward.** A `boundary_offsets` entry
   falling *inside* an atom's char span moves to the atom's start. A sentence
   "boundary" inside `ผู้หญิงคนนั้น` is crfcut being wrong on ASR output, not
   a licence to split.
2. **Gap-forced breaks respect atoms.** If a silence ≥ `gap_ms` falls between
   two constituents of an atom (rare; Whisper timestamps jitter), the atom
   still doesn't split — an atom is an atom. The gap check runs between
   atoms only.
3. **Counters count atoms' full text.** `target_chars` overshoot by one atom
   is legal and expected (that's what "back off to the nearest legal
   boundary" means); the DP oversize cost already handles it smoothly, the
   greedy path just closes after the atom.
4. **CutDeck word-level rules keep seeing words.** `words_from_pieces` /
   filler excision operate on *words*, not atoms — do not reroute them.
   (Ride-along observation, out of scope here: CutDeck's word-blade cut
   points have the same legality question — a blade between ทะเลาะ and กัน
   cuts audio mid-unit. When Phase-5/6 CutDeck work resumes, offer it
   `glue_atoms` rather than letting it grow its own vetoes.)
5. **Atoms never change text.** Concatenation is verbatim; normalization
   stays in `normalize.py`. Any diff in emitted *text* (not timing/grouping)
   is a bug.

### 2.4 Why over-gluing is the safe failure direction

Every rule here has homograph risk (`กัน` is also a verb "to block", `ที่` is
also a preposition/relativizer). We deliberately resolve ambiguity toward
gluing, context-free, because the costs are asymmetric: an over-glue moves a
cue break a few characters earlier — cosmetic, invisible unless the atom is
huge; an under-glue strands a bound morpheme at a cue edge — the exact defect
the user hand-fixes in Premiere. Context-conditioning (POS) is Phase 4, a
probe, only if the harness shows over-gluing actually costs cue_BER.

---

## 3. PHASE 1 — Build the atoms layer, port the four rules, delete the vetoes

1. `transcribe/thai/atoms.py`: `BreakLexicon`, `default_lexicon(config)`,
   `glue_atoms`. Pure functions, no model imports, no GPU.
2. Rewire `_group_words_into_cues_greedy` and `_group_words_into_cues_dp` to
   consume atoms; remove `_may_break_at_space`'s veto half, the main-loop
   veto block, the DP candidate vetoes, and `_next_real_word_texts` if now
   unused.
3. Tests:
   - Keep every existing test in `tests/test_faster_whisper_cues.py`
     unchanged and green — they are the incident's fixtures.
   - New `tests/test_thai_atoms.py`: glue semantics per rule (incl. the
     space-absorbed ` ๆ` case, digit+unit, pair+preceding-noun, exception-
     lexicon term), timing/confidence/char_pos of merged atoms, §2.3 items
     1–3 and 5.
   - **The property test that makes the inversion real:** for a corpus of
     synthetic piece-lists (include every fixture sentence) × a sweep of
     knob settings (`target_chars` 5..60, both algorithms), assert **no cue
     boundary ever falls strictly inside any atom's char span**. This is the
     test that was impossible to write against scattered vetoes.
4. Gate: run the harness (`--experiment`) vs the id=46 baseline. Expectation
   is cue_BER unchanged-to-slightly-improved (the port adds protection on
   paths that already had it; behaviour deltas should be edge cases). Judge
   by the CI rule (a delta inside the CI = unresolved, not a fail).

**Acceptance:** suite green; property test in place; zero veto call sites
remain in any splitter; harness run recorded.

## 4. PHASE 2 — Grow the lexicon the Thai way (the actual payoff)

Known gaps in today's four rules — each is the *next* incident waiting:

1. **`_DEMONSTRATIVES` is missing the spoken/deictic forms.** Today:
   `นั้น นี้ โน้น` only. Spoken Thai (this corpus is creator speech) uses
   `นี่ นั่น โน่น นู่น นู้น` constantly, and `คนนึง`/`คนหนึ่ง`
   (classifier + "one") is the same atomic shape (STYLE_GUIDE §8 keeps both
   registers verbatim — gluing doesn't rewrite them, it just refuses to
   split them).
2. **`_CLASSIFIERS` has five entries; spoken Thai uses dozens.** Grow toward
   the common set (`เรื่อง แห่ง ลูก ใบ เล่ม คัน หลัง เครื่อง ชิ้น ชุด คู่
   ครั้ง ที รอบ ตัว ที่ อัน คน สิ่ง …`). Consider deriving the list from
   pythainlp's corpus/POS resources instead of hand-curation (Phase 4 probe)
   — but a hand list in config beats an unshipped derivation.
3. **Final/polite particles can start a cue today.** `นะ ครับ ค่ะ คะ สิ เลย
   ล่ะ แหละ หรอก เถอะ จ้ะ อ่ะ มั้ย ไหม เหรอ หรอ ป่ะ` are utterance-final;
   stranded cue-initial they read exactly as broken as `กัน` did. These are
   `bind_left` candidates. Highest homograph risk of the three (e.g. `เลย`
   as "at all" vs the place name / "past"), which is fine under §2.4 — but
   grow in small batches.
4. **Other bound post-verbals:** `เอง`, `ด้วย` (as in ไปด้วย), directional
   `ไป/มา/ขึ้น/ลง` after verbs — genuinely ambiguous, park them for Phase 4
   POS-conditioning rather than gluing context-free.

Discipline: add in batches (one gap number = one batch = one `--experiment`
harness run = one commit). The gold set's hand-recut references are the
user's own cue taste — cue_BER *will* respond if a batch over-glues. Update
STYLE_GUIDE §7 bullets in the same commit as the lexicon entry implementing
them.

**Acceptance per batch:** harness non-regressed by the CI rule; new fixture
test per rule class; STYLE_GUIDE §7 and the lexicon still mirror each other.

## 5. PHASE 3 — Cue-legality lint in the harness (catch the NEXT gap on real output)

The incident was discovered by the user, in Premiere, after export. Give the
harness eyes for this class of defect:

- After scoring, scan every **hypothesis cue** (and, separately, every
  **reference cue** — the gold recuts define taste, so a "violation" that the
  reference also commits means the *lexicon* is wrong, and that contradiction
  gets printed, not hidden): flag any cue whose first atom-relevant token is
  `bind_left` material (particle-initial cue), any digit-final cue, any cue
  ending in a lone classifier whose next cue starts with its demonstrative,
  any exception-lexicon term split across two cues.
- Reuse `BreakLexicon` — the lint and the splitter must share one knowledge
  source or they will drift (same law as `db/store.py` owning SQL).
- Report `cue_legality_violations` (count + per-clip detail in verbose) on
  `eval_run` as a **descriptive** column first — no gate, no
  `METRICS_VERSION` bump. Gate it only after a few runs show it stable at 0
  on the current lexicon (then a regression means a new break path forgot
  atoms — exactly the alarm this handoff exists to install).

**Acceptance:** harness prints the count; baseline run shows 0 with the
Phase-1 lexicon (if it doesn't, the nonzero cases are free bug reports —
triage them before gating anything).

## 6. PHASE 4 — PROBE (optional, evidence-gated): context-conditioned rules

Only if Phase 2's harness runs show over-gluing measurably costs cue_BER, or
gap-4's ambiguous particles stay unprotected and keep appearing in the
user's Premiere fixes:

- `pythainlp.tag.pos_tag` (perceptron) over the reconstructed `full_text` to
  condition rules (`กัน` binds only after a VERB-tagged token; auto-derive
  classifier list from tagged corpora). Unproven on unpunctuated ASR output
  — treat its accuracy claim as (assumed) until probed on this corpus.
- Cost it: POS tagging runs per file on CPU; record RTF delta in the probe.
- This is the same probe-then-decide discipline as every engine bake-off:
  `--experiment`, harness, CI rule, TODO_LEDGER entry with numbers, keep or
  kill.

## 7. What NOT to do

- **Do not add veto function #5 at a call site.** Any new protection rule
  goes in the lexicon. If you find yourself writing `_*_break_veto`, stop —
  that's the pre-incident architecture reasserting itself.
- **Do not let atoms touch text content** — no normalization, no register
  canonicalization (STYLE_GUIDE §8), no whitespace cleanup. Grouping only.
- **Do not build the CutDeck two-line wrapper without atoms.** STYLE_GUIDE
  §7 already mandates one segmenter policy; when that feature starts, its
  first line of Thai logic is `glue_atoms`, not a new heuristic.
- **Do not gate the Phase-5 lint before it's proven stable-zero** — a noisy
  gate gets ignored, and this one guards against a failure class, not a
  number.
- **Do not skip the harness because "it's just grouping."** cue_BER is the
  user's daily pain and the only objective judge of Thai cue taste in this
  repo.
