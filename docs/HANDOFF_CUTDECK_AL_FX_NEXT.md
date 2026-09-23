# Handoff: CutDeck Adj & FX: automatic Adjustment Layer setup, then batch actions

**Written 2026-09-23** on branch `feat/cutdeck-transform-align` (the last commit before this
doc was `6913f76`). Read `CLAUDE.md` and `uxp/cutdeck/README.md` first.

## Where Adj & FX stands (all confirmed working in Premiere 26.5 by the user)

- **Adjustment Layer placement:** Click spans one AL over the selection, Ctrl+Click places one
  per clip, and Shift+Click makes 50/50 cut transitions that stack onto separate tracks when they
  overlap. The code is `uxp/cutdeck/timeline/adjustmentLayer.js`
  (`placeAdjustmentLayersOnTimeline`). Placed items are renamed `ADJ_<preset>…` (for example
  `ADJ_Zoom_16f`, `ADJ_InOut`) and colour-labelled from Settings.
- **Quick-effect presets:** you capture them from a clip and apply them onto the ALs.
  `uxp/cutdeck/timeline/effects.js` handles fixed values *and* keyframes. Keyframe times are
  source-media-relative. This was **proven** by the Check Keyframes probe on 2026-09-23: a
  keyframe on a clip's first frame reads back as its `getInPoint()`. So presets store the offset
  from the clip's first frame and replay it at the target's In point plus that offset.
  Interpolation numbers: LINEAR 0, HOLD 4, BEZIER 5. Point values must be written as
  `new ppro.PointF(x, y)`, because a plain `[x, y]` array throws "Illegal Parameter type".
- **Preset storage:** `uxp/cutdeck/presetStore.js` saves one `<name>.json` per preset in a folder
  the user chose. Removing a preset moves its file to `Removed/`. `localStorage` is only a cache.
  The user's library is at `F:\Me\1.All Pr&Ae\3-AnyMind\CutDeck\Effect`.

## Task 1: create Adjustment Layers without the manual setup

**The pain.** `placeAdjustmentLayersOnTimeline` throws at `adjustmentLayer.js` about line 798
when no matching AL exists. The user must then run File > New Item > Adjustment Layer, once
per resolution, and name each one `1920x1080`, `1080x1920` and so on. `findAdjustmentLayerItem`
matches the AL to the sequence using `Column.Intrinsic.VideoInfo`, falling back to the name.

**Proven facts to build on** (checked in `@adobe/premierepro@26.2.1`'s `premierepro.d.ts`; get
it with `npm pack @adobe/premierepro@26.2.1` into the scratchpad and open
`package/src/premierepro.d.ts`):
- There is **no** `createAdjustmentLayer`, color-matte or synthetic-media creation call anywhere
  in the API.
- `Project.importSequences(projectPath: string, sequenceIds?: Guid[]): Promise<boolean>`
  exists.
- `Project.importFiles(filePaths, suppressUI?, targetBin?, asNumberedStills?)` exists.
- `isAdjustmentLayer(): Promise<boolean>` exists on the project-item type (about d.ts line 264)
  and on `VideoClipTrackItem`. It is a better discovery test than matching by name.
- `createSetScaleToFrameSizeAction()` was probed earlier and does nothing visible, so an AL
  can't simply be rescaled.

**Candidate route (suspected, not probed):** ship a template project `CutDeck_Assets.prproj`
holding one tiny sequence per common resolution (1920x1080, 1080x1920, 3840x2160, 1080x1080),
each containing a correctly sized Adjustment Layer. When the active sequence's resolution has
no AL, call `importSequences` for that resolution's sequence. Premiere should bring the AL
project item in with it. Then move the AL into `CutDeck > ADJ & FX`, delete or keep the helper
sequence, and continue as usual. The fallback is `importFiles([template.prproj])`, which in the
UI opens the import-project dialog. `suppressUI` may or may not skip that dialog.

**Do this first:** follow the repo's probe-before-build rule (see `capabilityProbe.js` and the
user's memory notes). Build a guarded diagnostics-drawer button that answers these three
questions, and have the user run it before any production code:
1. Does `importSequences` on the template bring the AL project item along, and where does it
   land (root, or a bin named after the source project)?
2. Does the imported AL keep the right frame size, and does `isAdjustmentLayer()` return true
   for it?
3. Does it add one undo step, or several? Can the helper sequence be removed through the API?

Open questions for the user: where the template `.prproj` should live (the repo, or next to
their preset folder on F:), and which resolutions to ship. Unusual resolutions can't come from a
template. Say so plainly instead of pretending: keep the current manual message for those.

## Task 2: batch actions (pure UXP, lower risk)

These all reuse calls `effects.js` / `adjustmentLayer.js` already use successfully:
1. **Apply a preset directly to every selected clip.** No AL is involved; loop
   `applyCapturedPreset` over the selected track items. It returns `{ warnings }`, so gather
   them into the status line the way `doApplyPreset` in `main.js` does.
2. **Swap a preset on every CutDeck AL in the sequence or In/Out range.** Find them with
   `isAdjustmentLayer()` plus the `ADJ_` name prefix. Remove the components the old preset
   added, apply the new one, and rename the item `ADJ_<newPreset>…`.
3. **Strip CutDeck effects from a range.** Remove the ALs CutDeck placed (same identification
   as item 2). This deletes timeline items, so confirm the count in the status line before
   acting, and keep it a single undo step (one transaction).

Deciding which components the old preset added needs a rule. Suggestion: record the preset's
component matchNames on apply. The user must pick the UI placement (Adj & FX page vs Settings)
and whether swap and strip need a modifier key or a confirmation.

## Rules learned the hard way on this panel

- **Syntax-check after editing.** `main.js` can't be `require()`d off-host, so a syntax error
  only shows up in Premiere as a half-drawn, unclickable panel.
  `tests/cutdeck_syntax.test.cjs` now runs `node --check` on every plugin file.
- **Don't trust a `typeof x === "function"` guard to catch a wrong API name.** It just skips
  silently. Verify names against the d.ts.
- **Read Premiere's own log** for runtime errors:
  `%APPDATA%\Adobe\Premiere Pro\Logs\UXPLogs_*.log`.
- **Keep `panel/core/*` as the source.** Edit there, then run `scripts/sync_panel_core.py`.
  Only `core/panel.js` may touch the DOM (see `tests/panel_ui_contract.test.cjs`).
- **Tests:** `node --test tests/*.cjs` gave 190 passing tests at handoff time.
