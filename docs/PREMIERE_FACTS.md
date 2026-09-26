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
| ↳ returns `undefined` | CATCH | Sporadic: in the razor step of a Protected Rough Cut (426 cuts, 7,650 clones in one transaction), clone 4,113 (A2, edge 1706.37 s) came back `undefined` and the cut stopped; the identical cut list then applied cleanly (426 cuts, read-back clean). Cause unknown. `nativeCut.js` now asks once more inside the same callback before failing; the read-back still checks every piece. | jobs d9b6e4aa, live 2026-09-24 |
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
| Graphic (text/shape) track item | CATCH | `getProjectItem()` gives **no project item**, so no Video Info / source size. Chain: Opacity, Motion (same 11 params, defaults Position/Anchor [0.5,0.5]), Vector Motion (`AE.ADBE Graphic Group`, 6 params: Position, Scale, Scale Width, Uniform, Rotation, Anchor), Text (`AE.ADBE Text`). Its anchor frame is the **sequence frame**: stored Anchor [0.5,0.5] = Effect Controls 960.0, 540.0 in a 1080p sequence. No text bounds. | Check Transform on a Graphic + Effect Controls, 2026-09-24 |
| Graphic Text layer (`AE.ADBE Text`, 22 params) | CATCH | Readable: [2] Position (normalized, e.g. [0.3119,0.4613]), [3] Scale, [4] Horizontal Scale, [6] Rotation, [7] Opacity, [8] Anchor Point ([0,0]). [0] **Source Text: `getStartValue()` fails**. No text width/height anywhere ([18]/[19] Parent Width/Height read 0). So the text's box can't be read from UXP; CutDeck **measures it from pixels** instead (`transform/frameBounds.js` + helper `frame_bounds`: frame with the clip on vs off). [2] Position **and** [8] Anchor Point are stored **as fractions of the Graphic canvas** (the sequence frame): [0.1120, 0.8700] = Properties 215.1, 939.6 and [0.1120, -0.0327] = 215.1, -35.4 in 1920x1080. `createSetValueAction` on text Position **works**: written -0.2791 read back -0.2791 (live Align Left, 18:30). | Check Transform on a Graphic, 2026-09-24 |
| Graphic Source Text (`AE.ADBE Text` [0]) reads | ABSENT | `getStartValue()` resolves **empty** (no error). `getValueAtTime(t)` throws "not supported for these value types. Use GetKeyframeAtTime". `getKeyframePtr(t)` throws "Illegal Parameter type". So the font, size and string can't be read from the panel. The **saved `.prproj`** has them (row below). | Check Transform, live 2026-09-24 |
| Source Text in the saved `.prproj` (`cutdeck.prproj_reader`) | WORKS | Read offline, no Premiere needed. Each text clip is a `Graphic` clip whose `AE.ADBE Text` filter has an `ArbVideoComponentParam` named `Name=Source Text` (real element names: `Name`, `StartKeyframeValue` base64; **not** `ParamName`). The blob is a **FlatBuffer**: root f0 → document; document f0 = vector of runs, f1 = vector of font names; run f0 = its text, f1 = style table. Decoded on 9 layers: `Hello`/`ArialMT`, Thai `สวัสดี`/`Sarabun-Regular` (PostScript name, plain UTF-8), two lines = `
` between them, mixed styles = **one run per style** (`Hello` + ` World`). Style table: f1 = font size float (**omitted at 100**, present for 150), f8 = tracking float (200), f14 = faux-bold flag (`Arial` stays `ArialMT`, bold is a flag not a font), f2 = fill colour and f4 = stroke colour (each a table of three one-byte channels, f0 R / f1 G / f2 B, **a channel left out = 255**; no f2 = white fill; proven with red `255,0,0`, green `0,255,0`, `200,100,50` and a blue `0,0,255` stroke). Colour can change per letter (`h` `200,100,50` then `i` `42,0,255`): one run each. Keyframed Source Text: extra `<Keyframes>` element `ticks,base64;ticks,base64;`, each value a full blob. Keyframe time is **source time**: seconds into the clip = time minus the clip's `InPoint` (a new Graphic's InPoint is 3599.971 s). Proven on a clip at timeline 10.01 s with keyframes set at 0, 1 and 3 s: times 3599.9714 / 3600.9724 / 3602.9744 = 0 / 1.001 / 3.003 s in (23.976 fps timecode), so it does not depend on where the clip sits on the timeline. Only untrimmed clips were tried. The saved `StartKeyframeValue` text is **not** the first keyframe's (`fadsfds` stored, `a` keyframed at 0 s): for a keyframed layer read `keyframes`. **Per-run font:** a run's style f0 is the index into the font-name vector (omitted = 0); proven on a Thai + Arial + Arial Italic layer (4 runs, 3 fonts: `Sarabun-Regular`, `ArialMT`, `Arial-ItalicMT`), so the reader returns `runs` with a font and size each. **Stroke:** f4 keeps a stroke colour table even when the stroke is off (baseline layer), f5 = the on flag (1), f6 = stroke width float (4.0 default; proven 5 and 20). **Leading:** document-level f6 float (150.0 proven; absent = 0). **No opacity:** Premiere's Type panel has no fill or stroke opacity, and layers saved with a stroke changed only width, so there is no alpha field to decode. **Repeated blobs:** an identical Source Text binary is written once; later copies are an empty `StartKeyframeValue` with the same `BinaryHash` (3 of 26 layers in the probe), so read it by hash. Reader also returns per run `tracking` (float, 0 omitted), `bold` (f14 flag), `fill` and `stroke`. **Alignment:** document f4, omitted = left, **2 = centre** (user-confirmed), 1 = right (inferred: the only other alignment set). **Shadow:** document f11 flag (set only on the user's shadow layer). **Italic / underline:** style f15 = faux italic, f16 = underline (the layer had `ab` italic, `cd` underline: f16 on `cd` only; f15 was on both runs, and f14 bold was off there). Not decoded: stroke/shadow settings beyond the flag, the other style fields. | probe.prproj, 9 text layers, 2026-09-25 |
| Motion / Opacity / Text transform in the saved `.prproj` (`cutdeck.prproj_reader`, `effects[].params`) | WORKS | A clip's `AE.ADBE Motion` and `AE.ADBE Opacity` components are written **only once edited**: an untouched clip has no effects at all. Motion param indices equal the panel's `PARAM_INDEX`: 0 Position, 1 Scale (the file names it `Scale Height`), 2 Scale Width, 4 Rotation, 5 Anchor Point, 7 to 10 Crop L/T/R/B (percent); Opacity [0] is percent. A value is the second comma field of `StartKeyframe` (`-91445760000000000,<value>,...`, a sentinel time; a point is `x:y`). **`CurrentValue` is empty for Position, Rotation and Anchor and can be stale** (a default Text clip: `CurrentValue` 92, `StartKeyframe` 100), so don't read it. **Coordinate spaces confirmed offline:** Position 100,200 on a 1280x720 clip in a 1920x1080 sequence saved as 0.05208:0.18519 (/1920x1080); Anchor 100,200 saved as 0.078125:0.27778 (/1280x720). An animated param adds `IsTimeVarying` and a `Keyframes` element, records `ticks,value,...` joined by `;`; keyframe time is source time, so clip time = time minus `InPoint` (keyframes at 0 s and 2 s read 3599.971 / 3601.973 on a clip with InPoint 3599.971). A Text layer (`AE.ADBE Text`) carries its own transform group in the same format: [2] Position, [3] Scale, [4] Horizontal Scale, [6] Rotation, [7] Opacity, [8] Anchor. A Graphic in this file has **no** `AE.ADBE Graphic Group` (only Motion, Opacity and Text appear), unlike the live run. Uniform Scale (index 3) is not decoded. | probe.prproj Sequence 04, 2026-09-26 |
| Text layer space vs Premiere's blue text box | CATCH | In the text layer's own anchor space (Anchor Point px = stored × sequence size), the blue box **left edge is x = 0 and the baseline is y = 0**. Hand-snapped anchor, testt1231, LucidaCalligraphy-Italic 100: box x 0 to 433.06 = the sum of the glyph advances (fontTools, exact). Bottom 15.67 = the lowest glyph point ("3", 15.674). Top −87.05 matches no hhea/typo/win/head value (typo ascender 85.55): the rule for the top is **unknown**, and a second font is needed to fit it. The letters measured from frames sit at x 10.6 to 429.6, y −70.2 to 16.8. | hand snaps + frames, live 2026-09-24 |
| `Exporter.exportSequenceFrame(seq, time, name, folderPath, w, h)` | CATCH | Works (PNG, RGBA, **transparent** where nothing is drawn). **Resolves `true` in ~100 ms before the file exists**, and draws the timeline as it is when it renders, not when called: switching a clip off straight after swapped the two frames. Wait for the file (exists + stable `getMetadata().size`) before changing the timeline. Bare file name + folder, as Adobe's sample. | `transform/frameBoundsProbe.js`, live 2026-09-24 |
| `exportSequenceFrame` repeatability | CATCH | Two saves of the same frame are **not always pixel-identical**: another clip's video differed by 1/255 in 3 pixels (inside a different clip, ~1000 px from the text). With a zero-tolerance diff that stretched the measured text box from 0-419 to 0-1315, so every Graphic Align landed wrong. `cutdeck/frame_bounds.py` now takes the box from clear changes (>16) and grows it only by faint changes within 8 px. The helper keeps the latest pair as `cutdeck-bounds-last-on/off.png` in the panel's temp folder. | kept frame pair, live 2026-09-24 20:07 |
| `VideoClipTrackItem.createSetDisabledAction(bool)` | WORKS | Takes effect at commit; `isDisabled()` reads it back at once. One undo step each. | `transform/frameBoundsProbe.js`, live 2026-09-24 |
| `isAdjustmentLayer()` | WORKS | Exists on **track items only**, not on `ProjectItem`. | HANDOFF_CUTDECK_AL_FX_NEXT |
| `getTrackItems(TrackItemType.CLIP, false)` | WORKS | Pass `Constants.TrackItemType.CLIP` from runtime `ppro.Constants`, never a literal. | `host/trackItems.js` |
| `getSpeed/isSpeedReversed/getType` | UNPROBED | Used as refusal gates in the cut planner. | `nativeCut.js` |
| `AudioClipTrackItem.isDisabled()` | WORKS | Reads each clip's own state: on sequence "test" (6 audio tracks, the same recording on A1–A4) A1's clip read enabled and the clips on A2–A6 read disabled, so Rough Cut's JSON read analysed A1 only. A failed read would count as "on". | Rough Cut job e8b96443 `source.xml`, live 2026-09-24 |
| `AudioTrack.isMuted()` | OPEN | Called live without error; all 6 tracks of "test" read not-muted, which is also what a failed read defaults to, so a muted track still has to be tried. With no Reference Audio chosen, the first un-muted track with clips is analysed (the XML route used the export's track `<enabled>`). | Rough Cut job e8b96443, live 2026-09-24 |

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
| Motion write via `createSetValueAction` (panel nine-point anchor, Position compensated) | WORKS | Takes on Motion (a fixed effect): Anchor and Position saved, one Ctrl+Z restores the exact original. All nine targets, on cropped 10/20/30/40 clips, scale {100 uniform, 50 × Width 80 non-uniform} × rotation {0, 90, 15}: saved anchor on the target, rendered picture moved 0.00 px by the panel's model (`Position + R(rot)·Scale·(p − Anchor)`, rotation clockwise, Uniform off: Scale = height, Scale Width = width). No jump in the Program Monitor (top-left, watched live). | `cutdeck.prproj_anchor_check`, `test_projects/t_*.prproj`, 2026-09-26 |
| Motion write of typed Position X / Rotation / Scale (panel fields) | WORKS | Saved exactly as typed (700 px with Y untouched, 30°, 60%), one clip; three Ctrl+Z restore the original values. Effect Controls readout not reported. | `cutdeck.prproj_anchor_check`, `test_projects/p2_*.prproj`, 2026-09-26 |
| clip geometry: align, distribute, rendered bounds | ABSENT | Not in the API at any version (grep); CutDeck does the geometry itself. | transform-panel-plan Part 1 |

## Markers, events

| API | Status | What happens / the rule | Proof |
|---|---|---|---|
| `Markers.createAddMarkerAction(name, "Comment", start, duration)` | WORKS | 432 ranged markers in one transaction; one Ctrl+Z removed all; read-back matched. | Ledger 09-24 Phase 2 |
| ↳ 5th argument `comments` | WORKS | Through the helper v2 driver: `Markers.getMarkers(sequence)` (static, async), then one transaction adding a marker with name + comment; the comment shows in Premiere's Markers panel. One undo step. | `premiere_cli add_markers`, live 2026-09-24 (seen by the user) |
| `EventManager.addGlobalEventListener(SequenceEvent.ACTIVATED)` | WORKS | Fires on sequence switch. | `features/align.js`, ledger 09-24 |
| global `SequenceEvent.SELECTION_CHANGED` | BROKEN | Doesn't fire globally. Attach it to the sequence (`EventManager.addEventListener(seq, …)`) and move it on every switch. | Ledger 09-24 |

## UXP platform and the panel host

| Fact | Status | Detail | Proof |
|---|---|---|---|
| Multiple panels | CATCH | One plugin = **one shared document and JS context**. There's no per-entrypoint `main`. Extra panels are containers moved in by `entrypoints.setup({panels: {id: {show(root)}}})`. They share `localStorage` and the DOM id namespace. Needs `ipc.enablePluginCommunication`. | transform-panel-plan Part 2 (manifest schema) |
| `hide()` / `destroy()` hooks | BROKEN | Adobe documents them as not working yet in Premiere; don't rely on them. | transform-panel-plan Part 2; panel review |
| Helper v2 driver round trip | WORKS | The reloaded panel registered as the helper's Premiere driver ~30 s after Premiere started (it restarted the old `cutdeck-xml-4` helper itself). `premiere_cli read_sequence` returned the live sequence (6 A / 3 V tracks, 8467200000 ticks/frame); a refusal from the panel (no In/Out) came back to the terminal as the error. | live 2026-09-24 |
| WebSocket to the helper, cold start | CATCH | An installed plugin can get "Permission denied to the url ws://…" with a correct manifest until UDT has loaded a dev build that session (timing). `core/rpc.js` retries connecting 5× over ~3 s; never resends a sent request. | Ledger 08-26 + 09-16 |
| WebSocket message size | — | The helper's limit, not UXP's: was `max_size` 65536 (~200 clips with long paths ≈ 54 KB); 16 MiB since helper v2 (`cutdeck-xml-5`), for Rough Cut's JSON read of the audio tracks. | HANDOFF_CUTDECK_NATIVE_SYNC; docs/arch-design-helper-v2.md |
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
