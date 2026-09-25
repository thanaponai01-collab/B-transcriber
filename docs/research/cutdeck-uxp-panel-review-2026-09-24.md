# CutDeck UXP panel review — 2026-09-24

Scope: the whole `uxp/cutdeck/` panel (~8.3k lines) — Cut & Sync, Adj & FX, the Transform
panel — checked against Adobe's typings `@adobe/premierepro` **26.2.1** and **26.5.1** (the
installed Premiere is 26.5) and the AdobeDocs `uxp-premiere-pro` docs. No code was changed.

**Verdict:** the biggest wins are cleanup, not new features. Adj & FX runs about 5 undo steps
and several failed attempts for every Adjustment Layer (AL). The Transform panel checks
Premiere every 0.6 s for as long as the plugin is loaded. Rough Cut re-reads the entire
timeline about 7 times. On the creative side, Premiere has three APIs the panel isn't using
yet: timeline events, transcript import and markers.

Labels: **proven** = recorded by a live run in TODO_LEDGER; **traced** = the code path was
followed end to end; **suspected** = neither. Nothing here was run in Premiere for this
review. Anything marked "probe" needs a live run before building on it.

## 1. Fix first: wasted or risky work (small changes)

| # | Finding | How we know |
|---|---|---|
| A1 | After placing each AL, a "trim" step uses `createSetEndAction`. TODO_LEDGER.md:11 records that call as **unusable** (it throws "script object is no longer valid"). The error is silently ignored, and the check reports the trim "held" only because the earlier In/Out step already set the right length. So every placement wastes one attempt (`timeline/adjustmentLayer.js:462`). | proven (ledger) + traced |
| A2 | The overwrite tries the `ClipProjectItem.cast()` version of the AL first. The ledger records Premiere rejecting that ("Invalid parameter"). So each placement fails 2–3 times before the plain item works. The fallback list also includes a ripple **insert** onto a track that already has clips; if that insert ever succeeded, it would shift the footage after it (`timeline/adjustmentLayer.js:408-417`). | proven (ledger) + suspected risk |
| A3 | Accuracy: the panel decides whether a clip is an AL by its name ("adjustment", "adj_"). It also scans every item on every video track just to find which track a selected clip is on (`host/trackItems.js:344`). Premiere has `isAdjustmentLayer()` and `getTrackIndex()` on both video and audio clips. As it stands, footage named `adjustment_test.mp4` is skipped and a renamed AL is treated as footage. | traced, d.ts |
| A4 | The color label is set on the one shared AL project item in its own undo step for **every** placement. Once per run is enough. | traced |

## 2. Speed and RAM

- **Transform panel polling (biggest RAM/CPU drain).** `setInterval(…, 600)`
  (`features/align.js`) starts the first time the Transform panel opens and never stops.
  Adobe's docs say `hide()`/`destroy()` don't fire in Premiere yet. Each check makes about
  15–20 calls into Premiere, 100 times a minute, all day.
  - The fix is `EventManager.addEventListener(sequence, SequenceEvent.SELECTION_CHANGED)`,
    re-attached on `SequenceEvent.ACTIVATED`. Both are in the d.ts.
  - One limit: no event fires when Position is dragged in Effect Controls. For that case,
    keep a slow poll (about 5 s) or refresh when the panel gets focus.
  - Using `ACTIVATED` on the main panel would also let the sequence card refresh itself on
    sequence switch. There's no event for In/Out changes, so the refresh button stays.
- **Rough Cut reads (traced).** Each read (`timeline/nativeCut.js` `readItems` / `readSequence`)
  makes 6–11 calls into Premiere per clip, one after another. After the razor step, 432 cuts
  leave about 870 pieces per track. Changes:
  - Middle reads only need start, end and In.
  - Speed, reversed, nested and multicam only need checking on clips a cut actually touches,
    because `planCutApply` only refuses those.
  - Cache media paths per project item.
  - `elapsedSeconds` is already recorded, so there's a baseline to measure against.
- **Adj & FX undo steps.** Each AL costs about 5 undo steps, and applying a preset
  (`timeline/effects.js` `applyCapturedPreset`) adds up to 5 more per AL. Thirty cut
  transitions come to about 300 undo steps.
  - Applying a preset can run each of its 5 phases across all ALs at once: 5 steps total.
  - Placement: in transition mode every AL has the same length. So In/Out can be set once,
    then all overwrites done in one step, because lanes never overlap.
  - The ledger only proved that setting In/Out and overwriting in the *same* step fails
    (P2). N overwrites after a committed In/Out has never been run — **needs a live probe
    first**.
- **Collision scan.** Clear space is currently looked up 3 times across all tracks
  (`findSmartStackTrack` twice, then `isTrackRangeClear` per placement). Read the track
  contents once into memory, pick the tracks there, and re-check only the chosen track right
  before writing. That keeps the "never overwrite footage" safety check.
- **Small items.** Load the three test modules (`capabilityProbe.js` 60 KB, `roughCutProbe.js`
  24 KB, `syncProbe.js` 18 KB) only when clicked — saves KB, not MB. Open one connection to
  the helper instead of a new one for every 1.5 s status check (`core/rpc.js`). Drop the
  pretty-printed `console.log` of each captured preset.

No RAM figures in MB were measured. To measure: take a UXP Developer Tool heap snapshot
before and after 10 minutes with the Transform panel open.

## 3. APIs not yet used, ranked by time saved

1. **Send the Thai transcript into Premiere's Text-Based Editing**
   (`Transcript.importFromJSON` + `createImportTextSegmentsAction`). Our ASR beats
   Premiere's on Thai with English mixed in. Once it's inside Premiere you can cut by
   deleting text and get captions natively. The JSON format isn't documented, so first run
   `exportToJSON` on a clip Premiere has transcribed and copy its shape. 26.5.1 also adds
   `querySupportedLanguages()`, which shows whether Premiere even offers Thai.
2. **Review markers on the rough cut** (`Markers.createAddMarkerAction` with comments and
   colors). A marker at each cut, e.g. "removed 1.8 s: …", with a different color for risky
   cuts, to step through them. The ledger shows 432 markers already passed live.
3. **Hide jump cuts.** After a rough cut, apply a punch-in preset to every other segment.
   Only reuses what exists: per-clip AL mode plus `applyCapturedPreset`.
4. **FX on every cut of a single rendered file.**
   `SequenceUtils.performSceneEditDetectionOnSelection(APPLYCUT)` cuts the clip at its scene
   changes, then 50/50 mode places ALs on them.
5. **Tag outputs instead of relying on names** (`Properties` on the sequence). Store the
   source sequence and job ID on the copy. Resume then survives a panel reinstall, and Sync
   can refuse a synced copy by its tag, not the `_Synced` name.
6. **Point at Sync problems.** After Sync, select the unmatched clips (`setSelection`) and
   move the playhead to the first problem (`setPlayerPosition`).
7. **Menu commands.** Adobe's docs confirm `command` entrypoints appear under
   Window › UXP Plugins › CutDeck, e.g. "AL on every cut" or "Preset 1–9". Whether Premiere
   lets you bind a keyboard shortcut to them needs a live check.

One gap: 26.x has no audio-transition API, only video (`createAddVideoTransitionAction`). To
avoid pops at cut edges, the helper could shift each cut edge to the quietest frame within
±2 frames.

## Notes

- CLAUDE.md still points at the 26.2.1 typings; 26.5.1 matches the installed Premiere.
  26.5.1 adds `Transcript.transcribeClipProjectItem` / `hasTranscript` /
  `querySupportedLanguages`, `createSubClipAction` and `WorkAreaUtils`, and drops
  `ProjectConverter.importFromFinalCutProXML` (no longer used by the panel;
  `exportAsFinalCutProXML` is still there).

## Suggested order

1. A1–A4 (small, low-risk)
2. Event-driven Transform panel
3. Rough Cut read speed
4. Batching probe (Adj & FX placement + preset apply)
5. Review markers
6. Transcript import
