---
name: hks
description: "HKS (โหนกระแส) entry point. Load first for any HKS editing work: it names the stage skill to load, says no stage is done until its gate passes, and takes every user correction through tools/hks_correct.py."
---

GENERATED from projects/hks/registry by tools/hks_registry_build.py; do not edit.

# HKS: start here

The stages run in this order. Load a stage's skill before you start the stage. **A stage is not done until its gate passes.** Until then don't call it done, ready or finished, and don't start the next stage.

| Stage | Load | Done when | Gates its rules name |
|---|---|---|---|
| Day setup | `hks-day-setup` (14 rules) | `python -m cutdeck.hks_gates --prproj <saved .prproj> --sequence Editing` (the day's split sequence by its exact name; `Edit` on some days) prints `PASS day_setup` | `day_setup` |
| Paper edit | `hks-paper-edit` (55 rules) | the user approves the paper edit in their own words (no code gate measures a story) | none |
| Build | `hks-build` (56 rules) | `python -m cutdeck.hks_gates --prproj <saved .prproj> --sequence "<draft>" --from <body start s>` exits 0: no control fails | `draft_labels`, `near_miss_covers`, `same_frame_share`, `source_repeats`, `unsafe_holds`, `visible_cuts_in_speech` |
| Handover | `hks-handover` (29 rules) | `premiere_hks_handover` returns HANDOVER OK (it saves, runs every gate and stores the signed record the panel shows) | `same_frame_share`, `source_repeats`, `visible_cuts_in_speech` |

## When the user corrects you

1. Before anything else, run `python tools/hks_correct.py "<the user's exact words>" --episode <YYYYMMDD> ...` (its `--help` lists the rest). It is the only way a correction becomes a rule. Never write a rule by hand into rules.md, principles.md, a skill or a memory file.
2. It exits 2 with questions (which rule wins a conflict; gate or note?). Ask the user each one, then rerun with the answers.
3. Write the K id it prints next to the correction where memory tells the story. A test fails on a correction quoted in memory with no K id, and on a K id no rule cites.
