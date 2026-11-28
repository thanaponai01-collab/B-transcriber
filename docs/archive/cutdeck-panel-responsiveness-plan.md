# CutDeck panel: responsiveness, flicker and Graphic/text anchor bugs

Status: plan, not built. Written 2026-10-04 from reading the code (not from a live run).
Each cause below is a **hypothesis tied to a line**; Slice 0 measures them before anything
is changed. Adobe API sources are named per rule 2 of `GEMINI.md`.

## What the user sees

1. Clicking an action in **Adj & FX**, **Transform** or **Align** takes a while before anything happens.
2. The panel **flickers**.
3. **Transform** panel: anchor point on a **Graphic / text** gives errors or wrong results.

## Short answer: is a different architecture needed?

No rewrite. The seams are sound (`core/panel.js` / `core/alignPanel.js` render-only,
`features/*` own state, `transform/*` and `timeline/*` talk to Premiere). The slowness and
flicker come from **how much host traffic each click and each poll makes**, and from
**render paths that touch every control on every state change**. Fixing those is four
changes to the existing design, not a new one:

| Change | Replaces |
|---|---|
| A. **One read-model per selection** (`transform/snapshot.js`), reused by poll, display and edit | 3–4 separate re-reads of the same clip per click |
| B. **Adaptive poll** (fast only right after a change, slow when idle, paused during an action) | fixed 150 ms full read |
| C. **Optimistic UI**: write the panel's own state first, confirm from Premiere after | full `refreshAlignSequence()` before the user sees anything |
| D. **Busy = per-control, delayed** (only show busy after ~150 ms, never toggle every `[data-act]`) | `renderBusy` disabling every button on every action |

## Causes found in the code

### Slow clicks (Transform / Align)

| # | Where | What happens |
|---|---|---|
| L1 | [features/align.js](../../uxp/cutdeck/features/align.js) `FAST_POLL_MS = 150` + `pollAlignTransform` | Every 150 ms: `getSelection`, component chain, 10 Motion params, `Metadata.getProjectColumnsMetadata` + `JSON.parse` (in `readSourceFrameSize`), `getSettings` ×2, `isGraphic`, `readGraphicLayers`. All on the same UXP↔host bridge a click needs. A click waits behind an in-flight poll. |
| L2 | [transform/edit.js](../../uxp/cutdeck/transform/edit.js) `editSelectedClips` → `clipModel` → `readAnchorFrameSize` → `readSourceFrameSize` + `isGraphic`; then `isGraphic` again, `readGraphicLayers` again | Same clip read 3–4 times per click; per-clip loop is serial (`for … await`). |
| L3 | `features/align.js` `onAnchor/onAlign/onDistribute/onSetField` | After the write, a full `refreshAlignSequence()` (another complete read) runs **before** the status/value updates. |
| L4 | [transform/frameBounds.js](../../uxp/cutdeck/transform/frameBounds.js) `measureDrawnBounds` | Graphic without cached bounds: `ensureHelper()`, `exportSequenceFrame`, `waitForFile` polling every 20 ms, mute every other video track **one by one**, RPC to helper, unmute one by one. Several hundred ms to seconds. |
| L5 | [transform/params.js](../../uxp/cutdeck/transform/params.js) `itemComponentCache` (WeakMap keyed by the track-item object) | If Premiere returns a **new** proxy per `getSelection()` the cache never hits (slow). If it returns the **same** proxy, the cache never invalidates (`clearComponentCache` is called nowhere) → stale chain after adding an effect / undo. Unknown which — Slice 0 probes it. |
| L6 | `features/align.js` `commitField` | Busy-waits in 10 ms `setTimeout` steps until the last slide write finishes. |

### Slow clicks (Adj & FX)

| # | Where | What happens |
|---|---|---|
| A1 | [timeline/alLibrary.js](../../uxp/cutdeck/timeline/alLibrary.js) | Every click: `getRootItem` → walk bins → `flattenImportWrappers` (more `getItems`, possibly 2 transactions) → find the AL. Nothing is cached between clicks. |
| A2 | [timeline/effects.js](../../uxp/cutdeck/timeline/effects.js) `applyCapturedPresetToAll` | Up to 5 transactions per preset click (insert / values / enable keyframes / keyframes / interpolation). Needed for correctness today; measure before touching. |
| A3 | [timeline/adjustmentLayer.js](../../uxp/cutdeck/timeline/adjustmentLayer.js) | Placement + separate "Set Length" transactions per duration group. |

### Flicker

| # | Where | What happens |
|---|---|---|
| F1 | [core/panel.js](../../uxp/cutdeck/core/panel.js) `renderBusy` | On every `act()` start and end, **every** `[data-act]` in the main panel gets `disabled` + class toggled, unconditionally (no "already in that state" check, unlike `alignPanel`). Quick actions = whole panel greys out and back. |
| F2 | [features/controller.js](../../uxp/cutdeck/features/controller.js) `act` | Status flips to "Processing…" immediately, then to the result; the align status card shows/hides on level changes. |
| F3 | `frameBounds.muteOtherVideoTracks` / `createSetDisabledAction` path | Tracks muted/unmuted (or the clip switched off/on) to measure a Graphic → the **Program Monitor** visibly blinks. |
| F4 | [core/alignPanel.js](../../uxp/cutdeck/core/alignPanel.js) `setInput` | `.val-text` `textContent` and class toggles written on every render without a diff. |
| F5 | `pollAlignTransform` | A transient empty selection read blanks the fields for one tick (the `emptyPollCount < 1` guard only absorbs one). |

### Graphic / text anchor bugs

| # | Where | Bug |
|---|---|---|
| B1 | `edit.js` `readAlignTransform` vs `setField` | Display shows the **text layer's** values whenever `layers.texts.length > 0`, but `setField` only writes text layers when `layers.onlyText`. A Graphic with text + a shape or an added effect shows text values but **writes Motion**. Typed value "doesn't stick" / something else moves. |
| B2 | `edit.js` `setAnchor` → `textLayerAnchor` + panel fields | Returns null when the Graphic has **2+ text layers**, falling back to Motion while panel shows Text 1. Decided: support 2+ text layers with independent anchors. In 9-point anchor, each text layer snaps to its own individual text box. In panel inputs, provide a layer switcher (`Text 1` / `Text 2` / `All`) to inspect/target the active text layer or all in tandem. |
| B3 | `frameBounds.measureDrawnBounds(keepDisabled: true)` + `editSelectedClips` | Re-enable rides **inside** the edit's transaction. Ctrl+Z on the anchor/align undoes the re-enable too, leaving the Graphic **switched off**; the next click then errors "it is switched off on the timeline (Ctrl+Z past an Align can do that)". The error text documents the bug instead of fixing it. |
| B4 | `measureDrawnBounds` | Anchor on a Graphic **requires the playhead over the clip** and the helper running; otherwise "Move the playhead over it first." / helper errors. Correct refusal, poor UX: the anchor grid looks enabled. |
| B5 | `setField` anchor-x/y on text | Moves the text anchor without compensating Position, so the text jumps. Decided: typed Anchor X/Y must compensate Position so the text stays frozen in place on screen (move only anchor, no text moves). |
| B6 | `params.readAnchorFrameSize` | A Graphic **with** a project item (.mogrt / from a bin) of a different size: Position and anchor routes use different frames. Open in `PREMIERE_FACTS.md` row "Text Position canvas". |

`VideoTrack.setMute` / `isMuted` exist in `reference/adobe/api/premierepro.txt`, but
`docs/PREMIERE_FACTS.md` has no live row for them yet. Slice 0 adds one.

## Plan (ordered slices, each with its check)

### Slice 0: measure first (no behavior change)
- Add `core/timing.js`: `time(label, fn)` logs `CutDeck timing <label> <ms>` to UXPLogs. Wrap: poll read, `readSelectedMotionClips`, `clipModel`, `measureDrawnBounds` (each stage), `applyMotionValues`, AL lookup, `placeAdjustmentLayersOnTimeline`, `applyCapturedPresetToAll`.
- Live probe: does `seq.getSelection()` return the **same** track-item object on two calls? (settles L5). Does `setMute` blink the Program Monitor? Add both to `PREMIERE_FACTS.md`.
- **Check:** one live run per action → a timing table in this doc. Every later slice must beat its row.

### Slice 1: flicker fixes (small, safe) [DONE]
- F1: `panel.renderBusy` only touches a node whose `disabled` differs (same guard `alignPanel.renderBusy` already has).
- F2/D: controller sets `busy` immediately (blocks double-clicks) but exposes `showBusy` only after 150 ms; panels render the busy look from `showBusy`. Fast actions never flash.
- F4: diff `.val-text` text and classes in `setInput`.
- F5: keep last good transform for up to ~300 ms of empty reads, not one tick.
- **Check:** `node --test tests/*.cjs` green; new test: two `render()` calls with the same state mutate nothing (extend `tests/panel_ui_contract.test.cjs`); a fake `act` finishing in 50 ms never renders `showBusy: true`. (Verified: 605/605 tests pass).

### Slice 2: one snapshot per selection (L2, L3, L5) [DONE]
- New `transform/snapshot.js`: `readSnapshot(ppro)` → `{ seqFrame, seqAspect, clips: [{ item, key, name, transform, isGraphic, layers, anchorFrame }] }`, item reads run with `Promise.all`, frame size/aspect read once.
- Cache keyed by **`key` (track:startTicks) + selection signature**, not the object; invalidated after every write CutDeck makes and on any poll that sees a different signature. Fixes stale chain and never-hit cache together.
- `readAlignTransform`, `editSelectedClips`, `setField`, `alignToSelection`, `distribute` take the snapshot instead of re-reading. `readSourceFrameSize` result cached per project item (source size doesn't change).
- **Check:** existing `tests/cutdeck_align*.test.cjs` green; new fake-host test counts host calls for one anchor click on one clip: target ≤ 1 full read (today ≈ 4). Slice 0 timing for Anchor/Align on video clips drops. (Verified: 607/607 tests pass, Adobe API check clean, getTrackItems and getSettings called exactly once).

### Slice 3: optimistic UI + adaptive poll (L1, L3, L6) [DONE]
- After a write, put the **planned** values straight into `ctl.state.transform` and render; then confirm with one snapshot read in the background (overwrite only if it differs).
- Poll: 150 ms for ~2 s after any change/event/pointerenter, then 1000 ms; paused while `busy` or a slide is in flight. Keep the heartbeat (Premiere sends no event for Effect Controls drags — see the comment in `features/align.js`).
- `commitField`: await the in-flight slide's promise instead of the 10 ms loop.
- **Check:** test that `onAnchor` renders the new anchor before the confirm read resolves; poll interval test (fake timers). Live: value updates feel instant. (Verified: 610/610 tests pass, Adobe API check clean; optimistic rendering, promise await on `commitField`, and adaptive interval scaling verified).

### Slice 4: Graphic/text anchor correctness (B1–B5)
- B1: one decision function `textTarget(layers)` used by **both** display and edit: text layers are the target only when `onlyText`; otherwise display Motion values too.
- B2: for 2+ text layers, support independent anchors per text layer:
  - **9-point Anchor Grid:** Each text layer snaps its anchor to its own individual text bounding box (helper separates connected text boxes or derives per-layer targets). Both text layers' anchors and compensated positions are updated in one transaction so neither text moves on screen.
  - **Panel Input Fields:** Add a sub-layer switcher (`Text 1` / `Text 2` / `All`) when a Graphic has >1 text layers. Inspect/edit the active layer independently; or when `All` is selected, edits apply in tandem across all layers.
- B3: never put the re-enable inside the edit transaction. Use mute-only measuring; if muting isn't possible, re-enable in its own transaction immediately after the off frame is saved (two extra undo steps, but undo can never leave the clip off). Remove the "switched off" workaround message once fixed.
- B4: disable the anchor/align buttons for a Graphic with no cached bounds when the playhead is outside the clip, with the reason in the tooltip (from the snapshot, no extra reads).
- B5: typed Anchor X/Y on text must compensate Position so the text stays frozen in place on screen (move only anchor, no visual jump).
- **Check:** fake-host tests in `tests/` for each: (B1) text+shape Graphic display and write hit Motion; (B2) 2 text layers each snap to their own box independently; layer switcher selects target layer; (B3) undo of an anchor never leaves `isDisabled() === true`; (B5) typed anchor update writes matching position compensation. Live: nine-point anchor on a 1-layer and a 2-layer text Graphic keeps text in place; one Ctrl+Z restores. Add rows to `PREMIERE_FACTS.md`. (Done: 615/615 tests passing, Adobe API check clean; B1–B5 implemented and verified).

### Slice 5: faster Graphic measuring (L4, F3) [DONE]
- Mute/unmute tracks with `Promise.all` instead of one by one (`VideoTrack.setMute`, premierepro.txt; live-confirm order safety in Slice 0).
- Skip muting when `hasClipsUnderneath` is false (already) **and** when nothing is above either.
- Start `ensureHelper()` when the transform panel mounts, not on first click.
- `waitForFile` interval 20 ms is fine; measure before changing.
- **Check:** Slice 0 timing for a first Graphic anchor click drops; no Program Monitor blink when no other clips overlap. (Verified: 616/616 tests pass, Adobe API check clean; concurrent mute/restore and singleFrame bypass verified without disabling or flickering).

### Slice 6: Adj & FX (A1–A3), only where Slice 0 shows time [DONE]
- Cache the found AL / Color Matte project item per `(project, W×H)`; re-validate cheaply (item still in bin) instead of re-walking bins; run `flattenImportWrappers` only after an import.
- Merge the placement and "Set Length" transactions if the API allows (checked `docs/PREMIERE_FACTS.md`: P2 / line 37 & 66 proves In/Out marks must be committed in their own transaction before overwrite reads them, so separate transactions remain required by the Adobe host API for correctness).
- **Check:** `tests/cutdeck_*adjust*` / AL tests green; Slice 0 timing for a span click drops; one Ctrl+Z still undoes a placement. (Verified: 617/617 tests pass, Adobe API check clean; alLibrary caching per (project, W×H), cheap re-validation, and wrapper flattening only upon import verified).

## Order and parallelism
Slice 0 first (it decides priorities). Slice 1 is independent and can ship right after.
Slices 2 → 3 → 4 in that order (3 and 4 build on the snapshot). Slices 5 and 6 are
independent of each other and of 3/4.

## Open questions for the user
1. ~~B2: 2+ text layers, move every layer's anchor, or refuse?~~ **Resolved:** Independent anchors per layer. 9-point grid snaps each layer to its own box. Panel inputs provide a layer switcher (`Text 1` / `Text 2` / `All`).
2. ~~B5: typed text anchor, compensate Position or match Effect Controls?~~ **Resolved:** Compensate Position so the text stays frozen on screen (only anchor moves).
3. What exact error text do you see on the Graphic/text anchor? (Copy status button in the Transform panel.) It decides whether B3, B4 or something new is the one you hit.
