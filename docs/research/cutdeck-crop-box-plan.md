# CutDeck Crop Box: plan

**Problem.** Cropping in Premiere means typing Crop L/T/R/B numbers over and over. The user
wants to drag a box on the picture, the way Photoshop does it, and see the result live in the
Program Monitor.

## 1. What the Transform & Align panel does today (traced)

| Layer | File | What it does |
|---|---|---|
| UI | `core/alignPanel.js` | Fields (Position, Scale, Rotation, Anchor) with scrub-drag, a nine-point anchor picker, Align to Frame/Selection, Distribute. Calls `intents.*` only. |
| Read | `transform/params.js` | Finds `AE.ADBE Motion` by matchName and reads params by **proven index**: 0 Position, 1 Scale, 2 Scale Width, 3 Uniform, 4 Rotation, 5 Anchor, **7-10 Crop L/T/R/B %**. |
| Model | `transform/edit.js` `clipModel` | Builds `{position, anchor, scaleX, scaleY, rotation}` plus `crop` and `source` size. Skips keyframed or non-square-pixel clips. |
| Math | `transform/geometry.js` | `sourceToSequence` / `sequenceToSource` (`Position + R(rot)·Scale·(p − Anchor)`), `visibleSourceRect(source, crop)`, `renderedBounds`. Live-proven to 0.00 px (PREMIERE_FACTS rows 142-147). |
| Write | `transform/apply.js` `applyMotionValues` | `createSetValueAction` in one transaction, so one Ctrl+Z undoes it. Takes any `PARAM_INDEX` field, crop included. |
| Frame grab | `transform/frameBounds.js` | `Exporter.exportSequenceFrame` → PNG. CATCH: it resolves before the file exists, so wait for the file. |

The panel already **reads** crop (for rendered bounds) but never **writes** it.

## 2. The hard limit: UXP can't draw on the Program Monitor

Checked `reference/adobe/api/premierepro.txt`: no overlay, gizmo, monitor-pointer or
monitor-zoom API. The only monitor members are `Sequence.get/setPlayerPosition` and
`SourceMonitor.*` (open/play). A helper process can't draw over Premiere's monitor either:
its position, zoom and pan are unknown. Per GEMINI.md rule 2, the panel won't fake this.

**What gets the closest:** draw the box on a **preview of the frame inside the panel** and
write Crop on every drag step, so the **real Program Monitor updates live** while you drag.
Your eyes stay on the Program Monitor; your hand drags in the panel.

> Built-in alternative, worth trying first: Premiere's **Crop** video effect (Effects >
> Transform > Crop) already has on-monitor handles. Click the word "Crop" in Effect Controls
> and drag the box corners in the Program Monitor. Whether Motion's own Crop (params 7-10)
> gets handles in 26.5 is unverified; check in Premiere.

## 3. Design

```
[Crop Box section in Transform & Align]
  ┌───────────── preview <img> (exportSequenceFrame PNG) ─────────────┐
  │   dashed outline = full uncropped source (cropQuads.full)          │
  │   solid box + 8 handles = visible rect (cropQuads.visible)         │
  └────────────────────────────────────────────────────────────────────┘
  L [  ] T [  ] R [  ] B [  ]   Reset   ☐ Live while dragging
```

1. **Select a clip**, then click *Grab frame*. `exportSequenceFrame` at the playhead
   (`getPlayerPosition`) at preview size, wait for the file, show it in an `<img>`.
2. **Overlay** as absolutely positioned `div`s (box, handles, outline). No canvas
   `drawImage` (unproven in UXP).
3. **Drag** a handle or the inside of the box: pointer → `previewToSequence` →
   `dragCrop` / `moveCrop` (`transform/cropBox.js`) → new crop %. Works at any scale and
   rotation, because it maps back through `sequenceToSource`.
4. **Write** with `applyMotionValues(..., [{ item, name, values: cropToMotionValues(c) }])`.
   - *Live while dragging* on: write at most every ~100 ms. Premiere redraws the Program
     Monitor on each commit.
   - On release: one last write. **Undo problem:** every live write is its own undo step.
     Fix to prove live: on pointerdown remember the start crop; on release, if the steps
     can't be merged, tell the user "N undo steps" or keep Live off by default.
5. **Preview staleness.** The grabbed frame shows the picture already cropped, so the
   cropped-away area is blank. v1: the dashed outline shows where it is. v2 (optional):
   grab with crop set to 0 in a temp transaction, then undo it. Needs a live check that
   the undo is clean.
6. **Refuse** (reuse `clipModel` skips): keyframed crop, non-square pixels, Graphics (text
   canvas is the whole frame), more than one clip selected.

## 4. Slices and checks

| # | Slice | Check |
|---|---|---|
| 1 | `transform/cropBox.js`, pure geometry (**done**) | `node --test tests/cutdeck_transform_cropbox.test.cjs`: 8 pass (edge, corner, clamp, 50 % scale, 90° rotation, move, preview mapping) |
| 2 | **Live probe A:** `applyMotionValues` with `cropLeft…cropBottom` on Motion | Write 10/20/30/40, read back, compare with Effect Controls, one Ctrl+Z restores. Add a PREMIERE_FACTS row. |
| 3 | **Live probe B:** `<img src>` of the exported PNG in the panel (file path or `file:` URL) | The image appears. Add a PREMIERE_FACTS row. If it fails: read bytes with `uxp.storage` and use a `data:` URL. |
| 4 | **Live probe C:** write rate | Run writes every 50/100/200 ms during a drag. Watch Program Monitor lag and the undo history count. Pick the rate, set the Live default. |
| 5 | UI: section in `core/alignPanel.js` + intents in `edit.js` (`grabCropFrame`, `setCrop`) | Fake-premiere test (`tests/fakes/premiere.cjs`): a drag sends the expected crop values; `node tools/adobe/check-api.mjs` stays green |
| 6 | End-to-end in Premiere | Drag on a scaled + rotated clip, save, `cutdeck.prproj_reader` shows the crop; Program Monitor tracked the drag |

Slices 2-4 are independent probes and can run in one Premiere session. 5 needs 2 and 3.
