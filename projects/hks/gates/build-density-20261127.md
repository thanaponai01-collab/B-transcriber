# hks-build: too long, or too many rules? (2026-11-27)

**Question:** is the hks-build skill too long? The skill is within the size guide (170 lines, about 7k
tokens; the Agent Skills guide says under 500 lines). What looks wrong is how many rules it has (81) and
how many questions it asks (73), with about a quarter of the rules saying the same thing twice or more.

Evidence and scripts: [data/build-density-20261127/](data/build-density-20261127/). Nothing in the
registry was merged or retired. That is yours to decide (below).

## 1. Failure ledger (measured, `ledger.py` → `ledger.json`)

For each of the 81 active build rules: the corrections it cites, the corrections that repeated one of them
after the rule was added, its gate, and whether you confirmed it.

- **27 rules cite no correction.** 18 of them are the playbook (X45–X62): READ-DO recipes for timeline
  moves, not lessons. The other 9 come from the study (HKS-7, 17), the rule docs (C2, C3, C10, R7, X31)
  or agent notes (X44, X68, M-3).
- **37 rules had their correction repeated after the rule existed.** The worst are the cover and
  tightening rules: R6, R5, X29, X2, C17, X16 (each repeated in 6+ later corrections: K23, K46, K57,
  K58, K64, K66…).
- **18 rules are gated; 44 of 81 are confirmed.**

Limit: "repeated after added" compares dates, and many K rows were filed onto rules after the fact, so
it counts how often a lesson came back, not proof that the rule's text was read and ignored.

## 2. Redundancy (judged by hand, `groups.py`, `proposal.json`)

Ten groups of build rules cite exactly the same corrections. Read one by one, they are the same rule
written several times (mostly once from rules.md, once from principles.md, once as "I did X"). Four
more groups are a rule and its own reason or special case. Proposed canonical rule, and what it
would absorb:

| Canonical | Absorbs | Why |
|---|---|---|
| R5 No jump cuts | C1, C29, X41 | C1 is R5's reason; C29/X41 are its same-scene case (K7a K11 K23 K34 K64) |
| X34 Tighten inside a thought only under a cover | X2 | same lesson, K11 K58; X2 unconfirmed |
| C17 Tighten at speaker changes first | X16 | word for word the same |
| X43 Blur: adjustment layer + mask | X81, X96, X101, X72 | all "Premiere's own tool first, workaround named" (K19 K20 K25) |
| X33 Each piece starts and ends on a thought | HKS-32, C28, X40, X63 | all gate `visible_cuts_in_speech` (K15 K22) |
| X11 No snappy scene changes | C20 | C20 defines the sliver (K7d) |
| C26 A short ends on a held face | X28 | X28 is the 1-min case (K55) |
| X42 J/L on a copy | C30, X95 | three copies (K24) |
| X35 Add a moment whole | X64 | X64 is its failure (K56) |
| X36 Split the cut (J/L) | HKS-33, X65 | reason + failure, gate `same_frame_share` |
| X37 The held picture must be safe | X66 | failure, gate `unsafe_holds` |
| X10 No bug, clock or strip on footage | C3 | C3 is the clock reason |
| C25 Every shot framed on its own | X27 | the square case (K47 K54) |
| R6 Cover = B-roll from the same story | C9, C10 | R6's text already contains both |

25 rules absorbed: 81 → 56. `variants.py` checks that every current rule is still active or superseded
by an active one, and that every correction is still cited (it passes).

**Two contradictions found while reading (not merges; yours to settle):**
- X3 (B-roll one continuous scene, 20–46 s) and X4 (cutaways 8–16 s, "not 2–3 s pops") against X108
  (confirmed 2026-11-26: a cover that hides a cut is short, your median 2.6 s).
- X34 (in studio picture keep the take whole) against X108 (inside every kept passage cut the pauses,
  restarts and fillers, and hide each cut).

## 3. Variants (`variants.py` → `variants/`)

| Variant | What changes | Rules shown | Questions | Characters |
|---|---|---|---|---|
| current | | 81 | 73 | 28,344 |
| a | the 25 absorbed rules superseded | 56 | 52 | 20,609 |
| b | a + every gated rule as one line, no question | 56 | 48 | 18,212 |
| c | b + playbook to PLAYBOOK.md + questions in 4 pause points | 38 (+18 in PLAYBOOK) | 30 | 13,020 (+3,594) |

Pause points in c: before the first cut (5), after the body cut (6), after the covers and holds (9),
after finishing (10).

**Contract found:** `cutdeck/hks_enforce.py` makes the handover require one written answer per active
`do_confirm` rule of every stage: 164 today, 143 after (a). Variant b and c drop questions from gated
`do_confirm` rules and the playbook, which means changing those rules' `kind` (to `code_gate`, or a new
`reference` kind the schema does not have yet). That changes what the handover asks.

## 4. Experiment: does variant c catch more faults at the build do-confirm? (`replay/`)

**Setup:**
- **Draft:** the agent's 20261126 YT v1 as saved at HANDOVER OK (`CutDeck/Drafts/1 YOUTUBE agent v1
  20261126-174119.prproj`), dumped to text with `prproj_reader`. The dump has every clip, its source
  times, scale and effects, and the source words under each piece and cover (`replay/timeline.md`).
- **Subject:** Opus, one shot, no tools. It does the build do-confirm from the skill and lists every
  break.
- **Judge:** a blind Sonnet judge scores 8 faults the draft really has:
  - from your corrections: one insert on every cut (K67), no tightening (K68), no J/L (K69)
  - from the draft memo's "still not done": no BGM, no film damage, no clock blur, no sting or end kit
  - a 0.04 s sliver at 3:58.68
- **Runs and cost:** 4 runs per arm, $8.51 in all (cap $12).

| Fault | current (4 runs) | c (4 runs) |
|---|---|---|
| F1 cover spam, F2 no tightening, F3 no J/L, F4 no BGM, F5 no film damage, F7 no sting/end kit | 4/4 each | 4/4 each |
| F6 no clock blur | 2/4 | **0/4** |
| F8 the 0.04 s sliver | 2/4 | 3/4 |
| **Faults caught** | 7, 8, 6, 7 (mean 7.00) | 7, 6, 7, 7 (mean 6.75) |
| Questions answered | 73 | 30 |
| Cost per run | $1.11 | $0.90 |

- **Not settled on the total:** a gap of 0.25, inside the spread of each arm (2 for current, 1 for c).
  On this draft the shorter skill neither helps nor hurts how many faults are found.
- **One loss that points at a cause:** clock blur, 2/4 → 0/4. In c, HKS-C3 ("the TV clock is blurred to
  hide the re-cut") is absorbed into X10. Its question "where would a jumping clock show a cut" goes with
  it, and X10's question only asks about rendered frames. The two current runs that caught it argued
  exactly C3's point. So the C3 → X10 merge should carry C3's question, or C3 should stay. Four runs is
  thin evidence; it is a lead, not a proof.
- **Cheaper:** c used about 25 % fewer output tokens and cost about 19 % less per run.
- **Limits:**
  - a review of a finished draft, not a live build
  - one episode
  - rule ids in the self-check can hint the arm to the judge
  - the judge was not checked against a script this time; quotes were spot-read for F6

## 5. Regrowth (`regrowth.py`, `tools/hks_correct.py`)

- Replaying K28–K77 can't measure it: they were all filed onto rules that already existed (0 new rules
  first cite one of them). The duplicates in hks-build predate the intake. They came from extracting
  rules.md and principles.md, plus "I did X" notes kept as rules.
- The intake already asks a model "already a rule?". Offline (`--method lexical`) that check is off.
  So a new rule passed with `--repeat-of K<n>` was written even when an active rule already cites
  K<n>.
- **Built:** a deterministic check in `questions()`. When a new rule repeats a correction an active
  rule cites, it names that rule and asks: `--rule` (broken again), `--supersedes` (replaced) or
  `--keep` (both stay).
  - Test: `test_a_new_rule_for_a_repeated_correction_names_the_rule_that_cites_it`.

## 6. Also fixed

HKS-X106, X107, X108 and X109 carried markdown bold inside their `title` field, so the skills rendered
`****…**.**`. Titles cleaned and the skills regenerated (`hks_registry_build.py --check` passes).

## Yours to decide

1. **Merge the 14 groups in §2?** Per group: supersede (the absorbed rules stop being asked), or keep.
   Of the absorbed rules, these are confirmed by you: C1, C29, X41, X16, X81, HKS-32, C28, X40, C20,
   X28, C30, HKS-33, C3, X27, C9, C10. The canonical takes their corrections, so no K id is lost.
2. **The two contradictions in §2:** which rule wins on cover length, and on tightening in plain
   studio view.
3. **What the handover asks:** keep one answer per rule (164), or drop questions for gated rules and for
   playbook recipes (a schema and `hks_enforce` change).
4. **Whether the playbook stays inside the skill you read**, or moves to a file loaded on demand.
