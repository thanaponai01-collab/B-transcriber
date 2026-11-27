# Premiere timeline verbs by route tier (27.0.0, 2026-11-27)

Goal: for every timeline verb, know which route reaches it and which one an agent should use.
Tier 1 is UXP by clip id. It needs no focus and leaves the user's mouse and keyboard alone. Tier 2 is
the menu or the Control Surface, and it needs the timeline focused. Tier 3 is keys or Premiere's
dialogs, and it takes the keyboard (and the mouse, for dialogs). Each tier-2 or tier-3 verb was tried
as a tier-1 composite and tested live against its existing route. The test passes when both routes
give the same `read_timeline` and one Edit > Undo restores the before-read. The rows are in
[PREMIERE_FACTS.md](../PREMIERE_FACTS.md) *Timeline verbs*.

## Sources

`python tools/adobe/timeline_verbs.py` regenerates the source columns from the raw files:

| Source | What it holds | Count |
|---|---|---|
| `reference/adobe/api/premierepro.txt` | 27.0.0 typings, one line per member | 788 members |
| Third-party allow-list in `Adobe Premiere Pro.exe` 27.0 | What a third-party panel may call, by backend class | 96 classes, 676 entries |
| Control Surface catalog `commands-35300-29954531-1.json` | Premiere's command table, listed by the native plugin | 1,305 ids (**26.5.2**, not re-run on 27.0: the plugin is not installed) |
| The user's `Thanapon Bas shortcuts 9.kys` and Premiere's `Defaults.kys` | Bound commands | 439 and 371 |
| Live Win32 menu bar (`cutdeck.menu.list_items`) | Every menu item | 474 |

The allow-list names backend classes (`TrackItem`, `SequenceEditor` with `createAddItemAction`), not
the typed public ones (`createOverwriteItemAction`). So a verb's tier-1 cell names typed members, and
the allow-list only rules a member out where FACTS has a live row. Name collisions were dropped by hand
(`Marker.getTarget` is not track targeting). The 27.1 preview typings add only razor
(`SequenceEditor.createRazorTrackAction`, `createRazorAllTracksAction`).

## Matrix

"Live 11-27" is this run; other results cite their FACTS rows. MATCH means same read, and one Undo for
each route. Every 11-27 run used one V1+A1 track pair, no cover clip, and one direction per verb, so
the "Use" column holds for that layout. On a layered timeline list every track's clips in the call,
covers included (FACTS: a cover spanning an edit changes what W/Q and a ripple do). Nest, three-point
and frame hold were not prototyped live: their tier-1 candidates need two or more transactions by
existing FACTS rows, so they cannot pass the one-Undo check.

| Verb | Tier 1 (UXP by clip id) | Tier 2 (menu / Control Surface) | Tier 3 (keys / dialogs) | Live result | Use |
|---|---|---|---|---|---|
| Place | `createOverwriteItemAction`, `createInsertProjectItemAction`, `insertMogrtFromPath` (`place_media`, `place_text`) | Clip > Insert / Overwrite (needs a Source monitor clip) | `,` `.` | LIVE 11-21 (tier 1) | **1** |
| Move | `createMoveAction` (`edit_clips` move; move V and A) | Control Surface `cmd.timeline.nudge.*` | Alt+←/→ nudge (`cmd.timeline.nudge.*`) | LIVE 11-21 | **1** |
| Ripple delete | `createRemoveItemsAction(sel, true, ANY)` (`edit_clips` remove `ripple: true` on V and A) | Edit > Ripple Delete | Shift+Delete | Live 11-27: MATCH with the key; the menu did nothing 1 run of 2 | **1** |
| Ripple trim | composite: `trim_out` + `move` every later clip, one call | Trim Edit + toggle trim type + nudges | W / Q | Live 11-27: MATCH with W (after the key fix) | **1** |
| Roll | composite: shrink one side, then extend the other, one call | Sequence > Trim Edit + Ctrl+←/→ | N tool, Shift+W/Q | Live 11-27: MATCH | **1** |
| Slip | composite: `trim_out`, `move`, `trim_in` on V and A, one call | Control Surface `cmd.timeline.slip.*` | Ctrl+Alt+←/→ | Live 11-27: MATCH (needed the guard lift below) | **1** |
| Slide | composite: next `trim_in`, clip `move`, previous `trim_out`, one call | Control Surface `cmd.timeline.slide.*` | Alt+, / Alt+. | Live 11-27: MATCH | **1** |
| Razor | none on 27.0. The composite is `place_media` over the clip + `edit_clips` fix-up: same read, **2 Undos**, a new right piece without the original's effects, and it overwrites one media length after the cut. `cut_copy` razors a **copy** only. | Sequence > Add Edit (to All Tracks); Control Surface `cmd.sequence.razorateditline(.all)` (one live run, 26.5.2) | Ctrl+K / Ctrl+Shift+K | Live 11-27: composite fails the Undo check | **2** (menu) until 27.1's `createRazorTrackAction` |
| Lift (In/Out) | composite: `trim_out` / `trim_in` / `remove` on each clip in range, one call | Sequence > Lift | `;` | Live 11-27: MATCH for a range that crosses an edit. A range inside one clip needs a razor | **1** across edits, **2** inside a clip |
| Extract (In/Out) | composite: the lift ops + `move` everything later, one call | Sequence > Extract | `'` | Live 11-27: MATCH (range across an edit) | **1** across edits, **2** inside a clip |
| Link / unlink | none (no getter or setter in typings or allow-list) | Clip > Link / Unlink; Control Surface `cmd.clip.linkaudioandvideo` | Ctrl+L | LIVE 11-21 (menu; the item's label is the read-back) | **2** |
| Group | none | Clip > Group / Ungroup | Ctrl+G | UNPROVEN: the 11-25 run pressed Ctrl+Shift+G (Shift bug), so no group was made | **2** (menu), effect unknown |
| Targeting | none (no getter or setter; `createSubsequence(ignoreTrackTargeting)` only reads it) | Control Surface only: per-track `cmd.tlnav.toggle.target.video.1`-`.8` / `.audio.1`-`.8` (no menu item, no binding) | Ctrl+0 / Ctrl+9 toggle all | LIVE 11-25 (key); not readable | **3**, and avoided: tier-1 edits name each clip, so targeting does not matter to them |
| 3-point overwrite / insert | composite: `createSetInOutPointsAction` on the project item, commit, then overwrite / insert (FACTS: two transactions) | Clip > Overwrite / Insert after Match Frame | `.` `,` | overwrite LIVE 11-25 (key). Tier 1 not run here: it is two transactions by FACTS, so 2+ Undos | **1** for placing a source range by id (`place_media`); **3** when the Source monitor's marks are the input |
| Speed / reverse | none (`getSpeed`, `isSpeedReversed` only; no setter) | none (Speed/Duration opens a dialog) | Ctrl+R dialog (`set_speed`) | LIVE 11-21 (dialog) | **3** |
| Nest | none for a selection. `createSubsequence` + lift + place of the sequence is several steps | Make Subsequence (menu) | Clip > Nest... dialog (`nest_clips`) | LIVE 11-21 (dialog) | **3** for Nest; **1** for `make_subsequence` (a range) |
| Frame hold | none (`read_timeline` cannot see a hold). `frameHold.js` places an exported still instead: a different result | Clip > Video Options > Add Frame Hold | Ctrl+Alt+H (user binding) | LIVE 11-25 (menu; read from the saved `.prproj`) | **2** |
| Effects, transitions | `ComponentChain` append/insert/remove, `FilterFactory`, `createAddVideoTransitionAction` | Apply Video Transition | Paste Attributes dialog (`paste_attributes`) | LIVE 11-21 | **1**; **3** only to copy many clips' effects at once |
| Keyframes | `ComponentParam.createAddKeyframeAction`, `createSetTimeVaryingAction`, interpolation | none | none bound | LIVE 11-21 | **1** |
| Text | `insertMogrtFromPath` with baked text (`place_text`); `MogrtText` write BROKEN on 27.0 | Graphics > New Layer > Text | typing in the Program Monitor (`edit_text`) | LIVE 11-21 / 11-27 | **1** to place; **3** to edit text already on the timeline |

## Composite recipes (one `edit_clips` call, one Undo)

Times are relative. `d` is the change in ticks and must be a whole frame. Run live: the +d direction of
each, and lift/extract over a range that crosses one edit. The −d direction and a `remove` inside a lift
are the same ops, not yet run. List the V and the A clip
for every op, because linked audio does not follow. Put a shrinking op before an extending one, so no
clip ever overlaps a neighbour.

- **Ripple trim** a clip's end by `d`: clip `trim_out` −d, then every later clip on the edited tracks `move` −d (earliest first).
- **Roll** the edit between X and Y by +d: Y `trim_in` +d, then X `trim_out` +d (for −d, X first).
- **Slip** a clip by −d (source earlier, key "right"): `trim_out` −d, `move` +d, `trim_in` −d, all on the same clip.
- **Slide** clip B right by d: next clip `trim_in` +d, B `move` +d, previous clip `trim_out` +d.
- **Lift** [i, o): a clip that ends in the range `trim_out` to i, one that starts in it `trim_in` to o, one inside it `remove`.
- **Extract** [i, o): the lift ops, then every clip that starts at or after o `move` −(o − i), on every track.

## Clip ids

CutDeck's id `V<track>@<start>` is a position, not an identity: no `TrackItem` member returns a
stable id (allow-list and typings). Live: a tail trim keeps the id, and a head trim changes it.
A split gives the right half a new id, and a ripple changes every later clip's id. A name set with
`rename` survived all four, and a split copied it onto both halves. Re-read ids after each edit, and tag
a clip by name when it must be followed through a series of edits.

## Found on the way (fixed on this branch)

- `cutdeck/keys.py` sent every bare letter with Shift. W went out as Shift+W, which rolled the edit
  instead of ripple-trimming it. This also explains the old rows where Ctrl+Z did nothing (it went out
  as Ctrl+Shift+Z, Redo), Ctrl+Alt+Z failed, Q rolled, E disabled a clip, and I/O did not set marks.
  So do the Ctrl+G group, Ctrl+Alt+T lock and V tool-key rows. Those rows are flagged; they were not re-run.
- `edit_clips` refused a clip that appeared twice in one call. The guard had no live basis, and it
  blocked slip and extract as one Undo. It is gone; several ops on one clip apply in list order.

Not fixed: `keys.active_kys()` reads `~\Documents`, but this PC's Documents folder is under OneDrive, so
CutDeck reads Defaults.kys instead of the user's set. Every verb key in the matrix has the same
binding in both.

## Left to the user

- Installing the native Control Surface plugin (admin rights and a Premiere restart). For these
  verbs, the catalog (26.5.2) has commands with no menu item and no binding in either .kys:
  per-track targeting (`cmd.tlnav.toggle.target.video.1`-`.8`, `.audio.1`-`.8`), moving all targets
  up or down (`cmd.tlnav.move.all.target.*`), `cmd.sequence.splitclip`, the edit-point selections
  (`cmd.timeline.editpoint.rolledit`, `.rippletrimin/out`, `cmd.tlnav.select.nearest.edit.as.*`),
  `cmd.timeline.trackitem.linkmedia` / `unlinkmedia`, `cmd.clip.deleteeffects` and
  `cmd.effectcontrols.keyframes.clearall`. Per-track targeting is the only one a verb above lacks. A
  binding the user adds to the .kys would also reach these, without the plugin. Razor reaches UXP in 27.1.
- **Decided 2026-11-27 (user): tier-2 and tier-3 commands may bring Premiere to the front while the user works in it.**
  `key_command`, and `menu_command` with a `focus`, do (code read: `keys.run_focused` brings the window to the front before it focuses a panel; Undo/Redo with focus null only post). With the composites, only
  razor, link/unlink, frame hold, speed, nest and text editing still need such a route.
