# HKS gates: corrections that turned into checks

**Why this folder exists.** On 20261125 YT agent v1 broke rules that had been committed ten hours
earlier as "each mistake has a gate". The transcripts show why
([failure-table.md](failure-table.md)):

- The rules had been read in every session.
- What got through was mainly checks that measured a proxy (C), rules that contradicted each other
  (D), and rules with nothing to run them (E).
- In the two worst cases the agent saw the failing number and handed over anyway (B).
- "Gates" written as text don't run.

## Files

| File | What it holds |
|---|---|
| `registry.json` | Every gate: the mistake it catches, control or warning, the pass line, its status, the backtest evidence. Code reads the line and kind from here. |
| `failure-table.md` | Every user correction from 1123 to 1125, word for word: how it got through, and the FMEA rank. |
| `backtest.md` | Each gate on all 10 agent drafts and the user's 14 finished cuts: precision, recall, the spread of the finals, and the enforcement test. |
| `overrides.jsonl` | One line per override: time, gate, sequence, value, reason, who. |
| `data/` | Evidence a gate was backtested on that no longer exists elsewhere (the 1125 v1 A1 at 19:34). |

## How the gates run

- In Premiere: the helper's `premiere_hks_handover` tool (`cutdeck/hks_enforce.py`).
  1. Saves the project and reads the save.
  2. Finds the draft by its GUID and runs every code gate.
  3. Checks that every active do-confirm rule in `projects/hks/registry/` has a written answer.
  4. Copies the save into `CutDeck/Drafts`.
  5. Appends a record signed by the helper to `output/hks_gates/records.jsonl`, keyed by GUID and cut hash (`cutdeck/hks_gate_store.py`).
- The CutDeck panel's HKS Gates section shows every sequence from those records only (`premiere_hks_status`):
  - pass;
  - fail, with each gate id and value;
  - ungated, which covers never gated, changed after its last run, not saved, and a record not signed by the helper.
- `hks_status` with `mark_baseline: true` at day set-up marks every later sequence `new`, whatever its name.
- Offline, on a save on disk: `python -m cutdeck.hks_handover --prproj <day>.prproj --sequence "<draft>" --from <body start s>`.
- `python -m cutdeck.hks_gates_backtest` reruns the evidence for every line.
- The Stop hook that read session transcripts was removed on 2026-11-26, after the helper route was proven live (run `output/verify-cutdeck/runs/20261126-163421-hks-gates`). Its local registration in `.claude/settings.local.json` is a no-op without the file.

## Lifecycle of a gate

1. **A correction becomes a candidate.** Every user correction gets a row in
   `failure-table.md`, with its way (A–F). A correction in modes C or E gets a candidate gate.
   Mode C means the check measured a proxy, so the candidate must measure the goal itself.
   Mode D is a rule edit, not a gate: the user picks which rule wins, and the loser is deleted
   from rules.md.
2. **The line comes from the user's finals.**
   - Run the candidate on the user's finished cuts.
   - The line is their extreme (max for a "max" gate), set on the tuning days. The holdouts
     (1002, 1109, 1118) are scored once against it.
   - If any user final fails, the gate can only be a warning.
3. **Kept** needs both of these:
   - It passes every user final, the holdouts included.
   - It catches at least one draft the user corrected for that mistake (TP ≥ 1).

   Record TP / FP / FN in `evidence`.
4. **Control or warning.**
   - **Control:** it passes all finals and the user's verdicts back it. A failed control blocks
     the handover (`late_draft_policy` decides block or label).
   - **Warning:** it fails some user finals, or it is a list to look at. It is printed in the
     handover header and never blocks.
5. **Override.** `--override GATE="reason" --by <who>` lets one failed control through. The agent
   or the user may override, always with a written reason; one without a reason is refused (user,
   2026-11-25). Each override is a line in `overrides.jsonl`, and the hook makes the handover name it.
6. **Retire** a gate when either of these happens:
   - It fails a user final after any line change.
   - It has 0 TP over 5 episodes in a row while it blocked or warned at least once (cost with no
     catch).

   Retired gates leave the code and stay in the registry with the reason and date. Three were
   retired on 2026-11-25 on evidence: `jump_cuts_framediff`, `endings_reviewer` and
   `setup_reviewer`.
7. **Re-line** after every 3 new episodes: rerun the backtest with the new finals added. A line
   only moves to keep every final passing.

## The success metric

**Corrections per episode that a kept gate should have caught.** The 1123–1125 baseline under
today's gates:

| Day | Corrections A–E | Caught by a kept gate | Which |
|---|---|---|---|
| 1123 | 6 (K1, K2, K3, K5, K6, K7a) | 2 | K6 draft_labels (v1, v2), K7a near_miss_covers (v4) |
| 1124 | 4 (K9, K10, K11, K15) | 1 | K11 same_frame_share (v2) |
| 1125 | 6 (K17, K18, K21, K22, K23, K26) | 1 (+1) | K23 same_frame_share. Also K27 source_repeats, which was mode F because no rule existed then |

**Baseline:** 4 of 16 rule-break corrections, plus K27, reached the user while a gate that exists
today would have caught them. That is 5 corrections over 3 episodes, 1.7 per episode. The target
is 0 per episode.

The other 11 rule breaks have no working gate yet:

- C: K2, K5, K18, K22.
- D: K3, K17, K21.
- E: K1, K10, K15, K26 (day_setup warns on K10 and K26).
- B: K9 (the skipped split; the hook's label rule now forces it to be named).

**How to measure it on the next episode:**

1. `hks_handover` copies every handed-over draft into `CutDeck/Drafts`, so the draft survives
   Auto-Save rotation.
2. After the user's final save, run `python -m cutdeck.hks_gates --prproj <the Drafts copy>
   --sequence "<draft>"`. Diff that copy against the final (memory: diff-user-edits).
3. Add every correction (verbal, red marker, diff) to `failure-table.md` with its way. For each
   one, mark whether a kept gate fired on the handed-over copy.
   - **Fired:** the handover header named it. If the user still had to correct it, that is a
     policy issue (label vs block), not a gate miss.
   - **Should have fired and didn't:** the gate missed. Fix the gate, or retire it.
4. Corrections the gates don't cover (D, F, and C with no gate) are counted separately. They are
   the queue for new candidates.

## Your decisions (no experiment settles these)

1. **Late drafts:** decided 2026-11-25, **label**. A failed control may reach you only with the
   handover opening on its id and value.
2. **Overrides:** decided 2026-11-25, **the agent with a written reason** (or you). Every
   override is logged in `overrides.jsonl`.
3. **Reviewer cost per draft:** both cold reviewers failed to agree with you, so none runs now.
   For a future one, the measured costs were $0.71 per 168 endings (Sonnet) against $1.47
   (Opus), and $0.18 per set-up read (Sonnet).
4. **PRINCIPLES.md:** should "a correction becomes a gate; a gate stays only if it catches
   something" be promoted there?
