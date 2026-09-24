# Premiere facts: what the UXP API actually does

The one place for **how Premiere behaved when CutDeck ran it**. Adobe's typings say what exists;
this file says what happens. Read it before writing panel code, and add a row whenever a live
run teaches something (see "Adding a fact" at the bottom).

**Look things up in this order:**
1. **This file.** Proven behaviour, catches and dead ends.
2. **`reference/adobe/api/premierepro.txt`** / **`api/uxp.txt`**: every declared member, one line
   each (`grep "^SequenceEditor\." reference/adobe/api/premierepro.txt`). Tags show `static`,
   `since`, and `NOT IN 26.2.1` (absent at the manifest's `minVersion` 26.2.0).
3. **`reference/adobe/docs/`**: Adobe's docs (Premiere classes under `ppro-reference/`, the UXP
   platform under `uxp-api/`, recipes under `resources/recipes/`).
4. **`reference/adobe/samples/`**: Adobe's own working panels, for real call patterns.

`node tools/adobe/check-api.mjs` fails if the panel uses a member name found in none of these
(run by `tests/cutdeck_adobe_api.test.cjs`).

**Status:** **WORKS** proven live · **CATCH** works, with a rule you must follow · **BROKEN**
throws or misbehaves, don't use it · **ABSENT** not in the API at any version, so design around it
or build it in the helper · **UNPROBED** declared, never run in this project · **OPEN** partly
run, question still open.

Installed Premiere: **26.5** (manifest `minVersion` 26.2.0). Dates are 2026. "Ledger" means
`TODO_LEDGER.md`.

---

## Transactions and Actions

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| `Project.executeTransaction(cb, label)` + `CompoundAction.addAction` | CATCH | **Create every Action inside the callback.** One made outside it throws "The script object is no longer valid." when added. | Ledger 09-24 native rough cut, Phase 4 run 1; `timeline/nativeCut.js` |
| `Project.executeTransaction` | WORKS | One transaction = one Ctrl+Z. 100 clones in one transaction are near-instant and one Ctrl+Z undoes all of them. | `syncProbe.js`, HANDOFF_CUTDECK_NATIVE_SYNC |
| `Project.executeTransaction` | OPEN | The same transaction took 1 ms on one run and 28 s on another; cause not found. `host/project.js runTransaction` logs lock wait / callback / commit time when a run takes over 0.5 s. | `host/project.js` comment, 09-24 |
| `Project.lockedAccess(cb)` | WORKS | Wraps the transaction; used by every write path. | `host/project.js` |
| State inside one compound | CATCH | **Structural changes made earlier in the same compound aren't visible yet.** `getTrackItems()` doesn't see them, and an overwrite still reads the project item's *old* In/Out marks. Commit, re-read, then act (P2). | Ledger 09-24 P2; ledger 08-26 issue #25 round 17; `adjustmentLayer.js` (destroyed real footage 09-21) |
| Object references across transactions | CATCH | References go stale across transactions (issue #18). Re-fetch sequence, tracks and items after each commit. | HANDOFF_CUTDECK_NATIVE_SYNC step 5 |
| `compound.addAction` while the target sequence is **open** | BROKEN (suspected cause) | Failed with "Illegal Parameter type" mid-razor on a 95-min, 1735-cut copy that was open. Cut the copy **closed**, open it at the end. The cause (live redraw staling items) is suspected, not proven. | Ledger 09-24, `tiw_Synced2` |

## Sequences

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| `Sequence.createCloneAction()` | CATCH | Copies the sequence. Must be its **own** transaction; find the copy afterwards (new guid, or by name after rename). | `syncProbe.js`, `nativeSync.js` |
| `ProjectItem.createSetNameAction` (on the sequence's project item) | WORKS | Renames the sequence. | `nativeSync.js` |
| `Project.createSequenceFromMedia(name, [clip], bin)` | CATCH | Settings match the footage (tpf, frame size), but it **pre-places the whole clip** (1 V + 4 A). Remove it before placing anything. | Ledger 09-24 P1 |
| `Project.setActiveSequence` / `openSequence` | WORKS | Opens the result for the editor (done last). | `nativeCut.js`, `nativeSync.js` |
| `Sequence.getTimebase()` | WORKS | Returns **ticks per frame** as a string (e.g. `"8475667200"` at 29.97). | HANDOFF_CUTDECK_NATIVE_ROUGH_CUT 2.2 |
| `Sequence.getInPoint/getOutPoint/getEndTime`, `get{Video,Audio}TrackCount`, `get{Video,Audio}Track` | WORKS | Plain reads. | `workflow.capture`, `nativeSync.js` |
| `Sequence.getFrameSize()` = `SequenceSettings.getVideoFrameRect()` | WORKS | Both give the same size. `RectF` is **width/height only, no x/y**. | transform-panel-plan Part 1/1a |
| `SequenceSettings.getVideoPixelAspectRatio()` | WORKS | Returns a **string** (`"1:1"`), so parse it. | transform-panel-plan Part 1a |
| `SequenceSettings` width/height fields | ABSENT | No plain `videoFrameWidth/Height`; use `getVideoFrameRect()`. | `transform/params.js`, `alLibrary.js` |
| `Sequence.getSelection()` | CATCH | Has failed on this build before. Fall back to scanning items with `getIsSelected()`. It also returns the linked audio too, so a probe on "the selection" reads only the first item. | `host/trackItems.js`; transform-panel-plan Part 1a |
| Out point: exclusive or inclusive? | OPEN | `timelineRange.js OUT_CONVENTION` is still `null`; run Check Timing (probe 1) before relying on it. | `timelineRange.js` |

## Placing, cloning, removing (`SequenceEditor.getEditor(seq)`)

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| `createOverwriteItemAction(projectItem, time, v, a)` | WORKS | **The placement route.** Video + every audio channel land together, **linked**, full length (or the project item's In/Out span, see P2). | `syncProbe.js`, HANDOFF_CUTDECK_NATIVE_SYNC |
| ↳ track index = track count | CATCH | Creates the track (there's no add-track call). **Only one new track per transaction works**; several placements onto not-yet-existing tracks in one transaction failed ("could not find the one for V10"). Create each new track with its own single placement, then batch the rest. | `adjustmentLayer.js` 09-24 |
| ↳ argument type | CATCH | Pass the **plain** `trackItem.getProjectItem()` result. A `ClipProjectItem.cast(...)` object gets "Invalid parameter." | Ledger 09-24 run 1; `roughCutProbe.js` |
| ↳ landing inside an existing clip | WORKS | Overwrite cuts away what it covers and **keeps both sides**, so it works as a razor. Rough Cut clones a 1-frame filler onto each cut edge this way. | Ledger 09-24 Phase 4 run 3 |
| ↳ overlapping placements on one track | CATCH | Each overwrite clips the one placed before it. Give overlapping placements separate tracks. | `adjustmentLayer.js` 09-22 |
| `ClipProjectItem.createSetInOutPointsAction` + overwrite | CATCH | Places exactly the marked span, but only as **two transactions**: set the marks, commit, then overwrite. Restore the marks after. After one committed In/Out, **many overwrites in one transaction work** (21 ALs placed and verified, 6–7 undo steps incl. the preset). | Ledger 09-24 P2; Adj & FX run 09-24 |
| `createCloneTrackItemAction(item, offset, vOff, aOff, alignToVideo, isInsert)` | CATCH | Clones **one item only**: video without its audio (clone each audio item yourself, `alignToVideo=false`). Onto its own track it **overwrites** what's there, so never clone in place. Returns an Action, not the new item; re-read to find it. Clones keep effects and keyframes. Pieces are **not linked** (the API can't link). | Ledger 09-24 P3/P4/P5; `syncProbe.js` |
| ↳ same track, `isInsert=false`, clone + trim to split | BROKEN | Dead end: `timeOffset=0` is a no-op, and any other offset fixes `start − in` so no trim sequence can close it. Proven algebraically and live (issue #18, 14 rounds). | Ledger 08-26 |
| ↳ `isInsert=true` | CATCH | A genuine native split, but it leaves a full-length duplicate per boundary; cleanup needs a second transaction. Rejected on arithmetic (hundreds of hours of timeline at 221 cuts). | Ledger 08-26 issue #25 |
| `createRemoveItemsAction(sel, ripple=false, mediaType)` | WORKS | Removes only that media type, leaves a gap, nothing else shifts. Call **once per media type** (VIDEO, then AUDIO). | Ledger 09-24 P5 |
| `createRemoveItemsAction(sel, ripple=true, ANY)` | UNPROBED | Cross-track ripple depends on sync-lock UI state the API can't read. Rough Cut closes gaps itself with `createMoveAction`. | HANDOFF_CUTDECK_NATIVE_ROUGH_CUT 3.2 |
| `TrackItemSelection.createEmptySelection(cb)` | CATCH | The selection is **only valid inside its callback**. Build the selection *and* the remove action inside it, inside the transaction. Adobe's eslint rule: `no-empty-selection-escape`. | `nativeSync.js` 09-23 |
| `createInsertProjectItemAction` | CATCH | Ripples: shifts every clip after `time`. CutDeck uses overwrite instead. | `adjustmentLayer.js` |
| razor / split, link / unlink, get linked partner, move to another track, add track | ABSENT | Not declared in the typings at any version (grep). Split = overwrite-as-razor; tracks come from overwrite at index = count. | HANDOFF_CUTDECK_NATIVE_ROUGH_CUT 2.4 |

## Track items (`VideoClipTrackItem` / `AudioClipTrackItem`)

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| `createMoveAction(t)` | CATCH | **Relative** shift (negative works). **Linked audio doesn't follow** (0 of 4): move every audio item yourself. Audio can move by half a frame (sub-frame start is fine for audio). | Ledger 09-24 P5; `syncProbe.js` |
| `createSetInPointAction(t)` | WORKS | **Head trim:** start and media In move together, end stays fixed. | Ledger 09-24 run 1 |
| `createSetOutPointAction(t)` | WORKS | Tail trim. | Ledger 09-24 P3 |
| `createSetEndAction` | BROKEN | Throws "The script object is no longer valid." on video and audio. Use In/Out marks + overwrite for length instead. | Ledger 09-24 run 1; panel review A1 |
| `createSetStartAction` | UNPROBED | Only tried in the dead-end clone recipe (issue #18). | Ledger 08-26 |
| `getStartTime/getEndTime` | WORKS | Sequence time, TickTime. | many |
| `getInPoint/getOutPoint` | WORKS | **Media-relative** (= source time). | Check Keyframes probe 09-23 |
| `getIsSelected()` | WORKS | The real getter. `item.isSelected` is `undefined` on this build (not an Adobe API). | transform-panel-plan Part 1a |
| `isAdjustmentLayer()` | WORKS | Exists on **track items only**, not on `ProjectItem`. | HANDOFF_CUTDECK_AL_FX_NEXT |
| `getTrackItems(TrackItemType.CLIP, false)` | WORKS | Pass `Constants.TrackItemType.CLIP` from runtime `ppro.Constants`, never a literal. | `host/trackItems.js` |
| `getSpeed/isSpeedReversed/getType` | UNPROBED | Used as refusal gates in the cut planner. | `nativeCut.js` |

## Project items, bins, import

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| `ClipProjectItem.cast(item.getProjectItem()).getMediaFilePath()` | WORKS | Works for every clip. | `syncProbe.js` |
| `FolderItem.cast(item)` | WORKS | Gives `createBinAction` / `getItems` on a bin. | `host/project.js asBinLike` |
| `Project.importFiles(paths, suppressUI=true, bin)` on a `.prproj` | WORKS | No dialog. Premiere wraps the import in a `<file>.prproj` bin; move items out, then remove the bin once it reads empty (2 undo steps). CutDeck creates Adjustment Layers this way from a patched seed project. | HANDOFF_CUTDECK_AL_FX_NEXT Task 1 |
| create Adjustment Layer / colour matte / synthetic media | ABSENT | No such call. See the import route above. | HANDOFF_CUTDECK_AL_FX_NEXT |
| `createSetScaleToFrameSizeAction()` | BROKEN | Probed: does nothing visible. No matching getter. | HANDOFF_CUTDECK_AL_FX_NEXT; capabilityProbe |
| `Metadata.getProjectColumnsMetadata(item)` | WORKS | JSON; `Column.Intrinsic.VideoInfo` = `"1280 x 720 (1.0)"`, images add `", Straight Alpha"`. Works with the column **hidden**. An AL reports its creation size. The only source-dimension route. | transform-panel-plan Part 1a, runs 1–3 |
| `Metadata.getProjectMetadata` + `uxp.xmp.XMPMeta` | WORKS | Used to read `Column.Intrinsic.VideoInfo` via XMP (`timeline/alLibrary.js`). The UXP typings declare `xmp` oddly, so trust the docs + this. | `alLibrary.js` |

## Time

| Fact | Status | Detail | Proof |
|---|---|---|---|
| Ticks per second | WORKS | **254016000000**, fixed. All math in BigInt (`host/ticks.js`); no float seconds touch an edge. | XML fixture `pproTicksOut`; `host/ticks.js` |
| `TickTime.createWithTicks(string)` | WORKS | Ticks as a **string**. `.ticks` reads back as a string. | `host/ticks.js` |
| Video placement | CATCH | Snap video starts to whole frames (`getTimebase()` ticks/frame); audio-only can keep the exact tick. | HANDOFF_CUTDECK_NATIVE_SYNC |

## Effects, components, keyframes

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| Component chain layout | WORKS | Index 0 = Opacity (`AE.ADBE Opacity`), 1 = Motion (`AE.ADBE Motion`, 11 params), same on Adjustment Layers. A new effect lands at index 2. | transform-panel-plan Part 1a |
| Motion param indices | WORKS | 0 Position `[x,y]` · 1 Scale % · 2 Scale Width % · 3 Uniform Scale (bool, **blank displayName**) · 4 Rotation ° · 5 Anchor Point `[x,y]` · 6 Anti-flicker · 7–10 Crop L/T/R/B %. Match on index/matchName, never displayName. | transform-panel-plan Part 1a |
| Position units | WORKS | Normalized to the **sequence** frame, per axis. | transform-panel-plan 2nd run |
| Anchor Point units | WORKS | Normalized to the clip's **source** frame (stored pixels; pixel aspect **not** applied). | transform-panel-plan 2nd/3rd run |
| Transform **effect** match name | OPEN | Never seen in a probe. | transform-panel-plan |
| `getStartValue()` / `Keyframe.value` | WORKS | Double-wrapped `{value: {value: X}}`, which the typings document, so it's a contract. | transform-panel-plan Part 1 #3 |
| `createKeyframe(value)` for point params | CATCH | Must be `new ppro.PointF(x, y)`; a plain `[x, y]` throws "Illegal Parameter type". | `effects.js`, UXPLogs 09-23 |
| Keyframe times | WORKS | **Source-media-relative**: a keyframe on the clip's first frame reads back as its `getInPoint()`. | Check Keyframes probe 09-23 |
| `Constants.InterpolationMode` values | CATCH | Runtime **LINEAR 0, HOLD 4, BEZIER 5**. The typings list them alphabetically (BEZIER, HOLD, LINEAR), so values inferred from the typings are **wrong**. Always read `ppro.Constants.*` at runtime. | Check Keyframes probe; HANDOFF_CUTDECK_AL_FX_NEXT |
| `PointKeyframe` interpolation | ABSENT | No getter; point params keep Premiere's default interpolation. | `uxp/cutdeck/README.md` |
| `VideoFilterFactory.createComponent()` result | CATCH | Declared as `{}`: no `getParam`. Insert, **commit**, then re-fetch the component from the chain to set params (two transactions). | transform-panel-plan Part 1 #4 |
| Motion (fixed effect) in presets | CATCH | Skipped by presets; animate the **Transform** effect instead. | `uxp/cutdeck/README.md` |
| clip geometry: align, distribute, rendered bounds | ABSENT | Not in the API at any version (grep); CutDeck does the geometry itself. | transform-panel-plan Part 1 |

## Markers, events

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| `Markers.createAddMarkerAction(name, "Comment", start, duration)` | WORKS | 432 ranged markers in one transaction; one Ctrl+Z removed all; read-back matched. | Ledger 09-24 Phase 2 |
| `EventManager.addGlobalEventListener(SequenceEvent.ACTIVATED)` | WORKS | Fires on sequence switch. | `features/align.js`, ledger 09-24 |
| global `SequenceEvent.SELECTION_CHANGED` | BROKEN | Doesn't fire globally. Attach it to the sequence (`EventManager.addEventListener(seq, …)`) and move it on every switch. | Ledger 09-24 |

## UXP platform and the panel host

| Fact | Status | Detail | Proof |
|---|---|---|---|
| Multiple panels | CATCH | One plugin = **one shared document and JS context**. There's no per-entrypoint `main`. Extra panels are containers moved in by `entrypoints.setup({panels: {id: {show(root)}}})`. They share `localStorage` and the DOM id namespace. Needs `ipc.enablePluginCommunication`. | transform-panel-plan Part 2 (manifest schema) |
| `hide()` / `destroy()` hooks | BROKEN | Adobe documents them as not working yet in Premiere; don't rely on them. | transform-panel-plan Part 2; panel review |
| WebSocket to the helper, cold start | CATCH | An installed plugin can get "Permission denied to the url ws://…" with a correct manifest until UDT has loaded a dev build that session (timing). `core/rpc.js` retries connecting 5× over ~3 s; never resends a sent request. | Ledger 08-26 + 09-16 |
| WebSocket message size | CATCH | `max_size` 65536 bytes; ~200 clips with long paths ≈ 54 KB. | HANDOFF_CUTDECK_NATIVE_SYNC |
| `navigator.clipboard.writeText` / `setContent({"text/plain": …})` | WORKS (docs) | The documented clipboard. `uxp.clipboard.copyText` is **not** an API (see `tools/adobe/api-allowlist.json`). Needs `clipboard` permission. | `reference/adobe/docs/resources/recipes/clipboard/` |
| `require("uxp").storage.localFileSystem` | WORKS | Missing from the UXP typings, but documented and used. | `helperStart.js`, docs |
| Plugin temp folder (UDT load) | — | `%TEMP%\Adobe\UXP\PluginsStorage\PPRO\26\Developer\com.cutdeck.xml\PluginData` | HANDOFF_CUTDECK_AL_FX_NEXT |
| Runtime errors | — | `%APPDATA%\Adobe\Premiere Pro\Logs\UXPLogs_*.log`, and UDT's DevTools console. | HANDOFF_CUTDECK_AL_FX_NEXT |
| A syntax error in `main.js` | CATCH | The panel draws half and can't be clicked. `tests/cutdeck_syntax.test.cjs` runs `node --check` on every file. | 09-23 |
| `typeof x === "function"` guards | CATCH | They silently skip a **wrong** API name. Check names with `tools/adobe/check-api.mjs`, not guards. | HANDOFF_CUTDECK_AL_FX_NEXT |
| Panel compositing, Premiere 26.3.2.2 | BROKEN (26.3) | A UXP panel painted nothing (DevTools confirmed). Not seen on 26.5. | Ledger 08-29 |

## Not UXP: ExtendScript / QE DOM

Retired. Premiere 26.3 silently ignores QE `razor`/`ripple_delete` on some installs, and the File > Scripts
menu is gone. ExtendScript is supported only through Sept 2026. Don't build on it (ledger 08-25).

---

## Adding a fact

After any live run in Premiere (a probe button, a feature's first real use, an error in UXPLogs):

1. Add or update the row: API, status, **what happened in one sentence**, proof (probe name /
   ledger entry / commit, and the date). If it overturns a row, change the row and say what the
   old claim was, so nobody re-derives it.
2. If a test fake models this behaviour (`tests/fakes/premiere.cjs` or a test's `fakeHost`),
   make the fake do the same thing, citing the row.
3. Long narratives stay in `TODO_LEDGER.md`; this file keeps the one-line result.
