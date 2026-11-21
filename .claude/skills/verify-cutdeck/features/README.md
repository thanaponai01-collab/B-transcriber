# CutDeck verification map

The maintained source for proving CutDeck's user-facing Premiere behaviour live. Read this index,
then follow the matching feature file. `C` below means
`python .claude/skills/verify-cutdeck/scripts/cdv.py`, run from the repo root with
`PYTHONIOENCODING=utf-8`.

## Baseline preconditions

- Premiere Pro running with the user's project open (only the user opens projects).
- `C doctor` exits 0. If not, `C launch` (plus `--restart-helper` / `--reload-panel` after code changes).
- `C start --label <feature>` then `C scratch`: the scratch sequence `CutDeck verify (scratch)`
  holds exactly `V1@0` and `A1@0`, a 6 s 1080x1920 30 fps test clip, and is open. `scratch`
  clears clips only: In/Out marks, markers and track mute from an earlier run stay, so read them
  (`read_timeline`) before a recipe that depends on them.
- Nothing else selected in the user's sequences (doctor's `selection` line).

## Driving conventions

- Every action is `C call <command> '<json>'`: the same helper path as the MCP tools.
- Name the sequence in every call that takes one: `"sequence": "CutDeck verify (scratch)"`.
  The transform commands and `add_markers` take none and act on the ACTIVE sequence, so the
  scratch must be the open one (it is after `C scratch`).
- Address clips by the ids `read_timeline` prints; re-read after any edit (ids are start times).
- Undo with `C call menu_command '{"path": "Edit > Undo", "focus": null}'`, then read back.
- End every recipe with the scratch sequence back to its baseline, then `C cleanup`.

## Proof and skip reporting

- Proof is the recorded call files plus a read-back after each edit and after each undo;
  `C shot <label> --frame` for anything that changes the picture.
- Report the run folder `output/verify-cutdeck/runs/<run_id>/` and the checkout commit from `C doctor`.
- A step you could not run is reported with the command tried and the unmet precondition.
  Never report it as verified through another route.

## Features

- [Timeline editing](./timeline-editing.md): read, select, move/trim/disable/remove clips, undo. Proven with this skill.
- [Menu and keyboard commands](./menu-and-keys.md): any menu item or shortcut, on the right timeline.
- [Transform of selected clips](./transform.md): scale, rotation, position, anchor, align.
- [Cut a copy (Rough Cut engine)](./cut-copy.md): frame ranges cut out of a copy of a sequence.
- [Ways in for agents and scripts](./entry-points.md): MCP tools, `premiere_cli`, `Backend().premiere`.
- [Effects, parameters and transitions](./effects.md): add an effect, set any parameter, add a transition.
- [Marks, markers and track mute](./marks-markers-mute.md): In/Out, sequence markers, the eye / M button.
- [Text Graphics](./text.md): place a text Graphic with your own text, edit text already on the timeline.
- [Premiere dialogs: speed and nest](./dialogs.md): Clip > Speed/Duration and Clip > Nest, filled for you.
