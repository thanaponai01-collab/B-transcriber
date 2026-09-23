# HANDOFF — CutDeck: native rough cut (replace the XML *output* with live Premiere edits)

**Status:** design + probe plan. Nothing here is built. Written 2026-09-23.
**For:** Claude Code, working in `B-transcriber`.
**Read first:** `CLAUDE.md` rule 2 (prove every Adobe API before use), `HANDOFF_CUTDECK_NATIVE_SYNC.md`
(the pattern this copies: it retired XML Sync the same way), `HANDOFF_CUTDECK_XML_RECUT.md`
(the transform this replaces), `uxp/cutdeck/timeline/nativeSync.js` (the proven code shape).
**Prime directive (unchanged):** a false cut is worse than a missed one. The editor's source
sequence is never touched; every native edit lands on a **copy** and is verified by read-back.

---

## 1. Why

Today's rough cut (`main.js` → `workflow.prepare` → helper `start` → `cutdeck.xml_recut` →
`workflow.importResult`) round-trips through FCP7 XML twice: Premiere exports the sequence, the
helper rewrites it, Premiere imports the result. The XML *output* half is where the limits live:

| XML limit | Where it bites today |
|---|---|
| FCP7 can't carry transitions, nested sequences, or keyframed effects safely | `xml_recut._refuse_if_unsafe` / `_refuse_unsupported_media` refuse the whole job — the more finished the edit, the more often |
| Import creates new project items and a new sequence identity | `xml_bridge._run` strips `<uuid>` and renames; the project fills with duplicates |
| Timebase lives in the XML, not the project | per-project `--fps` rules, `DurationMismatch` guard, VFR refusal |
| Link state rebuilt by hand | `xml_recut._rebuild_links` |
| One-way | once imported, CutDeck can't see or revise the cut |

**What stays XML:** the *input* half. `exportAsFinalCutProXML` (d.ts:2353) is a cheap read-only
export that already gives the helper the media paths + placements for the audio mixdown. Keep it
as analysis input in Phase 1; replacing it is Phase 4 (optional).

**The change in one line:** the helper returns **cut regions in frames** instead of writing
`rough_cut.xml`; the panel applies them natively to a clone of the sequence.

---

## 2. Every declared API this handoff relies on

Source: `@adobe/premierepro@26.2.1`, `package/src/premierepro.d.ts` (obtain with
`npm pack @adobe/premierepro@26.2.1` in the scratchpad). Line numbers are that file.
**Status column:** *LIVE* = run in Premiere by an existing CutDeck probe/feature;
*DECLARED* = in the typings only — must pass a probe (section 5) before feature code uses it.
Typings give no runtime semantics; every DECLARED row has a named open question.

### 2.1 Project / transactions

| API | d.ts | Signature | Status | Open question |
|---|---|---|---|---|
| `Project.getActiveSequence` | 2127 | `(): Promise<Sequence>` | LIVE (`workflow.capture`) | — |
| `Project.setActiveSequence` | 2134 | `(sequence: Sequence): Promise<boolean>` | DECLARED | opens the result for the editor |
| `Project.createSequence` | 2142 | `(name: string, presetPath?: string): Promise<Sequence>` | DECLARED | presetPath deprecated; default preset ≠ footage — avoid |
| `Project.createSequenceFromMedia` | 2151 | `(name: string, clipProjectItems?: ClipProjectItem[], targetBin?: ProjectItem): Promise<Sequence>` | DECLARED | settings match footage? does it also lay the whole clip on the timeline (must then be removed)? |
| `Project.executeTransaction` | 2274 | `(callback: (compoundAction: CompoundAction) => void, undoString?: string): boolean` | LIVE (`componentAccess.runInTransaction`) | — |
| `Project.lockedAccess` | 2284 | `(callback: () => void): void` | LIVE | — |
| `CompoundAction.addAction` | 1052 | `(action: Action): boolean` | LIVE | — |
| `ProjectConverter.exportAsFinalCutProXML` | 2353 | (see file) | LIVE (`workflow.prepare`) | — |

### 2.2 Sequence

| API | d.ts | Signature | Status | Open question |
|---|---|---|---|---|
| `Sequence.createCloneAction` | 2859 | `(): Action` | LIVE (`nativeSync`) | — |
| `Sequence.createSubsequence` | 2866 | `(ignoreTrackTargeting?: boolean): Promise<Sequence>` | DECLARED | uses sequence In/Out? could replace clone+scope for ranged cuts |
| `Sequence.getInPoint` / `getOutPoint` / `getEndTime` | ~2880 | `(): Promise<TickTime>` | LIVE (`workflow.capture`) | — |
| `Sequence.getTimebase` | 2932 | `(): Promise<string>` | LIVE — returns ticks-per-frame | — |
| `Sequence.getFrameSize` | 2927 | `(): Promise<RectF>` | DECLARED | — |
| `Sequence.getVideoTrackCount` / `getAudioTrackCount` | ~2815 | `(): Promise<number>` | LIVE | — |
| `Sequence.getVideoTrack` / `getAudioTrack` | ~2825 | `(trackIndex: number): Promise<VideoTrack \| AudioTrack>` | LIVE | — |
| `Sequence.getSelection` / `setSelection` / `clearSelection` | 2922 / 2806 / ~2800 | `TrackItemSelection` based | DECLARED | only needed for review UX |
| `Sequence.getProjectItem` | 2917 | `(): Promise<ProjectItem>` | LIVE (`nativeSync` rename) | — |
| `ProjectItem.createSetNameAction` | 2488 | `(inName: string): Action` | LIVE | — |
| `VideoTrack.getTrackItems` / `AudioTrack.getTrackItems` | 4043 / 491 | `(trackItemType: Constants.TrackItemType, includeEmptyTrackItems: boolean): Item[]` | LIVE (`nativeSync.listClips`) | — |

### 2.3 SequenceEditor (`SequenceEditor.getEditor(sequence)`, d.ts:2953)

| API | d.ts | Signature | Status | Open question |
|---|---|---|---|---|
| `createOverwriteItemAction` | 3002 | `(projectItem: ProjectItem, time: TickTime, videoTrackIndex: number, audioTrackIndex: number): Action` | LIVE (`nativeSync:176`) — V + all audio land linked; index = track count creates a track | does it honour the **project item's In/Out** (placing only the marked span)? |
| `createInsertProjectItemAction` | 2986 | `(projectItem, time, videoTrackIndex, audioTrackIndex, limitShift: boolean): Action` | LIVE-ish (`adjustmentLayer` fallbacks) | not needed if overwrite works |
| `createRemoveItemsAction` | 2970 | `(trackItemSelection: TrackItemSelection, ripple: boolean, mediaType: Constants.MediaType, shiftOverLapping?: boolean): Action` | DECLARED (nativeSync uses it, not independently proven) | ripple=false leaves a gap? ripple=true shifts *all* tracks or only the item's track? one mediaType per call → call twice (video, audio)? |
| `createCloneTrackItemAction` | 3019 | `(trackItem: VideoClipTrackItem \| AudioClipTrackItem, timeOffset: TickTime, videoTrackVerticalOffset: number, audioTrackVerticalOffset: number, alignToVideo: boolean, isInsert: boolean): Action` | DECLARED | keeps effects + keyframes? clones linked partner? returns an Action, not the new item — must re-read the track to find it |

### 2.4 Track items (`VideoClipTrackItem` d.ts:3773; `AudioClipTrackItem` d.ts:240 has the same members)

| API | d.ts (V / A) | Signature | Status | Open question |
|---|---|---|---|---|
| `getStartTime` / `getEndTime` | ~3857 / ~310 | `(): Promise<TickTime>` sequence time | LIVE | — |
| `getInPoint` / `getOutPoint` | ~3833 / ~285 | `(): Promise<TickTime>` media-relative | LIVE (keyframe probe: media-relative, equals source time) | — |
| `createSetStartAction` | 3868 / 317 | `(tickTime: TickTime): Action` | DECLARED | does it move media In with it (trim) or slip? |
| `createSetEndAction` | 3875 / 324 | `(tickTime: TickTime): Action` | DECLARED | same, at the tail |
| `createSetInPointAction` | 3844 / 293 | `(tickTime: TickTime): Action` "relative to the start time of the project item" | DECLARED | does it change duration or shift start? pairing with SetStart required? |
| `createSetOutPointAction` | 3851 / 300 | `(tickTime: TickTime): Action` | DECLARED | same |
| `createMoveAction` | 3827 / 276 | `(tickTime: TickTime): Action` "shifting it by" | DECLARED | **relative shift or absolute?** doc says shift; probe must prove sign and units |
| `createSetDisabledAction` / `isDisabled` | 3897 / 346 | `(disabled: boolean): Action` | DECLARED | used by the review mode only |
| `getSpeed` / `isSpeedReversed` | 3810 / 3820 | `(): Promise<number>` | DECLARED | refusal gate, mirrors `assemblyPlan.unsupportedReason` |
| `isAdjustmentLayer` | ~3815 | `(): Promise<boolean>` | LIVE (`adjustmentLayer.js`) | — |
| `getProjectItem` | 3919 / 368 | `(): Promise<ProjectItem>` | LIVE | — |
| `getTrackIndex` | ~3915 | `(): Promise<number>` | LIVE | — |
| `getType` | ~3885 | `(): Promise<number>` | DECLARED | filter transitions (`TRACKITEMTYPE_TRANSITION`) |
| `createRemoveVideoTransitionAction` | ~3790 | `(transitionPosition?: Constants.TransitionPosition): Action` | DECLARED | only if a cut lands inside a transition — Phase 1 refuses instead |

**Not declared anywhere (proven absent by grep of the d.ts):** razor/split, link/unlink,
get-linked-partner, move-to-another-track. Design around them; do not probe for them.

### 2.5 Project items (`ClipProjectItem`, d.ts:564; `ClipProjectItem.cast`, d.ts:561)

| API | d.ts | Signature | Status | Open question |
|---|---|---|---|---|
| `getInPoint` / `getOutPoint` | 717 / 724 | `(mediaType: Constants.MediaType): Promise<TickTime>` | DECLARED | read to restore the editor's marks afterwards |
| `createSetInOutPointsAction` | 773 | `(inPoint: TickTime, outPoint: TickTime): Action` | DECLARED | does overwrite **in the same compound** see it, or must it commit first? |
| `createSetInPointAction` / `createSetOutPointAction` | 743 / 765 | `(tickTime: TickTime): Action` | DECLARED | fallback if the pair action misbehaves |
| `createClearInOutPointsAction` | 778 | `(): Action` | DECLARED | restore state |
| `getMediaFilePath` | 729 | `(): Promise<string>` | LIVE (`nativeSync`) | — |
| `isMulticamClip` / `isMergedClip` / `isSequence` | 666 / 661 / ~575 | `(): Promise<boolean>` | DECLARED | refusal gate (nested / multicam) |

### 2.6 Time and markers

| API | d.ts | Signature | Status | Note |
|---|---|---|---|---|
| `TickTime.createWithTicks` | 3538 | `(ticks: string): TickTime` | LIVE (`host/ticks.makeTickTime`) | all math stays BigInt ticks in `host/ticks.js` |
| `TickTime.alignToNearestFrame` / `alignToFrame` | 3599 / 3603 | `(frameRate: FrameRate): TickTime` | DECLARED | not needed if frames are converted with `ticks_per_frame` |
| `Markers.getMarkers` (static) | 1752 | `(markerOwnerObject: Sequence \| ClipProjectItem): Promise<Markers>` | DECLARED | review mode |
| `Markers.createAddMarkerAction` | 1787 | `(Name: string, markerType?: string, startTime?: TickTime, duration?: TickTime, comments?: string): Action` | DECLARED | review mode: one ranged marker per cut |

---

## 3. Design

### 3.1 Data contract (helper → panel)

New job output, alongside (then instead of) `rough_cut.xml`. `xml_recut` already computes it:
`scoped_cuts(plan, tb, duration_frames, frame_range)` → ascending, non-overlapping
`[(start_frame, end_frame)]` on the **sequence** frame grid.

```json
{ "cuts_frames": [[120, 188], [402, 455]],
  "ticks_per_frame": "8475667200",
  "sequence_duration_frames": 9000,
  "report": { "cuts_applied": 2, "removed_frames": 121, "reasons": ["silence", "filler"] } }
```

- Add `--cuts-json <path>` to `cutdeck.xml_recut` main: write the list and **skip `recut()`**
  (so no XML refusal can fire — the panel decides what it can apply).
- `xml_bridge._run` gains a `job["output"] == "native"` branch: pass `--cuts-json`, set
  `job["cuts"]`, skip the XML post-processing block.
- Panel converts frames → ticks with BigInt: `ticks = BigInt(frame) * BigInt(ticks_per_frame)`.
  **Refuse** if the helper's `ticks_per_frame` ≠ `sequence.getTimebase()` (replaces `DurationMismatch`).

### 3.2 Route A — recut a live sequence on a clone (the daily path; replaces `xml_recut`)

The editor's existing flow (sequence with In/Out marks, one clip or a synced stack) keeps working.

1. **Clone** the active sequence (`createCloneAction`, own transaction), rename to
   `<name> — CutDeck <id8>` (`createSetNameAction`), find it by name — copy of `nativeSync` step 3.
2. **Read** every clip item on every track of the clone (`listClips` from `nativeSync.js`, move
   it to a shared `timeline/trackItems.js` once it has a second caller).
3. **Plan (pure JS, new `cutPlanApply.js`, unit-tested without Premiere):** for each item
   `[S, E)` with media-in `M` and each cut `[a, b)`, reuse `_keep_subranges` logic → surviving
   pieces. Each item becomes one of: untouched, trimmed-head, trimmed-tail, removed, or split
   into N pieces. Every piece's destination = `start − shift(start)` (port `_shift_for_frame`).
   Refuse before any mutation (whole plan, like `assemblyPlan`) on: speed ≠ 1, reversed,
   transition item overlapping a cut, nested sequence / multicam project item.
   **Keyframes are NOT a refusal** — that is the point of going native (verify in probe P4).
4. **Apply in ONE transaction** (one Ctrl+Z), in this order:
   a. Splits: for an item needing N pieces — trim the original to piece 1, then for each further
      piece `createCloneTrackItemAction(original, offset, 0, 0, alignToVideo, isInsert=false)`
      and trim the clone. (**Blocked on P3**: the clone action doesn't return the new item. If a
      clone can't be addressed inside the same compound, split into two transactions — clone
      pass, re-read, trim pass — and accept two undo steps, stated in the status line.)
   b. Remove pieces wholly inside cuts: `createRemoveItemsAction(selection, ripple=false, …)`,
      once per media type.
   c. Close gaps **ourselves**, left to right: `createMoveAction` by `−shift` per surviving item.
      Never rely on ripple — its cross-track behaviour depends on sync-lock UI state we can't read.
5. **Verify by read-back** (the non-negotiable): re-list the clone; every expected piece must
   exist at its planned start/end/in within 0 ticks; sequence end = original − removed. Any
   mismatch → status error naming the clip + timecode, clone left for inspection, source untouched.
6. `setActiveSequence(clone)`; status: `N cuts · X s removed · opened <name>`.

### 3.3 Route B — fresh clip → new sequence (replaces `xml_export`)

For "cut this raw clip" (MCP / `submit_rough_cut` without a sequence):

1. `createSequenceFromMedia(name, [clip], CutDeck bin)` — settings from footage (P1 checks whether
   the whole clip is pre-placed; if so, remove it first, same transaction style as nativeSync 4).
2. Save the clip's current In/Out (`getInPoint/getOutPoint(mediaType)`).
3. For each KEEP span, cursor from 0: `createSetInOutPointsAction(in, out)` →
   `createOverwriteItemAction(clip, cursor, 0, 0)`; `cursor += out − in`. Pure planning reuses
   `assemblyPlan.planAppend` cursor rules.
4. Restore the clip's original In/Out (or `createClearInOutPointsAction` if none). Read-back verify.

### 3.4 Route C — review mode (zero-risk, ship first)

Same helper output, but only `createAddMarkerAction(reason, "Comment", start, duration)` per cut on
the **source** sequence (markers are the only mutation, one undo). Lets the editor audit cuts
before committing, and gives Route A a free "apply the markers I kept" input later.

---

## 4. Phases

| Phase | Scope | Done when |
|---|---|---|
| 0 | Probes P1–P5 (section 5) as guarded buttons in `capabilityProbe.js`, run live by the user | each probe's pass/fail recorded in `TODO_LEDGER.md` with the Premiere version |
| 1 | Helper `--cuts-json` + bridge `output: "native"` + tests | `pytest` green; new test: cuts JSON equals `scoped_cuts` for the existing recut fixtures |
| 2 | Route C (markers) | live: markers match cut list on a real sequence; one Ctrl+Z removes all |
| 3 | `cutPlanApply.js` pure planner + Node tests (splits, removals, shifts, refusals, ranged In/Out) | tests mirror `tests/` recut cases frame-for-frame |
| 4 | Route A apply + read-back | live on a real synced stack: read-back passes, render matches the XML route's output on a no-keyframe fixture; a keyframed clip crossing a cut survives with animation intact |
| 5 | Route B | live on a raw clip; clip's own In/Out restored |
| 6 | Retire XML output path (`xml_recut` write, `importResult`) behind a setting, then delete | one release with both; user accepts native on real footage |
| 7 (optional) | Replace XML *input*: panel sends media paths + placements (`getMediaFilePath`, start/in) and the helper mixes down from those | `exportAsFinalCutProXML` no longer called for rough cuts |

---

## 5. Probes (Phase 0) — each on a throwaway clone, each read-back reported in the panel

| # | Proves | Steps | Pass if |
|---|---|---|---|
| P1 | `createSequenceFromMedia` | create from one clip into CutDeck bin | settings match footage; report whether the clip was pre-placed |
| P2 | project-item In/Out + overwrite in one compound | one transaction: `createSetInOutPointsAction(2s,4s)` + `createOverwriteItemAction` at 0 | placed item is exactly 2 s long with media-in 2 s; if not, retry as two transactions and record which works |
| P3 | split substitute | on a clone: trim item to [S,b) via SetEnd/SetOutPoint; clone it with `timeOffset=b−S`; re-read; trim clone to [b,E) with media-in `M+(b−S)` | two items, contiguous, media continuous, audio partner followed (report linked state as seen in UI) |
| P4 | clone keeps effects | P3 on a clip with a keyframed Transform + Lumetri | both pieces carry the chain; keyframe ticks (media-relative) unchanged |
| P5 | move + remove semantics | `createMoveAction(−1s)` on one item; `createRemoveItemsAction(ripple=false)` on another | move is **relative**, other tracks untouched; remove leaves a gap and nothing else shifts |

If P3 fails outright, Route A falls back to **Route B-style rebuild**: new sequence, and per surviving
piece overwrite the piece's project item with In/Out set (loses effects — then the keyframe refusal
from `xml_recut` must be ported, stated in the UI).

---

## 6. Acceptance / invariants (tests)

- Source sequence byte-identical after any run (check: re-read item list before/after).
- Sync preserved by construction: for any two surviving pieces on different tracks, relative offset
  unchanged unless one was inside a cut (port the `xml_recut` sync test to `cutPlanApply` tests).
- All tick math BigInt through `host/ticks.js`; no float seconds touch a cut edge.
- Whole-plan refusal before first mutation; refusal messages name clip + timecode.
- One Ctrl+Z undoes the apply (or two, if P2/P3 force it — stated in UI).
- Structure guard (`f068f5a`) stays green: new modules respect the layer direction.

## 7. Out of scope

Multicam clips (none in the editor's projects), speed-ramped clips, cutting inside transitions,
changing the analysis itself (`rules.py`, presets) — all unchanged.
