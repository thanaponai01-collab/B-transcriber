---
name: verify-cutdeck
description: Drive the real CutDeck stack in live Adobe Premiere Pro (helper on ws://127.0.0.1:7891, UXP panel, the menu/keys/screenshot routes) to prove a Premiere command or panel feature works, with recorded evidence. Use after changing anything under cutdeck/ or uxp/cutdeck/, or when asked to show that a Premiere command, MCP tool or panel feature works for real, not just in tests.
---

# Verify CutDeck in live Premiere

CutDeck lets agents and scripts control Premiere. Every Premiere command is one entry in the
table `cutdeck/driver_commands.py`; a command family's code lives in `cutdeck/commands/`
(`pieces.py`: paste_from, paste_pieces, arrange). It runs through the helper
(`python -m cutdeck.helper`, port 7891); panel commands go on to the CutDeck UXP panel inside Premiere, and the menu, key, screenshot and
AI Assistant commands run in the helper itself. Tests use a fake Premiere
(`tests/fakes/premiere.cjs`); this skill drives the real one.

Everything goes through one script:

```
python .claude/skills/verify-cutdeck/scripts/cdv.py <step>
```

Set `PYTHONIOENCODING=utf-8` first (Thai sequence names break the Windows console otherwise).
Run from the repo root. Every step exits 0 on PASS and prints `FAIL <why>` otherwise.

Not covered here: the transcript web editor (`uvicorn transcribe.editor.server:app`, port 8000)
and SubtitleDesk (`python -m subtitle_desk.server --port 8010`), see `.claude/launch.json`;
and the GPU transcription pipeline. `VERIFY.md` maps features to their automated tests; this
skill is the live check on top.

## Hard rules

- **One Premiere, one panel, one helper.** The panel connects only to port 7891, so two
  verifications cannot run side by side. Never run two at once. Helper-only commands
  (`screenshot`, `list_menu`, `list_key_commands`) can be tried on a second helper
  (`python -m cutdeck.helper --port 7899 --jobs-dir <scratch dir>`), which has no panel.
- **The user's project is open and is real work.** Edit only the scratch sequence
  `CutDeck verify (scratch)`. Read anything; write nothing else. Undo your own edits.
- **Never export** (`export_sequence`) and never open, close or quit projects: the user does those.
- Never save the project except as the first half of `launch --reload-panel`.
- Kill only what you started (cleanup does this by pid). Never kill Premiere or python by name.

## Launch

Premiere must already be running with a project open. An agent cannot do that step: if
`doctor` fails "Premiere Pro is running", ask the user.

```
cdv.py launch                     # start a helper if none answers; wait for the panel
cdv.py launch --restart-helper    # after changing cutdeck/**/*.py: helper restarts in place on this code
cdv.py launch --reload-panel      # after changing uxp/cutdeck/*: save project, reload panel, wait
```

Ready means `launch` printed `PASS panel connected, 33 panel commands` (the count is what the
panel registered; it equals `len(PANEL_COMMANDS)` once the panel runs this checkout, which
doctor checks) and `doctor` exits 0. The panel reconnects on its own within 5 to 30 s
after a helper restart. If it never connects, the panel is closed: ask the user to open
Window > UXP Plugins > CutDeck (or load it in UXP Developer Tool).

## Doctor

```
cdv.py doctor
```

Read-only. Checks, in order: Premiere running, helper answering, panel connected as the driver,
panel offering every panel command (else it runs older code: `launch --reload-panel`), a
sequence readable, the current selection (a non-empty selection means transform commands WILL
edit those clips), the helper started after the newest `cutdeck/**/*.py` change (else
`launch --restart-helper`), and that UXP Developer Tool loads this checkout's `uxp/cutdeck`.
Run it first, and again whenever anything looks off.

## Drive

```
cdv.py start --label <what>       # new run: evidence folder; remembers the user's active sequence
cdv.py scratch                    # reset "CutDeck verify (scratch)" (9:16, 30 fps): clear it,
                                  #   place a 6 s test clip (V1@0, A1@0), open it
cdv.py call <command> '<json>' [--label x]   # run one command, record request + result
cdv.py shot <label> [--frame]     # Premiere window PNG; --frame adds the scratch frame PNG
cdv.py cleanup [--keep-helper]    # give Premiere back (see Cleanup)
```

`call` takes any command name from `cutdeck/driver_commands.py` (the MCP tool name without
`premiere_`) with its arguments as JSON. It sends the helper the same `premiere` request MCP tools,
`premiere_cli` and `Backend().premiere` send, through the standard-library client in
`cutdeck/helper_protocol.py` (tests hold its replies and errors equal to `Backend`'s). Handles to use:

- Sequences by name: `"sequence": "CutDeck verify (scratch)"`.
- Clips by id `V<track>@<start_ticks>` exactly as `read_timeline` prints them. After `scratch`:
  `V1@0` and `A1@0`, 1524096000000 ticks long (6 s; 254016000000 ticks per second; one frame
  at 30 fps is 8467200000).
- Menu items by path, e.g. `"Edit > Undo"`, from `list_menu`. Shortcuts by command name, e.g.
  `cmd.transport.sequence.end`, from `list_key_commands`.
- Undo your edit with `call menu_command '{"path": "Edit > Undo", "focus": null}'`. Never as keys:
  Ctrl+Z sent as keys does nothing.

Per-feature recipes: [features/README.md](features/README.md).

## Evidence

Each run writes `output/verify-cutdeck/runs/<run_id>/`: `run.json`, one `NN-<command>[-label].json`
per `call` (args, result or error, time), the `shot-*` PNGs, and `cleanup.json`. `output/` is
git-ignored. Proof standards:

- Drive the user path: `call` goes through the helper exactly like an agent's MCP tool. Never
  call panel internals or fakes.
- Record the action AND the state after it: a `read_timeline` (or `inspect_selection`) after
  every edit, and the undo with a read back to the original.
- For anything visible, `shot <label> --frame` before and after: the frame PNG is what the
  sequence renders (an empty frame renders transparent, which looks white).
- A command's own reply is not proof for menu and key commands: they only post a click or a
  key press. Read the result back.
- `doctor` output belongs in the report: it names the checkout commit the run proved.

## Cleanup

```
cdv.py cleanup
```

Reopens the user's sequence that `start` remembered, stops the helper only if this run's
`launch` started it (pass `--keep-helper` to leave it for the user), and closes the run. It never
deletes evidence, never saves the project, and never deletes the scratch sequence (no API can;
`scratch` reuses and resets it next run). It cannot undo edits: undo them yourself during the run.
Run it after every run, failed ones too.

## Helpers

- `scripts/cdv.py`: the steps above (`--help` on any step).
- `python -m cutdeck.live_check`: the panel/helper half of `doctor` on its own.
- `python -m cutdeck.premiere_cli <command> [target]`: one command from a terminal, no evidence.
- Route map and limits: `docs/PREMIERE_CONTROL_MAP.md`. Live API behaviour:
  `docs/PREMIERE_FACTS.md` (add a row for anything new you learn live).
