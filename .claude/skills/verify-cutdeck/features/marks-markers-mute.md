# Marks, markers and track mute

An agent sets a sequence's In/Out marks, adds and removes sequence markers, and mutes a track
(the eye button for video, M for audio).

## Sub-features

- `marks` sets In and Out.
- `add-markers` adds markers (name, comment, time in seconds) to the ACTIVE sequence, one undo step.
- `remove-markers` removes markers by start tick.
- `mute` mutes or unmutes a track by name (`V2`, `A1`).

## How to get to it (user POV)

- MCP tools `premiere_set_in_out`, `premiere_add_markers`, `premiere_remove_markers`, `premiere_set_track_mute`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index; the scratch is the open sequence (`add_markers` takes no `sequence`).

- **Marks.** Run `C call set_in_out '{"sequence": "CutDeck verify (scratch)", "in_ticks": "254016000000", "out_ticks": "762048000000"}'`. A `read_timeline` shows `in_ticks` 254016000000 and `out_ticks` 762048000000.
- **Add a marker.** Run `C call add_markers '{"markers": [{"start_s": 2, "name": "cdv ทดสอบ", "comment": "verify"}]}'`. Reply `added` 1; a read shows one marker at `start_ticks` 508032000000 with that name (Thai kept) and comment.
- **Remove it.** Run `C call remove_markers '{"sequence": "CutDeck verify (scratch)", "starts_ticks": ["508032000000"]}'`. Reply `removed` 1, `markers` empty.
- **Mute.** Run `C call set_track_mute '{"sequence": "CutDeck verify (scratch)", "track": "V1", "muted": true}'`, then `C shot muted --frame`: the frame is fully transparent. Unmute with `"muted": false`; a read shows V1 `muted` false.

Proven 2026-11-22 with this skill, every step above (run `20261122-000256-maintain-timeline`).

## Gotchas

- `C scratch` does not clear marks, markers or mute: leave them as you found them, or read them first.
- Each mute and unmute is its own history entry in Premiere.
