# HKS registry layout: one rules.json (A) vs rules/<id>.json (B)

Goal: decide the layout by measuring diff size and merge conflicts when several sessions edit rules at once.

Reproduce (Python 3.13, git 2.53, Windows 11):

    python experiment.py   <worktree>/projects/hks/registry/rules.json > run_output.txt   # also writes results.json and work/<scenario>-<layout>/ repos
    python bench_readers.py <worktree>/projects/hks/registry/rules.json | tee bench_output.txt

## Setup

- Source: the 181-rule `rules.json` from the hks-registry worktree (read only). A and B use the same dump: `indent=1, ensure_ascii=False`, trailing newline. B keeps `schema` and `stages` in `meta.json`.
- The three rules: K24, K25 and K20 already have entries. These were added last, so the base drops HKS-X42 (K24, J/L on a copy), HKS-X95 (K24, before-you-cut 7) and HKS-X96 (K19/K20/K25, ellipse or circle mask). Each branch then puts one back verbatim. X95 and X96 sit next to each other, and X42 sits far away.
- Every merge is a real `git merge --no-ff` into master, one branch at a time. A conflict, or a clean merge with a wrong result, is resolved to the known-right state before the next merge.
- Measurement: conflicted files come from `git ls-files -u`, hunks from `<<<<<<<` lines.
- A conflict is **false** when the rule-id sets changed by the two sides do not overlap.
- Every clean merge is parsed with a loader that rejects duplicate keys and ids, then compared rule by rule with the expected set.
- "Neighbour" in scenario 2 means the rule right next to the insertion point: X94, just before the added X95, marked superseded by X96. In the append variant it is X104, the last rule.

## Results

| Scenario | Lines per change (A / B) | A conflicts | B conflicts | A + `merge=union` |
|---|---|---|---|---|
| 1a. 3 adds at their source position | 26, 28, 30 / 26, 28, 30 (1 new file each) | 1 of 3 merges, 2 hunks, false (X95 and X96 are adjacent) | 0 of 3 | X96 merge: **corrupt JSON** (two rules interleaved) |
| 1b. 3 adds appended at the end | 26, 28, 30 / same as 1a | 2 of 3, 2 hunks each, both false | 0 of 3 | 2 of 3 **corrupt** |
| 2a. add beside + supersede the rule before | add 28, supersede 4 / same | 0 | 0 | clean, correct |
| 2b. add at end + supersede the last rule | 28, 6 / n/a | 0 | n/a | clean, correct |
| 3. two edits to the same rule's text (true conflict) | 2, 2 / 2, 2 | 1, 1 hunk, true | 1, 1 hunk, true | clean but **two `"text"` keys**: a plain `json.loads` keeps the last one and loses one edit silently |
| 4a. generator re-sorts by id vs add X95 | 3962, 28 / n/a | 0 (X95's sorted neighbours equal its source neighbours) | n/a: file order has no meaning | correct |
| 4a2. re-sort vs add M-3 (sorted neighbours differ) | 3942, 24 / n/a | 1, 1 hunk, false | n/a | **one object with two `id` keys**: a plain loader drops a rule silently |
| 4b. reformat (`indent=2`) vs add | 9104 in 1 file / 8380 in 181 files; add 28 / 28 | 1, 1 hunk, false | 0 (the new file keeps the old format until the generator runs again) | **corrupt** |
| 4c. reformat vs supersede X94 | 9160 / 8432 in 182 files; edit 4 / 4 | 1, 1 hunk, false | 1, 1 hunk, false (only X94.json) | **corrupt** |

Totals, printed by `experiment.py` from `results.json`:

| Layout | Merges | Conflicted | False | Corrupt |
|---|---|---|---|---|
| A, all 9 scenarios | 20 | 7 | 6 | 0 |
| A, the 5 scenarios B also ran | 11 | 4 | 3 | 0 |
| B, the same 5 scenarios | 11 | 2 | 1 | 0 |
| A + `merge=union`, all 9 | 20 | 0 | 0 | 7 (2 of them parse silently: duplicate keys) |

B's only false conflict is a reformat against an edit to the same rule.

Diff size per add is the same in both layouts: 24 to 30 lines, one file.

## Reader cost

Load all rules, then check that ids are unique and every `superseded_by` target exists. B also checks that the filename equals the id.

| Rules | A warm | B warm | A first load in a new process | B first load |
|---|---|---|---|---|
| 181 | 0.81 ms [0.77 to 0.82] | 10.97 ms [10.82 to 11.00] | 1.10 ms | 11.71 ms |
| 1810 (10 copies) | 7.57 ms | 114.7 ms | 8.07 ms | 113.8 ms |

- Each cell is the median of 7 fresh processes, alternating A and B, with 50 repetitions in each.
- The slowest first load took 199 ms (181 rules) and 11.4 s (1810 rules) in B, against 10.6 and 16.9 ms in A. Which round it came from was not recorded. Antivirus scanning of freshly written files is a guess, not measured.
- Limiter for B, from a split timing of 181 files: open and read take 7.35 ms, about 40 µs per file. Glob takes 0.49 ms and JSON parsing 0.51 ms.
- The integrity check costs 0.02 to 0.5 ms in either layout.
- Does it matter (inferred): the extractor and the gates load the registry once per run, so 11 ms is noise. At 1810 rules B takes about 0.1 s per load, which matters only to a loop that reloads the registry.
- Loader code: A is 1 line. B is 6 lines (glob, sort, parse, filename check).

## Caveats

- Correctness is checked by rule id, not by position. A clean merge in A that put a rule in the wrong place would still count as correct.
- The three adds reuse known, distinct ids. Two sessions that each take "the next free id" would collide in both layouts: an add/add conflict in B, and in A a duplicate id that may merge clean. The layout does not fix id allocation.

- B loses source order. A keeps the `rules.md` order, so B needs an `order` field or a sort key if any reader relies on order.
- No custom JSON merge driver was tried. A per-id three-way merge is about 25 lines, not a one-liner.
- The extractor (`tools/hks_registry_extract.py`) rewrites the whole file with the same dump. A rewrite in the same format produces line diffs only where values change, so scenario 4 shows only what happens when the dump format or the rule order changes.
