# HKS rule registry: extraction report (2026-11-26)

[rules/](rules/) holds every HKS rule and principle, one file per entry named by its id, and
[registry.json](registry.json) the schema version and stages. It was curated by hand
from `rules.md`, `principles.md`, `before-you-cut.md`, `../PRINCIPLES.md` and the two policies in
`gates/registry.json`. Commits come from `tools/hks_registry_extract.py`:

```
python tools/hks_registry_extract.py           # fill commit/added where null, validate, print counts
python tools/hks_registry_extract.py --check   # recompute every commit, report drift, write nothing
```

Each entry has one field the brief did not list: `probe`, the phrases from its source file that
the extractor passes to `git log --follow -S`. A probe for an active entry must occur exactly once
in today's file. A superseded entry may probe wording that is gone. A rerun fills only empty
`commit`/`added` fields and never touches the rest.

## Counts (181 entries)

| | |
|---|---|
| status | active 169, superseded 11, retired 1 |
| kind (all `proposed`) | do_confirm 166, code_gate 11, human_only 4 |
| stage | build 83, paper_edit 58, handover 28, day_setup 12 |
| confirmed | 91 yes, 90 no |
| ids | HKS-R1..R7, HKS-C1..C31, HKS-1..33, M-1..M-6, HKS-X1..X104 (new) |

## Conventions I chose

- **code_gate** means a gate with status `kept` in `gates/registry.json` measures the rule's main
  claim. Kept warnings count (`visible_cuts_in_speech`, `unsafe_holds`), though they print a list
  to look at with no line. **`gate` may also name a gate that only partly measures the rule.**
  Then the kind stays `do_confirm`, e.g. HKS-R5 with `same_frame_share`, which counts camera
  changes too. The only non-kept gate used is `day_setup` (candidate). No entry points at a
  retired gate. Three were retired: `endings_reviewer`, `setup_reviewer`, `jump_cuts_framediff`.
- **Partial code gates** (code_gate, but part of the text is unmeasured):
  - HKS-X8: `near_miss_covers` doesn't check that a cover opens on a fully-on frame.
  - HKS-X63, HKS-X38: they list cuts in speech, not unfinished thoughts.
  - HKS-X65, HKS-X94: the share doesn't separately check the cover over each same-scene jump.
  - HKS-X37, HKS-X66: `unsafe_holds` lists the holds; someone still has to look at the frames.
  - HKS-33: the share doesn't measure the safe-hold condition.
  - HKS-X75: `draft_labels` counts labelled pieces, not whether each colour is right.
- **confirmed** is set on every entry. It is true only where the source gives the words to the
  user. It is false for:
  - every candidate, seen and guess entry;
  - the 1123-cut lessons read from the user's cut (X1-X4, X6, X7);
  - the agent-written sections: the timeline playbook, "My own mistakes", all of
    before-you-cut.md (X87-X101), the working layout (X76), X79, M-3 and the "test a check"
    candidate (X102).
- **commit** is when the probe's wording first entered that file. Rules R1..R7 came into
  rules.md "word for word" from workflow-log.md at `0d67094`. Their earlier history in
  workflow-log.md is not traced.

## Supersessions (only where the docs say so)

| Old | New | Doc's words |
|---|---|---|
| HKS-6 | HKS-C21 | "Narrows HKS-6 to a rule" |
| HKS-8 | HKS-C7 | "Confirmed as HKS-C7" |
| HKS-9 | HKS-12 | "HKS-9 → see HKS-12" |
| HKS-12 | HKS-C8 | "HKS-12 confirmed" |
| HKS-21 | HKS-C9 | "HKS-21 confirmed" |
| HKS-27 | HKS-C17 | "HKS-27 confirmed" |
| HKS-28..31 | HKS-C23..C26 | "moved up: HKS-28 → C23 …" |
| HKS-X12 "covers ≥ 4 s" | HKS-R6 | rules.md "Replaced by rule 6's 'no fixed minimum'" |

Retired: HKS-X84 "stakes said within 60 s" ("Refuted by measurement").

## Id collisions and ambiguities

1. **Small numbers mean different things.** "rule n" is HKS-Rn. "draft workflow 1..4",
   "before-you-cut 0..8" and "my mistakes 1..10" are aliases on X ids.
   `gates/registry.json` cites "rules.md mistake 5", which is HKS-X67.
2. **M-7** is cited only as a proposal (PRINCIPLES.md: "ask the user before promoting it to M-7"),
   so it has no entry. It is the only cited id not in the registry.
3. **HKS-28..31** survive only as a "moved up" note. Their probes match the removed definitions
   (commit `29f890d`).
4. **HKS-22 vs HKS-C4.** C4 cites HKS-22 but never says "confirmed", so both stay active.
5. **HKS-6 → C21** follows the brief ("narrows"), but HKS-C18 still cites HKS-6 as live ("the
   accused's answer (HKS-6) … stay[s]").
6. **"Covers ≥ 4 s"** has two named replacers. rules.md says rule 6; principles.md says HKS-C9
   "replaces" it. I chose HKS-R6, where the struck text sits.
7. **Rule 5's status note** ("now allows inset camera changes and cuts under a still, and a
   punch-in needs a cover") sits in rules.md's header, not in rule 5. I folded it into HKS-R5's text.
8. **K7b** ("Show the fully on. Don't show the resolve.") is mapped to HKS-X9 (full-frame
   footage). It could instead be the "fully on" half of HKS-X8.
9. **K8** ("duplicate the same draft then fix it") is mapped to HKS-X17 (route order), by inference.
10. **K12, K13** ("feel fun") have no entry, because no rule was ever written for them.
11. **Twin commits.** `4dfab64` and `a80c11f` carry the same change and message. `6ce5764`
    reverts `4dfab64`, and the text survives through `a80c11f`, which failure-table cites. I set
    HKS-X73, X74, X76, X77 and X79 to `a80c11f` by hand, so `--check` reports exactly these five
    as drift.
12. **HKS-X103 (late-draft policy)**:
    - its wording first appears at `37905b9`, as one of two options;
    - the user chose "label" at `27cd553`.
13. **Left out, with the reason:**
    - "Other rules, still in the log" (6 pointers to workflow-log.md): not lifted, no text here.
    - "Questions to ask": open questions, not rules.
    - "Before any draft, read before-you-cut.md": meta.
    - PRINCIPLES.md candidates already held by an HKS entry: watch time (HKS-C18), brand marks
      (HKS-C3), keep the source untouched (HKS-C30).
    - PRINCIPLES.md candidates that are 1RaceClub only: use what's in the project, verify from
      footage.

## Entries that may contradict each other (listed, not decided)

1. HKS-R7 "Same ending every episode" vs HKS-10 and HKS-C16 (endings vary, an open one says so).
   R7 may mean the end card.
2. HKS-R1/R2 ("get in fast", "drop backstory") vs HKS-C27, X39 and X89..X91 (context first). The
   docs reconcile them in words, and failure-table counts K21 as mode D, "rules conflicted".
3. HKS-R2 / M-4 (each point once) vs HKS-11, advice day ("key tip repeated on purpose").
4. HKS-4 (first telling wins) vs its own "better telling" weakening, and HKS-12 "overrides HKS-4".
5. HKS-6 (accused answers at length) vs its weakening ("often short or missing") vs HKS-C18 (stays
   even when slow).
6. HKS-C9 / HKS-21 (no minimum; covers under 4 s normal) vs HKS-X4 (cutaways 8-16 s, "not 2-3 s
   pops") and K2.
7. HKS-C20 / X22 (a sliver is under 0.4 s) vs HKS-X11 (a camera change within 1 s of a cut).
8. HKS-C14 / X19 (3-4 min with nothing new) vs HKS-X86 (5+ min).
9. HKS-X78 (full-screen footage keeps clock and logo) vs HKS-X10 (no bug or clock on footage) and
   HKS-C3. failure-table K17 records this one as a conflict.
10. HKS-17 (film damage marks footage the show frames or lifts) vs HKS-C10 / R6 (film damage on
    B-roll zoomed to full screen).
11. HKS-X65 and X94 say the user's 20261124 YT body had 12 of 173 same-frame cuts; HKS-X38 says
    30 of 180 for the same body. failure-table: 12 of 173 is the user's lowest share; the kept
    line is 0.46.
12. HKS-X34 ("in studio picture, keep the take whole") and HKS-R5 vs HKS-X58 (cut on a repeated
    word, "the user's way to tighten in plain view").
13. HKS-X74 (one colour per question piece) vs HKS-C31 / X88 (hot spots yellow, not just question
    colours). The docs don't say which colour a hot-spot piece gets.
14. HKS-2 (hook lines come back in the body) vs HKS-C24 / X26 (the body doesn't replay a hook
    clip). C24 came from the FB short; whether it holds for the YT is not stated.
15. M-2 (the user exports) vs HKS-X32 (export when asked, with `honekasae_export`). M-2 marks its
    own HKS reading a guess.
16. HKS-16 ("unlabelled topics never reach the cut") vs its own 1123 counter-example (n = 1).
17. HKS-5 (broadcast order unless the viewer needs it elsewhere, 0-4 moves) vs HKS-X1 / X91
    (story order, not the broadcast's).
18. HKS-X33 ("the edge must be in a real pause") vs HKS-X67 (an "every edge in a pause" rule
    failed the user's own cut) and HKS-X63 (a sentence end said without a pause may stay).
19. HKS-C11 (a card may tease beyond the body) vs HKS-X82 (every headline card is paid off).
20. HKS-X3 (B-roll starts and ends on a sound cut) vs HKS-X36 (put the picture change 0.5-2 s off
    the sound cut).
21. HKS-C30 / X42 / X95 (J/L on a duplicate, raw untouched) vs HKS-X45 (J/L by `edit_clips`
    shrinking one picture and extending the other, with no copy named).
22. M-3 (nothing edits the user's day project) vs the day-setup entries that change the user's
    `Editing` and `Backup` (X13, X69, X88, X77).
23. HKS-R6 (cover ideally from the same moment) vs HKS-20 (a proof picture from anywhere in the
    broadcast, even 100+ min away). HKS-C9's "on the topic, or what the broadcast showed then"
    may hold both.

The same rule restated in several files, so the generator can merge them:

| Rule | Entries |
|---|---|
| Whole thought | HKS-32, C28, X33, X40, X63, X92 |
| Same-scene jump covered | HKS-R5, C1, C29, X41, X65, X94 |
| Context first | C27, X39, X71, X89..X91, X98 |
| J/L on a copy | C30, X42, X95 |
| Yellow hot spots | C31, X73, X88 |
| Premiere's own tool | X43, X72, X81, X96, X101 |
| Test a check on the user's cut | X67, X102 |
| Failed gate opens the handover | M-6, X87, X99, X103 |
| Handover checks | X18..X22 with C13, C14, C15, C16, C19 |
| Hook set-up and payoff | X25, C23 |
| No hook clip mid-body | X26, C24 |

## Commits not found, and late ones checked

None is missing. All 181 entries resolved, and 5 were overridden by hand (item 11).

Every entry whose commit differs from the rest under its heading was read against the history:

- **Fixed.** HKS-X10, X25 and X27. Their first probes included words added later, so they matched
  `24d24fb` / `180b6d4`. Each probe is now the bold title.
- **Really added later:**
  - HKS-X17 (`1b77c3a`), X71 and X72 (`12dfd13`), X75 (`1ea8169`), X78 (`12dfd13`);
  - C20-C22 (`b7ada2e`), C23-C26 (`180b6d4`, renamed from HKS-28..31), M-6 (`12dfd13`).

`commit` still dates the wording a probe matches. An entry whose wording was rewritten in place
before today keeps the commit of its oldest surviving phrase.
