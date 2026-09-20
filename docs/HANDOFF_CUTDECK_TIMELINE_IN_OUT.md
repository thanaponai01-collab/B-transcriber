# Handoff: CutDeck — Premiere timeline In/Out to rough cut

Date: 2026-09-16  
Status: **Phase 1 complete; Phase 0 built but not yet run on a host.** Native editing
feasibility remains unverified.  
Repository: `D:\01 - Antigravity\00 Claude\B-transcriber`

## 0. Where this actually stands (updated 2026-09-16)

Read this before section 4 or 9 — it says which parts of the plan below are done,
which changed, and what is blocking.

**Built and tested (72 Node tests green across four files):**

| What | File | Tests |
| --- | --- | --- |
| Exact half-open range normalization, BigInt ticks | `uxp/cutdeck/timelineRange.js` | `cutdeck_assembly.test.cjs` (29) |
| Section 6 intersection and placement math | `uxp/cutdeck/assemblyPlan.js` | ″ |
| Phase 0 probe 1 — marks and timing, read-only | `uxp/cutdeck/capabilityProbe.js` | ″ |
| Phase 0 mutation probe — the three-point route | `uxp/cutdeck/assembleProbe.js` | `cutdeck_assemble_probe.test.cjs` (32) |

Both probes are buttons in the single CutDeck panel. The mutation one arms on the
first click. **Phase 1's exit criteria are met** — exact frames, no float drift, no
production mutation enabled.

**A backend candidate the plan below does not mention.** Sections 4 and 9 were
written around `createSubsequence`, cross-sequence clone, and nested insertion.
Issue #25 settled on a fourth route that is simpler than all three and shares this
document's placement math exactly: a **three-point edit** —
`ClipProjectItem.createSetInOutPointsAction` to bound the source, then
`SequenceEditor.createOverwriteItemAction(projectItem, time, vIdx, aIdx)` to place
it. No cloning, no nesting, no subsequence. `assembleProbe.js` probes it; it is now
the leading candidate simply because it is the only one with a probe built.

**Two gestures are blocking, both human, both independent of each other:**

1. **Run the timing probe.** `timelineRange.OUT_CONVENTION` is deliberately `null`
   and every call throws until it is set. Nothing in Phase 2 or 3 can be correct
   without it — a wrong guess is off by exactly one frame on every single add.
2. **Run the assemble probe** in a disposable project. It answers whether the
   three-point route exists at all: does a new sequence inherit the timebase, do N
   placements survive one transaction, does one overwrite carry **linked audio**
   (this route's own question — a rough cut without dialogue is useless), and does
   ripple-remove work.

`uxp/cutdeck/README.md` has the step-by-step for both.

**Still true and still the point:** host mocks establish orchestration, never
Premiere's editing fidelity. Every verdict is `null` until those clicks happen.

## 1. Intended result

The editor marks **In** and **Out** in Premiere's source timeline, clicks **Add to Rough Cut** in CutDeck, and the marked section is appended to one reusable rough-cut sequence. The editor repeats this without exporting XML, importing files, choosing folders, or creating a new result sequence for every selection.

Example: mark 00:10–00:20, add; mark 00:40–00:55, add. The destination contains those two sections consecutively, with an expected duration of 25 seconds after Premiere's exact Out-point convention has been normalized. The source stays intact and remains the active timeline for the next selection.

**Scope assumption:** this plan follows the conversation's proposed “Add to Rough Cut” workflow: the selected range is material to keep. The user confirmed that marking happens in Premiere's timeline. They have not separately confirmed whether each selection should also receive automatic silence/filler removal. Ship manual range assembly first; treat automatic cleanup as a separate follow-on. Do not silently substitute assembly for the existing automatic rough-cut feature.

The earlier conversational claim that this can preserve all audio/video needs qualification: the desired behavior is clear, but editable cross-sequence copying and fidelity must pass the host spike below before being promised.

## 2. Current implementation and reuse

Read these files before implementation; paths below are repository-relative.

| File | Current responsibility / relevance |
| --- | --- |
| `uxp/cutdeck/workflow.js` | `capture()` already reads active project, sequence, In/Out, end time, GUIDs, timebase and audio-track count. `prepare()` starts the helper workflow and exports XML. `importResult()` imports and identifies a new sequence. |
| `uxp/cutdeck/main.js` | Panel events, busy guard, status messages, XML job persistence and resume. The socket probe is now behind an explicit button and no longer runs on load, as section 5 required. |
| `uxp/cutdeck/index.html` | Existing panel controls. |
| `uxp/cutdeck/rpc.js` | XML helper requests and connection retry behavior. |
| `uxp/cutdeck/README.md` | Working workflow, existing limitations and test commands. |
| `cutdeck/xml_bridge.py` | Helper orchestration for the existing export/analyze/import path. |
| `tests/cutdeck_workflow.test.cjs` | Existing host-operation mock tests. |
| `tests/cutdeck_rpc.test.cjs` | Existing connection/retry tests. |
| `uxp/spike18_split_probe/README.md` | Historical native split experiments, including transaction/byproduct limitations. Consult if a candidate implementation depends on splitting. |

The current workflow already captures timeline marks. Its overhead comes after capture: export full-sequence XML, analyze via the helper, write a result and import a new sequence. The README states that analysis covers the full sequence and only the resulting cuts are limited by In/Out.

The user reports that the UXP workflow works. Preserve it as the existing automatic mode while adding the new path. No Python helper, transcription, GPU work, XML, or rendered media is needed for manual assembly if native copying is proven.

Read repository guidance in `CLAUDE.md` and relevant current entries in `TODO_LEDGER.md` before changing code. `docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md` explicitly marks its old ExtendScript/QE design as superseded; it is historical context, not an implementation recipe.

## 3. Product contract

1. Open a source sequence and press Premiere's usual I/O keys.
2. Click **Add to Rough Cut**. Capture fresh marks at click time; the panel preview is informational.
3. On the first successful add, create one destination with matching sequence settings. Later adds reuse its identity.
4. Append the complete marked timeline interval, preserving relative placement across supported tracks and gaps inside that interval.
5. Keep the source timeline active. Show the added duration and total rough-cut duration.
6. Offer **Open Rough Cut**, **Back to Source**, and **New Rough Cut** as secondary controls.

Suggested panel content:

```text
Timeline selects
Source: Interview assembly
In: 00:01:12:08   Out: 00:01:25:16
Destination: Interview assembly — Rough Cut

[ Add to Rough Cut ]

Added selection · 4 sections · total 01:08:12
[ Open Rough Cut ] [ Back to Source ] [ New Rough Cut ]
```

Display timecodes in the source's actual display format. Drop-frame labels are display conventions; edit calculations use exact ticks/frame counts.

Defaults:

- One source and one destination per assembly session.
- Destination name: `<source name> — Rough Cut`; identity is its GUID, never its name.
- Include all supported audio/video tracks regardless of track targeting, subject to the validated mute/disabled policy in Phase 0.
- Capture the effective source playback state, including disabled items and muted tracks, only if the chosen backend can preserve it. Otherwise explain the unsupported state before mutation.
- Preserve internal gaps. Append the next selection immediately after the previous selection's full marked duration.
- Keep the source marks and playhead unchanged.
- Clicking **New Rough Cut** starts a fresh session; retain the previous destination and create the next one lazily on a successful add.
- Prevent accidental repeat submissions. A later intentional repeat of the exact same range is allowed through an explicit **Add Again** action.

Source switching requires an explicit new session in v1. If the destination itself is active, tell the editor to return to the bound source; never append a sequence into itself.

## 4. Native API feasibility: first implementation milestone

Adobe's reference documents `Sequence.getInPoint()`, `getOutPoint()`, `getTimebase()`, `getProjectItem()` and `createSubsequence(ignoreTrackTargeting)`. It does not fully specify the range, fidelity or targeting behavior needed here. Verify these details in the installed host. [Sequence reference](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequence)

`SequenceEditor` exposes clone-track-item, project-item insert, overwrite and removal actions. Their presence alone does not establish that arbitrary track items can be cloned across sequences with effects, links and trimming intact. A sequence project item may insert as a nest. [SequenceEditor reference](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequenceeditor)

`Project` provides sequence creation, identity lookup and undoable transactions. `lockedAccess()` has a synchronous callback; asynchronous preparation belongs outside it. Prove transaction behavior for the chosen operations, including any sequence creation that is outside the action transaction. [Project reference](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/project)

### Phase 0: bounded host spike

Use a disposable test project with frame counters, audible boundary cues, linked A/V and staggered clips on at least two video and two audio tracks. Record the exact Premiere build, plugin version, method signatures, source/destination snapshots and visible playback result.

Probe in this order:

1. **Marks and timing** — ✅ **built**, `capabilityProbe.js`, not yet run. Determines unset-mark behavior, one-frame selections, Out-point inclusivity, nonzero sequence start timecode and the true ticks-per-frame value. Establishes a normalized half-open interval `[in, outExclusive)`.
1b. **Three-point placement** — ✅ **built**, `assembleProbe.js`, not yet run. Not in the original list; added after issue #25 settled on this route (see section 0). Does `createSetSettingsAction` carry the real timebase; do three interleaved `setInOut`/`overwrite` pairs survive one transaction or collapse against the shared `ClipProjectItem`; does one overwrite place **linked audio** on A1; does `createRemoveItemsAction(sel, ripple, ANY)` take that audio with it. **Run this before probes 2 and 3** — if it passes, they are moot, because it is the same capability reached without cloning or subsequencing.
2. **Subsequence extraction:** test whether `createSubsequence(true)` isolates the marked range, includes all intended tracks and preserves independent clips/settings. Test targeted versus untargeted tracks explicitly.
3. **Append editable clips:** test a destination editor operating on source track items through documented clone operations. Establish whether cross-sequence cloning is supported, then trimming, placement, links and effects. Avoid assuming a returned action gives a reference to a newly created item before commit. **Note:** issue #24 closed the same-sequence version of this after eighteen live rounds; do not restart it without reading that issue's closing comment.
4. **Sequence insertion:** separately test inserting the source sequence's project item with marked boundaries. Record whether output is nested or expanded and whether marks are respected. This is an alternative product behavior, not equivalent evidence for editable copying.
5. **Undo and failure:** add two sections, undo the second, redo it, then undo the first. Test failure after sequence creation and after part of a multistage append. Record whether a coherent recoverable state is possible. **Changed by issue #25:** if the destination is a new sequence beside the original rather than an in-place edit, undo is `Project.deleteSequence`, and the one-undo-step requirement relaxes to "the destination is disposable".
6. **Repeated use:** perform 50 adds and check source marks, source clips, target duration, links, audio sync, UI responsiveness and project item growth.

Timebox this investigation to one focused engineering day. Deliver evidence and a go/no-go decision even if no backend qualifies. Do not let the historic split experiments become an open-ended prerequisite.

### Backend decision

| Outcome | Decision |
| --- | --- |
| **Three-point placement passes** (probe 1b: timebase inherited, placements independent, audio linked) | Build the native assembly MVP on it. Cheapest route, shares section 6's math unchanged, and nothing needs cloning. |
| **Three-point passes but placements collapse** | Still build on it, at one transaction per placement. Record the cost; undo is `deleteSequence`, so multi-transaction is acceptable. |
| **Three-point passes but audio is video-only or misaligned** | Not shippable as-is for a rough cut. Decide explicitly between a second placement call per range for audio, or falling back to probes 2/3. Never ship a silent rough cut. |
| Editable cross-sequence range copy passes | Build the native assembly MVP. |
| Subsequence creation passes, but append does not | Record partial feasibility; a new sequence per mark does not satisfy this request. |
| Only nested insertion passes | Present it as a distinct option requiring a product decision. A nest keeps a dependency on its source and hides individual tracks in the destination. |
| Native methods fail fidelity or recovery checks | Keep the current working XML mode. Report the specific blocker and propose a separately scoped fallback. |

Do not silently fall back to XML, nesting, rendered clips, keyboard automation, or undocumented QE calls under the direct-edit button. Those change the promised behavior.

**Completion criterion:** a written matrix identifies every supported source condition, the chosen native operation sequence, exact timing rules, undo behavior and known limitations. Production implementation starts only for the proven subset.

## 5. Implementation structure

Keep existing XML recovery and native assembly state separate.

| File | Responsibility | State |
| --- | --- | --- |
| `uxp/cutdeck/timelineRange.js` | Capture and normalize exact marks, source identity, timing and preflight data. | ✅ built |
| `uxp/cutdeck/assemblyPlan.js` | Pure range intersection and destination placement; no Premiere calls. | ✅ built |
| `uxp/cutdeck/capabilityProbe.js` | Phase 0 probe 1, read-only. Not originally listed. | ✅ built |
| `uxp/cutdeck/assembleProbe.js` | Phase 0 probe 1b, mutating. Not originally listed. | ✅ built |
| `uxp/cutdeck/assemblyHost.js` | Native capability checks, destination creation, append operations, validation and recovery. | ⛔ blocked on Phase 0 — do not write it before a backend is chosen |
| `uxp/cutdeck/assemblySession.js` | Bound source/destination IDs, operation journal and session reconciliation. | ⛔ same |
| Existing `main.js` / `index.html` | Add the assembly controls and status states; retain automatic XML controls. | partial — probe buttons only, no assembly controls |
| `tests/cutdeck_assembly.test.cjs` | Timing and host-boundary behavior tests. | ✅ 29 tests |
| `tests/cutdeck_assemble_probe.test.cjs` + `tests/fixtures/cutdeck_assemble_host.cjs` | Mutation-probe orchestration against a mock timeline. | ✅ 32 tests |

These are proposed seams, not a requirement to create empty abstractions. Merge small modules where it simplifies the actual implementation. Reuse the existing identity/capture code where compatible, but preserve the XML protocol's expected fields and behavior.

Native assembly must initialize and operate with the helper stopped. ✅ The startup socket diagnostic is behind an explicit button and no longer runs on load; both probes run with the helper stopped.

## 6. Timing and clip placement

Use decimal tick strings across persistence and host boundaries. Use exact integer arithmetic internally where the UXP runtime supports it; verify `BigInt` support and serialize explicitly. Do not convert Premiere ticks to JavaScript `Number` for calculations. Use the sequence's actual timebase rather than assuming a constant frame rate.

After normalizing the mark convention, let the selection be `[I, O)`, append cursor be `D`, and a source timeline item occupy `[S, E)`:

```text
overlapStart = max(S, I)
overlapEnd   = min(E, O)
include item only when overlapEnd > overlapStart
destinationStart = D + overlapStart - I
destinationEnd   = D + overlapEnd - I
nextAppendCursor = D + O - I
```

For an ordinary forward 1x item, adjust its source-media In by the trimmed timeline offset. Do not apply that equation to speed ramps, reverse playback, remapped time or unsupported nested media. Preserve source track indexes unless a validated mapping is explicitly chosen.

The append cursor is the end of the whole selected interval, including trailing gaps; it may differ from the last visible clip's end. If the target was manually edited, reconcile against a stored structural snapshot and stop for an explicit rebind/new session when intent is ambiguous. Never blindly reuse a stale cursor or derive it only from `getEndTime()`.

A wholly empty interval produces “No clips in the marked range” without creating a destination. An interval with clips and internal gaps retains those gaps.

## 7. Session and mutation contract

Suggested persisted fields:

```json
{
  "schemaVersion": 1,
  "sessionId": "generated-id",
  "projectId": "premiere-project-guid",
  "sourceSequenceId": "source-guid",
  "destinationSequenceId": "destination-guid-or-null",
  "ticksPerFrame": "exact-integer-string",
  "appendCursorTicks": "0",
  "lastVerifiedDestinationFingerprint": "structural-fingerprint",
  "pendingOperation": null,
  "completedOperations": []
}
```

Each operation records its own ID, captured source range and fingerprint, expected destination start/end, pre-mutation destination fingerprint, state and verified inserted item identities where available. Fingerprints describe relevant timeline structure and settings; do not assume Premiere exposes a universal revision counter.

Operation flow:

1. Acquire the panel busy guard, read live source marks and resolve the bound project/source by GUID.
2. Preflight all intersecting content and destination state. Build the complete plan before mutation.
3. Persist a pending operation before making a host change. If persistence fails, do not proceed.
4. Prepare necessary asynchronous reads, then revalidate identity and relevant state immediately before commit. Use the supported locking model; avoid holding a lock across asynchronous work.
5. Create a destination only when needed, using the Phase 0 method that preserves settings. Record its ID immediately. Treat creation and append as separate recovery boundaries if the host does.
6. Build fresh native actions and execute the append using the validated transaction sequence. Aim for one named Undo entry per add; report actual limitations if host APIs cannot provide it.
7. Verify inserted boundaries, track placement and destination state after commit. Mark success only after verification.
8. Persist the receipt and next cursor, preserve source focus and release the busy guard.

Suggested states: `idle → validating → applying → verifying → ready`, with terminal branches `unsupported`, `failed` and `needs_reconciliation`.

On reload or uncertain completion, inspect the bound destination and pending operation before another add. If the append is verifiably present, finalize its receipt. If absent, allow an explicit retry. If ambiguous, block another mutation and explain what needs inspection. Never replay an uncertain append automatically.

Native Undo/Redo can invalidate panel history. Re-read target structure before the next action; reconcile verified Undo/Redo where possible, otherwise stop with an actionable message. Do not automatically issue Undo after an unrelated user edit, and never delete an ambiguous destination as cleanup.

## 8. Supported subset and fidelity

Start with the repository's practical target: ordinary forward 1x clips, linked A/V, and stacks of already-synchronized raw clips. Expand support only after fixtures prove it.

Preflight transitions crossing selection boundaries, speed changes, nested/multicam clips, adjustment layers, captions, graphics, track effects, clip effects/keyframes, locked tracks, mute/disable state, offline media and unusual audio channel layouts. Each gets an explicit supported or unsupported result. Do not silently drop an item or effect.

For v1, reject locked destination tracks intersecting the planned write. Source locked-track behavior must be documented by the spike: the source is read-only, but host copy semantics still need validation. Track targeting alone must not unexpectedly omit audio or a camera angle.

Matching settings includes frame rate, frame size, pixel aspect, audio sample rate/channel configuration and relevant color/sequence settings. If a chosen creation method cannot preserve required settings, it fails preflight for that source.

## 9. Delivery phases and exit criteria

### Phase 1 — exact range model and tests — ✅ COMPLETE

Implement normalized range capture, placement calculations and session validation. Cover a one-frame range, boundary-touching clips, nonzero media In, nonzero sequence timecode, 23.976/29.97 timebases, gaps, overlapping tracks and large tick values.

**Done when:** pure tests demonstrate exact expected frames and no floating-point drift; no production timeline mutation is enabled yet.

**Met** by `timelineRange.js` + `assemblyPlan.js` under `cutdeck_assembly.test.cjs` (29 tests), covering every case listed plus fifty consecutive adds at zero drift and tick values past `Number` precision. Session validation is **not** in this phase's delivery — it moved to `assemblySession.js`, which stays unwritten until Phase 0 picks a backend.

### Phase 2 — proven native backend

Implement only the backend selected by Phase 0. Add preflight, matching destination creation, repeated append, verification and identity-based recovery. Test destination rename/deletion, project switching, failure between stages and uncertain completion.

**Done when:** supported fixtures append twice to the same sequence, source fingerprints remain unchanged, and recovery prevents duplicate or misdirected edits.

### Phase 3 — panel workflow

Add the primary button, source/destination display, busy states and secondary navigation. Native mode works without the helper. Use messages such as “Mark In and Out on your source timeline,” “Added 13 seconds to Rough Cut,” and specific unsupported-feature explanations.

**Done when:** mark → add → mark → add is possible without a file dialog or automatic navigation away from the source.

### Phase 4 — live acceptance and documentation

Run the matrix below in Premiere. Update `uxp/cutdeck/README.md` with supported builds, limitations, Undo behavior and the distinction between manual assembly and automatic cleanup. Record actual evidence in the repository's existing maintenance tracking.

**Done when:** all supported cases pass, unsupported cases fail before mutation, existing XML tests remain green, and the handoff includes observed timings and any unresolved host limitations.

## 10. Acceptance matrix

| Scenario | Required outcome |
| --- | --- |
| First selection | Exactly one destination; marked range copied with correct boundaries. |
| Second selection | Same destination; appended once at the stored interval end. |
| Repeated click while busy | One operation only. |
| Deliberate repeat | Explicit Add Again adds a second instance. |
| Missing/reversed/empty marks | Clear message; no project mutation. |
| One-frame and NTSC ranges | Exact included frames; no cumulative drift. |
| Multitrack linked A/V | Relative timing and links preserved; playback in sync. |
| Leading/internal/trailing gaps | Range layout and next append position preserved. |
| Unsupported content or locked destination | Specific preflight failure; source and destination unchanged. |
| Rename destination | Bound GUID still resolves correctly. |
| Delete destination or switch project | Stop; never silently choose a same-named sequence. |
| Reload during append | Reconcile; never duplicate an uncertain operation. |
| Undo/Redo or manual target edits | Session reconciles or requires explicit recovery. |
| Helper stopped | Manual assembly still works. |
| Existing automatic XML mode | Existing range handling, import identity and recovery still pass. |
| 50 consecutive selections | No source changes, drift, duplicate media imports or unexpected sequence growth. |

Run the existing Node workflow/RPC tests plus new assembly tests. Run relevant Python tests only if shared Python behavior changes. Host mocks validate orchestration; they do not establish Premiere editing fidelity. Live acceptance is required to claim support.

Measure first-add setup separately from warm adds, using a short source and a long source with similar marked ranges. Record median and slowest warm-add time over at least 20 operations, host build and clip count. A useful provisional target is under one second for a simple warm add; it is a target, not a current performance claim. Explain any scaling with total timeline size.

## 11. Optional follow-on: automatic cleanup within the marks

If the intended end state is “mark this part and automatically remove its silence,” retain that as a separate feature:

1. Capture the marked timeline interval and analyze only the required audio window plus documented context.
2. Reuse the existing CutPlan/rules and exact time conversion rather than introducing a second detector.
3. Translate retained intervals back to source-sequence time and feed the proven native assembly backend.
4. Revalidate the source after analysis; refuse stale plans when media placement or relevant settings changed.
5. Verify word protection at range edges and parity with the established cleanup behavior before changing defaults.

This still needs audio access and analysis; removing XML does not remove transcription cost. Directly ripple-deleting the current sequence is another scope with separate undo and synchronization requirements. It is not part of this append-to-rough-cut MVP.

## 12. Final handoff requirements

Deliver the native capability findings, implementation and focused tests, live fixture evidence, updated usage documentation, measured latency and a clearly stated supported subset. If the host cannot support the desired operation, deliver the specific failed capability and tested alternatives instead of describing an unproven approach as complete.

Start with Phase 0. The key question is whether this Premiere build can copy a marked timeline range into a persistent destination with the fidelity and recovery behavior above.
