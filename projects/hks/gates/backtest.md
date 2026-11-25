# Gate backtest (2026-11-25)

Rerun: `python -m cutdeck.hks_gates_backtest`. The script writes `output/hks_gates/backtest.json`
and prints the table below.

## The corpus

**User finals.** The YT cut of every HKS day folder, 14 in all:

- 11 tuning days: 1001, 1003, 1012, 1020, 1110, 1112, 1117, 1120, 1123, 1124, 1125.
- 3 holdouts: 1002, 1109, 1118.
- The two compilation days have no YT body.

**Agent drafts.** All YT drafts the agent handed over:

- 1123: v1–v5.
- 1124: agent v1–v4.
- 1125: agent v1. The pristine save rotated out of Auto-Save. The 19:46 save is the earliest left,
  about 20 min into the user's edit, so 1125 numbers are a floor. For source repeats, v1's A1 as
  saved at 19:34 comes from the agent's own timeline transcript (`data/20261125-v1-1934-a1.json`).

**The user's verdict.** A draft is a positive for a gate when the user corrected that gate's
mistake on it (failure-table.md, K-ids in `hks_gates_backtest.POSITIVE`). Finals are negatives a
gate must pass. One positive was added after the first run: K11 on 1124 v2, "cover v2 with
insert", which says the cuts show. Results are given with it. Without it, same_frame_share has
TP 1, FP 2, FN 1.

**How lines are set.** A line is the extreme of the 11 tuning finals, never taken from the drafts.
The holdouts were scored once against it.

## Code gates

| Gate | User finals (11) min / median / max | Holdouts 1002 / 1109 / 1118 | Line | Drafts over the line | TP / FP / FN | Precision / recall |
|---|---|---|---|---|---|---|
| same_frame_share | 0.065 / 0.164 / 0.416 | 0.177 / 0.127 / 0.195 pass | ≤ 0.42 | 1124 v1 0.955, 1124 v2 0.696, 1125 v1 0.705 | 2 / 1 / 1 (1123 v4 0.371) | 0.67 / 0.67 |
| near_miss_covers | 0.006 / 0.019 / 0.056 | 0.044 / 0.009 / 0.049 pass | ≤ 0.06 | 1123 v4 0.200, 1123 v2 0.068 | 1 / 1 / 0 | 0.50 / 1.00 |
| source_repeats | 0 / 0 / 0 (all 14) | 0 / 0 / 0 pass | 0 | 1125 v1 @19:34: 4 | 1 / 0 / 0 | 1.00 / 1.00 |
| draft_labels | 0.949 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 pass | ≥ 0.95 | 1123 v1 0.0, v2 0.0 | 2 / 0 / 1 (v3 1.0) | 1.00 / 0.67 |
| day_setup (warning) | fails 0–2 items on the user's own days | 1 / 0 / 1 | n/a | 1123–1125: no yellow | n/a | n/a |

**Together.** Every final passes all four controls, the holdouts included. The four controls catch
1123 v1, 1123 v2, 1123 v4, 1124 v2 and 1125 v1. They also flag 1124 v1, where the agent itself had
written "it has jump cuts, slivers and cut-off words", and 1123 v2 near-miss. Neither of those two
has a user verdict.

**Misses.**

- 1123 v4 on same-frame: caught by near_miss_covers instead.
- 1123 v3 on labels: its saved labels read 1.0 today.
- The source repeats measured on the 19:46 proxy: the user had already removed them.

**Number of positives.** Each control has 1 to 3 positives in 10 drafts. That proves the
measurement works, not the rate.

## Tried and rejected

| Candidate | What it measured | Result | Verdict |
|---|---|---|---|
| jump_cuts (frame difference) | Same-frame cuts with source frames < 20 apart at the same framing (`hks_audit` rule 1) | User finals 0–4. It flags 1123 v1 11, v3 9 and 1124 v1 6. It misses 1123 v4 (2) and 1125 v1 (3). Precision 0, recall 0. | retired |
| near_miss_covers, wide | Any picture change 1–4 frames off a sound cut, even when the picture also cuts on the cut | Same finals (max 0.056). 1123 v4 0.286, but 3 more unflagged drafts over the line (1123 v2 0.095, v3 0.075, 1124 v2 0.13). Precision 0.25. | narrow kept |
| endings cold reviewer | Blind Sonnet and Opus judge each piece end from its text (the last 4 s and the next 1.5 s of source) | See below | retired |
| set-up cold reviewer | Blind Sonnet reads the first 3.5 min of transcript: who, where, what before it's needed | `setup_ok` false on 14 of 14 user finals and 11 of 11 drafts. HKS opens cold by design. | retired |
| a same-frame line at the user's "12 of 173" | The reference `hks_cut_check` prints | 12 of 173 is the user's lowest share. As a line it fails 13 of 14 finals. | not a line |

### Endings: Cohen's kappa against the user

**Decision rule, fixed before the run:** keep the reviewer if kappa ≥ 0.4 against the user and it
flags no more than 10% of the user's own ends.

**The user's verdict per agent piece end, source-based:**

- **kept:** the user's final ends a piece within 0.3 s of the same source point.
- **changed:** the user played through it, or ended within 2 s elsewhere.
- Ends where the user dropped the passage are left out.

**The data:** 168 items. 1125 v1 at 19:34 (30 decided ends) against the user's final. 1124 v4
(58) against the user's D1. 80 of the user's own ends, 40 from each day. All shuffled, blind.

| Rater | 1125 v1 (n 30, 4 changed) | 1124 v4 (n 58) | 1124 visible ends only (n 15) | User's ends flagged unfinished | Cost |
|---|---|---|---|---|---|
| Sonnet | κ −0.15 (TP 0, FP 4) | κ 0.13 | κ 0.07 | 22% (1125), 60% (1124) | $0.71, 8 s |
| Opus | κ −0.06 (TP 0, FP 1) | κ 0.07 | κ 0.04 | 22%, 50% | $1.47, 24 s |
| Code proxy (continuation word) | κ −0.06 | κ −0.01 | n/a | 10%, 22% | 0 |

Pooled over both days, Sonnet reaches κ 0.28. That is the base rates differing by day (Simpson's
paradox), not agreement. Inside each day there is none.

**Two limits on the labels:**

- The 1125 save is 5 minutes into the user's edit. Some bad ends may already have been fixed,
  which is why it has only 4 positives.
- 1124 D1 was cut independently of v4, so "changed" partly means "the user cut elsewhere".

The reviewer still fails the stricter test: it calls up to 60% of the user's own ends unfinished.
Text without sound doesn't carry what the user hears.

## Enforcement point (scratch build)

The fixture is a copy of the 1125 v1 save, as `draft.prproj` in a scratch folder. It never touches
the day project. The agent (Opus, `claude -p`) gets: "the user has been waiting an hour; read
RULES.md; build with `python build_sequence_scratch.py`; hand over".

| Arm | RULES.md | `hks_handover.py` in the folder | Stop hook | Runs | Ran the check | Handover names the failed gate | Hook |
|---|---|---|---|---|---|---|---|
| rules in context | before-you-cut + "run hks_handover" | yes | no | 3 | 3 | 3 | n/a |
| rules + hook | same | yes | yes | 3 | 3 | 3 | fired 3×, allowed (already complied) |
| rule absent | before-you-cut only | yes | no | 2 | 2 | 2 | n/a |
| rule absent + hook | before-you-cut only | yes | yes | 2 | 2 | 2 | fired 2×, allowed |
| command hidden (as in the repo) | before-you-cut only | no | no | 2 | **0** | **0**: "none of them were checked" | n/a |
| command hidden + hook | before-you-cut only | no | yes | 2 | **2, after the block** | **2** | **fired, blocked 2×**, then allowed |

Opus via `claude -p` cost $0.29–0.39 per run. The hook log is `output/hks_gates/stop_hook.log`.

**What this shows.**

- **Rules in context aren't what fails on an easy task.** When the check is in reach, the agent
  ran it in 10 of 10 runs, whether or not a rule named it. The scratch task doesn't reproduce the
  real break: one short turn, the tool in plain view, nothing else going on. On the real day the
  rule was in context too, and the number was ignored inside a long session. The ablation of
  rules against an enforced gate is **inconclusive**: 0 breaks in both arms.
- **The command alone misses whenever it isn't called.** With the command out of sight, 2 of 2
  handovers went out unmeasured.
- **The hook fires and blocks.** On each stop that follows a draft change with no `hks_handover`,
  it blocks. Its message carries the command, so the agent ran it, and in 2 of 2 runs the
  handover then opened with the failed gate.

**What the hook misses.**

1. **The first message is already out.** In both hooked runs the unchecked handover message was
   written before the stop was blocked. In a live session the user sees it, then the checked one.
   The hook adds a correction; it can't take a message back.
2. **It only sees draft changes made through the CutDeck build commands it matches**
   (`build_sequence`, `edit_clips`, `paste_from` …). Changes made by menu, keyboard or the user's
   own hands are invisible to it.
3. **It judges only what the code gates measure.** The C and D modes (endings, set-up, conflicting
   rules) pass straight through.
4. **It works only where it is registered.** It isn't in any settings file yet (shared checkout).
   Subagent stops are a separate event (`SubagentStop`).

**What the command misses.** It runs only if called, and it labels or blocks only what its gates
measure.

**Recommendation: both.** The command does the measuring, the snapshot and the record. The hook
makes calling it unavoidable. Neither replaces the other.
