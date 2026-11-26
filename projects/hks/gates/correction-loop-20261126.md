# HKS correction loop (2026-11-26): what leaks, what was built, what is yours to decide

**Goal:** nothing the user tells the agent on HKS gets lost, and the skills follow the registry by
themselves. Success is a lower repeat-correction rate: how often the user corrects the same mistake twice.

Evidence: [data/correction-loop-20261126/](data/correction-loop-20261126/) (the matrix, the gold map,
the matcher runs and every script). Branch `hks/correction-loop`.

## Step 1: the traceability matrix (measured)

**Sources:**
- The user's words: every user message in the 115 session transcripts that mention HKS, in full,
  including slash-command arguments and answers to the agent's questions (`scripts/usermsgs2.py`).
- The user's edits: the diffs of the user's final saves against the agent's drafts written up in
  `memory/`. Five headline numbers were re-measured on the saves with `prproj_reader`, and all five
  held.
- Git history of `registry/`, `memory/` and `.claude/skills/hks-*`.

**80 corrections over 4 episodes (1123–1126), 20 per episode:**
- 30 are the K1–K27 rows (K7 is split in four). 28 are spoken or red-marker; K14 and K27 came
  from diffs.
- 18 more spoken corrections. 13 are from 1123–1125 and were missing from K1–K27; 5 came on 1126.
- 32 more found only by diffing the user's saves. Diffs also back 8 of the K rows.
- 21 teaching moments (1120, the user narrating their own edit) are kept apart as context.

The ledger is now `registry/corrections/K1..K77.json`. K28–K77 are the new ones;
`data/.../idmap.json` maps each to its source row.

How far each correction got before this branch (gold map: one model reader per correction against
memory and the registry, written before any matcher ran; `gold_map.json`):

| Step | Reached | Leak |
|---|---|---|
| Told → memory (`projects/hks/memory`, global memory) | 63 / 80 | 17 (21 %), mostly 1123 verbal corrections |
| Told → a registry rule states the lesson | 73 / 80 (63 full, 10 partial) | 7 (9 %): K12, K13, K29, K40, K43, K53, K74 |
| Correction linked to its rule by id (`corrections`) | 28 / 80 | 52 (65 %): only K1–K27 were ever linked |
| Rule → generated stage skill | 73 / 73 | 0: by construction, but skills exist only since 2026-11-26 16:08 |
| Rule → a kept gate measures it | 15 / 80 | 65 (81 %) |
| Came back later (the user corrected it again) | 30 / 80 | |

**Repeat-correction rate so far:** 31 of 80 corrections repeat an earlier correction of the same
mistake (0.39). By episode: 0.22, 0.38, 0.50, 0.53 (`tools/hks_corrections_report.py`). Counting
the 1120 teaching as an earlier telling, it is 38 of 80 (0.48).

How firm the number is:

| Count | Rate | By episode |
|---|---|---|
| All 80 | 0.39 | 5/23, 11/27, 7/15, 8/15 |
| Without the 5 low-confidence repeat pairs | 0.35 | 2/20, 10/26, 6/14, 8/15 |
| Without the 6 same-evening 1124 diff rows | 0.34 | 5/23, 5/21, 7/15, 8/15 |
| Without both | 0.29 | 2/20, 4/20, 6/14, 8/15 |

The rise to 1126 holds in every count. Part of it is mechanical: each new episode has more earlier
corrections it can repeat. The diff rows also differ a lot by episode (2 on 1123, 20 on 1124).

**Where the repeats leak:**
- 15 of the 31 repeat within one episode. The 1124 FB and 1-min were built before the YT diff was
  read (6 rows), and 1123 had drafts v1–v4.
- 16 repeat across episodes. 14 of those had a written rule before that day, and the failure
  table shows rules.md was read in full on every build day. Capture is not the leak. The leak is
  between a rule the agent has read and what it does.
- 4 cross-episode repeats came after the kept gates existed, all on 1126:
  - K64 (17:24) came before that day's handover.
  - K66 (18:57, body over 20 min) came after `HANDOVER OK` at 17:41 (memory).
  - K68 and K69 are diffs of the v1 that the helper's signed records (19:01–19:07) show passing
    every gate.

  In those three the gates passed and the goal failed.

**What this means for Step 2:** the four pieces close capture (memory → rule, 9–21 % leak) and
drift. They do not change what decides the repeat rate, which is rule → behaviour for the 81 % of
corrections with no gate. That part is in "Yours to decide".

## Step 2: what was built

| Piece | Where | Test |
|---|---|---|
| Correction ledger, one file per correction, with `repeat_of` | `registry/corrections/`, schema `$defs.correction` | `test_every_correction_is_valid_and_cited_by_a_rule` |
| Coverage check: every correction cited by a rule; every quoted correction in memory carries `(K<n>)` | `tests/test_hks_corrections.py` | the plants below |
| One intake command. It exits 2 until every question is answered: "which rule wins?" (conflict check against the **registry**), "does a rule already say this?" (`--rule <id>`, a repeat, or `--new`), and "gate or note?" (`--as-is` for a rule broken again). Then it writes the correction, the rule and `conflicts.json`, regenerates the skills and prints the memory line to paste. Live: about $0.15 and 14 s for both model calls | `tools/hks_correct.py` | `test_intake_*` (4) |
| Entry skill `hks`: stage order, which skill to load, "a stage is not done until its gate passes" with the command that proves it, and "every correction goes through `hks_correct.py`" | generated by `tools/hks_registry_build.py` | the hand-edit guard covers it |
| `rules.md`, `principles.md` frozen | `registry/frozen.json` | `test_rule_docs_are_frozen` |
| Lexical ratchet: a new flagged rule pair nobody judged fails | `registry/conflicts.json` (156 pairs: 156 open, 0 judged) | `test_no_unjudged_rule_conflict` |
| Rules after HKS-X114 must come through the intake | `test_new_rules_come_through_the_intake` | |
| Tracking per episode | `tools/hks_corrections_report.py` | `test_report_*` |

Backfill:
- All 80 corrections are linked to the rules the gold map names.
- 5 rules, confirmed by the user on 2026-11-26, cover the 7 corrections that had none: HKS-X110 (audio carries
  its video's label colour), X111 (a film-promo day feels fun, K12+K13), X112 (open on the line
  the user names), X113 (the first voice pre-laps under a full sting, K43+K53) and X114 (an
  inserted interview is not a body piece).
- X108 gained the four details confirmed by the user that lived only in rules.md (0.15 s pauses,
  a swear word cut by sound, short covers, film damage on full-screen covers).
- Memory paragraphs that quote a correction now carry their K id; 3 false hits are marked
  `(not a correction)`.

Proof:
- The day-setup "done when" command was run on the real 1126 save and printed `PASS day_setup`.
- `hks_correct.py` was run live, with the model conflict check, on K17's words ("already full
  screen dont zoom in"). It stopped on HKS-X10 and HKS-X105 and wrote nothing.

## Step 3: prototypes

**1. How a correction is matched to its rule** (`scripts/score.py`, gold = `gold_map.json`, 190 correction–rule pairs):

| Matcher | Precision | Recall | Cost | Notes |
|---|---|---|---|---|
| Heading parse (memory heading = rule `source.heading`) | 0.21 | 0.03 | free | Memory isn't written under rule headings. It found 3 of 79 memory places. |
| ID tags (`(K<n>)` in memory + `corrections` in the rule) | 0.80 | 0.78 where tags exist; 0.38 over all 80 | free, deterministic | Before this branch only K1–K27 had tags. |
| Model matcher (Sonnet, the whole rule book) | 0.78 | 0.78 | $0.35 for 80, about 5 s per 20 | Calls 2 corrections covered that gold says have no rule. Not runnable in pytest. |

To find a correction in memory at all, a quote-form detector (`User…: "…"`, `**User correction`) found
11 of 14 quoted corrections, 9 of 12 hits real. Prose that retells a correction without quoting it
is not found (65 of 79 gold places are prose).
**Recommendation (from these numbers):** ID tags as the test's link, written by the intake. The
quote-form detector for memory. The model matcher as an optional audit, not a test.

**2. Short vs full stage skill** (`data/.../skill_replay/`, throwaway).
- Setup:
  - Task: the paper edit of 1125 and 1126, replayed in one shot from the transcript.
  - Arms: the full `hks-paper-edit` skill (52 rules), or the same rules cut to their titles.
  - Model: Opus as the subject; blind Sonnet judges against per-episode rubrics built from your
    corrections. The judges matched a scoring script on 82 of 82 line-range items.

| Rule breaks | Full | Short |
|---|---|---|
| 1125 (12 items) | 8, 7 | 7, 7 |
| 1126 (14 items) | 6 | 8 |
| Cost per run | about $1.46 | about $1.52 |

- **Not settled.** The gap between arms (0.5 on 1125) is no bigger than the spread within an arm,
  and 1126 has one run per arm (spend capped at $15; $13.55 used).
- The short skill saves about 3 % of input.
- Both arms broke the same items in every run: context, resolution, moves out of order. The full
  arm broke items its own text names. That points at how rules are applied, not at length.
- Proxy limits: one shot versus a session, whole lines (it can't tighten word by word), and no
  user brief.
- To settle it: more episodes at $1.3–1.8 a run, scored by graded line shares.

**3. Generated or frozen rules.md / principles.md.** Drift since the registry was born (93f4f87,
16:08) to 21:32 the same day:
- 35 lines of hand-written rule text were added to the two docs.
- 4 details confirmed by the user existed only in rules.md.
- HKS-X105..X107 existed only in the registry.

Generating the docs from the registry would keep the probe of only 7 of 145 active entries. The
extractor would then fail for 138 of them, and code and docs cite these files in 20+ places.
**Recommendation: frozen** (built). Folding their history into the registry is your call below.

**4. Finals and holdouts:** no cut gate is new or changed on this branch. The new checks read the
registry and memory, not a timeline, so there is nothing to run on the 14 finals or 1002/1109/1118.
The open cut gap from the redesign stays open: covers 1–4 frames late, K7a.

## Step 4: attacks (`test_a_planted_break_turns_its_check_red`)

| Plant | Red test |
|---|---|
| A correction only in memory (quoted) | memory check |
| A new episode in memory, told only in prose | episode check |
| A correction only in the ledger | ledger check |
| A hand-edited skill | `hks_registry_build.py --check` |
| A contradicting rule (lexical axis) | lexical ratchet |
| A contradicting rule in other words, written by hand | intake check (rules after X114) |
| A skipped regenerate step | `--check` |
| A rule with no stage | schema |
| A rule written into rules.md | frozen pin |

**Holes that stay green:**
- A prose correction added to an episode that already has corrections in the ledger, never
  quoted and never put through the intake. The episode check catches a new episode told only in
  prose (plant above), but not this. Only a model audit of memory would; it is not built. The
  model matcher scored 0.78 / 0.78 and costs about $0.35 per 80 corrections.
- A contradiction the intake's model check misses. It found 3 of 3 known ones in the redesign.
  The lexical ratchet adds only what its four axes see.
- `hks_registry_extract.py --check` prints "drift" without failing (pre-existing; not fixed here).

## Tracking: the next three episodes

After each episode, put every correction (verbal, red marker, diff of the final save) through
`tools/hks_correct.py` with `--repeat-of` where it repeats one. Then run
`python tools/hks_corrections_report.py` and fill the table.

| Episode | Corrections | Repeats | Repeat rate | A kept gate should have caught |
|---|---|---|---|---|
| Baseline 1123–1126 | 20.0 / episode | 7.8 / episode | 0.39 | 1.7 / episode (1123–1125, today's gates, gates/README) |
| next 1 | | | | |
| next 2 | | | | |
| next 3 | | | | |

The 1.7 is a different count: corrections a gate that exists today would have caught. The report
counts only gates that existed that day, so 1123–1125 read 0 there.

**Limit of the comparison.** The baseline's 80 corrections were found by three readers sweeping
every transcript and save diff after the fact. The next episodes depend on the agent in the session
running the intake. The intake now names rules that already state the lesson (live, on K64's
words, it named HKS-X69 and X77), so a repeat is the easy path. Still, the same sweep after each
episode is what makes the numbers comparable: `data/correction-loop-20261126/scripts/` (scratch
paths are arguments; the cost per episode is not measured).

## Yours to decide (options and evidence; I decided none)

1. **Which rules may be merged, retired or dropped from what gets loaded.** 179 active rules (164
   do-confirm, so the handover asks 164 answers); 79 unconfirmed (X110–X114 were confirmed on
   2026-11-26). 156 rule pairs flagged and not judged.
   Options:
   - (a) drop unconfirmed rules from the skills;
   - (b) merge rules that cite the same corrections (for example HKS-R6, X3 and X4 on covers);
   - (c) keep everything.
2. **Item budget per stage.** Today: day setup 14 rules, paper edit 55, build 81, handover 29. The
   skill files are 6.5k / 18.9k / 28.6k / 11.6k characters. The replay (Step 3.2) did not settle whether
   shorter items get followed better.
3. **Who judges the taste rules** (story, endings, fun: K12/K13, K21, K22). Options:
   - (a) you, at handover;
   - (b) a second model. The blind endings reviewer cost $0.30–1.47 per draft at kappa ≈ 0; the
     model matcher here is 0.78/0.78 on matching, which is a different task;
   - (c) a warning only.
4. **Whether a failed gate blocks the handover or only labels it.** K66, K68 and K69 came
   after handovers whose gates all passed, so blocking on a failed gate would not have stopped
   them.
   Block has no mechanism in the helper (redesign doc, decision 3).
5. **Whether the old prose history is kept.** Options:
   - (a) frozen in place (as built);
   - (b) moved to `projects/hks/history/`, with the links and the probes updated (138 probes point
     at them);
   - (c) deleted after the registry carries every detail.
