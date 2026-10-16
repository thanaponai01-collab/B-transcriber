# Premiere native cutter for CutDeck Rough Cut — 2026-10-16

## Scope and result

The requested feature is a cutting backend for the existing Rough Cut button. No manual toolbar, extra editing controls, or ASR changes are proposed.

**Observed live:** Premiere Pro 26.5.2 does not expose native razor or range lift/extract to the tested ordinary third-party UXP plugin. The native descriptors are present in the executable, but their presence does not make them callable through the public panel API.

**Recommended investigation route for this installed version:** a small native Control Surface SDK plugin that accepts narrowly defined cutting requests from the existing helper and dispatches Premiere host commands. This is a source-supported integration candidate, not a tested Windows cutting implementation. A newer public native-razor API is the simpler alternative when a compatible installed host can be verified.

## Evidence

### Installed executable

- Path: `C:\Program Files\Adobe\Adobe Premiere Pro 2026\Adobe Premiere Pro.exe`
- Windows file version: `26.5.2.5`; live UXP host version: `26.5.2`.
- SHA-256: `b24e2b442a8e0350edbc0c214d2fcae2f68c7d9843ae399e5058d5b5a6786094`.
- Shell exact-byte scan found `createRazorTrackAction` at file offset `640596456`, `createRazorAllTracksAction` at `640596656`, `createLiftActionInRange` at `640595392`, and `createExtractActionInRange` at `640595456`. Offsets refer to original file bytes, not virtual addresses.
- Nearby strings describe native cutting behavior. These are descriptors, not proof of execution or full native control flow. Ghidra was unavailable; no native decompilation is claimed.
- The embedded UXP facade loads `SequenceEditor` from `host/mediaCoreBackend` using `torq-native`, then adds public wrappers. The adjacent embedded API catalog lists add/remove methods for SequenceEditor and omits razor/lift/extract. The catalog's enforcement role was not established.
- Facade reconstruction concatenated exact adjacent embedded chunks at `(655664256,16000)` and `(655680272,8252)`; reconstructed JavaScript parsed without execution. SHA-256: `2488f74ad5a36f7ae254ab29dbd2ee1fb94129e2718d39ffff12f9282a9da8f6`.
- REA facade analysis parent: `ev_629d2ba55e8148bec7b99532830ccf62f70bacc1fb765a58cca5ffb290064b54`. Static graph coverage remains partial/unknown for dynamic native relationships.

### Read-only live probe

A temporary manifest-v5 plugin with its own ID (`com.cutdeck.cutter.reaprobe`) was validated and loaded through the already-running UXP Developer Tools. It used normal third-party access, without private dependency declarations or Adobe identity impersonation.

The probe inspected both `SequenceEditor.prototype` and `SequenceEditor.getEditor(activeSequence)`:

| Member | Observed type in both locations |
| --- | --- |
| `createRazorTrackAction` | `undefined` |
| `createRazorAllTracksAction` | `undefined` |
| `createLiftActionInRange` | `undefined` |
| `createExtractActionInRange` | `undefined` |
| `createRemoveItemsAction` | `function` |
| `createCloneTrackItemAction` | `function` |

`require('uxp').dvascripting` and `.mediaCoreBackend` were also `undefined`. An active project and sequence were present; the sequence timebase was `10160640000` ticks/frame. No actions were created or executed, no sequence was opened or switched, and no project was saved. The probe plugin was successfully unloaded afterward.

This runtime result was obtained with a shell CDP client through Adobe's UDT bridge. It is not a REA passive-runtime Evidence record. Raw response: `probe-runtime-result.json` in the retained investigation directory.

### Bridge candidate

[Adobe's Control Surface SDK guide](https://ppro-plugins.docsforadobe.dev/control-surfaces/control-surfaces/) establishes the native plugin lifecycle and host-suite mechanism. The [premiere-xpress author's SDK reference](https://github.com/alexlinde/premiere-xpress/blob/main/CONTROL_SURFACE.md) describes `ControlSurfaceHostCommandSuite` command enumeration and `ExecuteCommand(contextID, commandID)`. That example project is macOS-oriented; it is not proof of a working Windows bridge.

The installed default keyboard XML contains `cmd.sequence.razorateditline`, `cmd.sequence.razorateditline.all`, `cmd.sequence.extract`, and `cmd.sequence.lift`. Runtime enumeration must establish their actual availability and context through the SDK before using them. Do not guess command context or treat shortcut definitions as a callable UXP dispatcher.

## Fit into the current rough-cut engine

1. Keep `workflow.js`, helper audio analysis, `cuts_frames`, exact ticks, source-snapshot guard, and `cutPlanApply.js`.
2. Start the native bridge spike with **native splits only**, replacing filler creation, filler trimming, overwrite cloning, and filler cleanup in `timeline/nativeCut.js:applyPlan`. Retain the existing explicit non-ripple removal and calculated per-item gap closure initially. This avoids changing splitting and multitrack ripple semantics simultaneously.
3. Keep all mutations on the existing sequence copy. Native commands may require that copy to be open/active, unlike today's closed-copy apply path. The spike must establish target binding before mutation; a read-before/read-after check alone does not prevent a user switching sequences during dispatch.
4. Marshal SDK dispatch through the host-supported callback/update mechanism. Expose a bounded operation such as `split_at_ticks` to CutDeck, rather than an arbitrary command or code-execution endpoint. The helper owns transport and request lifecycle; the native plugin owns host dispatch.
5. Read back the exact planned pieces and verify source identity, timing, effects/keyframes and A/V link behavior. Do not infer link preservation from matching positions or a successful command return.
6. Treat native Extract as a later candidate for replacing delete/move stages, only after targeted tracks, locked tracks, sync-lock, overlaps, transitions and empty-space intervals have been demonstrated correct.

## Remaining implementation gates

- Adobe C++ SDK headers and a Windows build toolchain were not located in the paths checked; no SDK or compiler was installed.
- Verify command enumeration/dispatch, exact frame-boundary semantics, native target identity, A/V links, cancellation, undo and helper/host disconnect behavior on disposable sequences.
- Compare linked A/V, multichannel audio, late cameras, gaps, overlaps, locked tracks, nested/multicam clips, speed changes and effects against the existing planner. Unsupported cases must remain explicit.
- Benchmark equivalent completed rough cuts only after correctness passes. No token, elapsed-time, CPU or memory performance improvement is claimed from fewer proposed actions.
- Do not integrate a partial bridge or silently fall back mid-job. Failed or partially applied copies must retain the current failure/recovery behavior.

## Retained local evidence

The investigation directory contains `facade-provenance.json`, `premiere-uxp-facade.js`, the embedded API catalog, the probe source and raw result, and `rea-evidence.json`. The portable REA bundle includes artifact inventories and static analyses; its bundle-level unknown count does not override the partial semantic coverage recorded inside analyses. Raw extracted Adobe code and the 93 MB bundle should remain local and must not be committed.

No CutDeck application code or UI was changed. This report and the facts row record the completed read-only investigation; the bridge remains unimplemented and unverified.

### Native host diagnostic, 2026-10-16
Observed on actual Premiere process 37516: EntryPoint, Startup, Connect and acquisition of HostSuite1 and HostCommandSuite1 succeed. HostSuite.GetCommandRef rejects the supplied host reference with kSPBadParameterError (1348563565 / 'Parm'); no catalog and no command execution. Retained lifecycle trace: output/native-cutter-spike/live/lifecycle-37516.jsonl. SDK sample registers the plugin-side CommandSuite1; the initial minimal probe did not. A zero-button CommandSuite1 experiment now compiles and passes the synthetic host checks, including explicit command-ref failure cleanup; its effect on real Premiere is unverified. This is a hypothesis, not an established root cause. Production rough-cut behavior is unchanged.

### Command catalog on real Premiere, 2026-10-16
The revised read-only build, which registers the plugin's own zero-button `CommandSuite1`, ran on real Premiere (PID 35300). Every lifecycle stage reported error 0, including `get_command_ref`, `get_command_count` and `catalog_finished`. The catalog is `complete: true`: 1,417 reported, 1,417 examined, 0 errors, contiguous indices, 19 contexts, and no duplicate (context, command) pairs. The 112 repeated command IDs are the same commands listed under different contexts. The cutting commands are present under context `global` (Application): `cmd.sequence.razorateditline` "Add Edit" (index 567), `cmd.sequence.razorateditline.all` "Add Edit to All Tracks" (568), `cmd.sequence.lift` "Lift" (553) and `cmd.sequence.extract` "Extract" (545). So the missing plugin-side `CommandSuite1` was the cause of the earlier `kSPBadParameterError`. Nothing was run. What these commands act on (active sequence, playhead, targeted tracks), their frame-boundary behaviour, undo, and A/V links are all still unproven, and must be tested on a disposable sequence first. Evidence: `output/native-cutter-spike/live/lifecycle-35300.jsonl` (sha256 c7b89360…) and `commands-35300-29954531-1.json` (sha256 51f1d2a5…).

## Plan: one Add Edit on a disposable sequence

Goal: one native `cmd.sequence.razorateditline.all` on a throwaway sequence. Prove it cuts the intended sequence at the intended frame, changes nothing else, keeps A/V links, and is undone by one Ctrl+Z. Nothing is integrated into Rough Cut.

### What each side can do (sources)

- **Native (SDK headers):** `ControlSurfaceHostCommandSuite1` has only `Navigate`, `GetCommandCount`, `GetCommand` and `ExecuteCommand(ref, contextID, commandID)`. There is no argument for sequence, time or track. `ControlSurfaceHostTransportSuite` can read `GetTimeDisplayString` and step or jump the playhead, but it cannot seek to a time. The plugin's `ControlSurfaceSuite.Update` is the host's periodic callback; dispatch happens there, never on a plugin thread.
- **UXP (`reference/adobe/api/premierepro.txt`):** `Project.setActiveSequence`, `getActiveSequence`, `Sequence.setPlayerPosition` / `getPlayerPosition`, track `getTrackItems`, item `getStartTime/getEndTime/getInPoint/getOutPoint/getProjectItem/getIsSelected`, `Sequence.createCloneAction`. There is **no track-targeting API and no link read**.
- So binding is done in UXP and execution in native. Native knows nothing about the sequence, so the guard is: UXP sets the sequence and playhead, native refuses unless `GetTimeDisplayString` equals the timecode UXP expects, and UXP re-reads afterwards.

### Choice of command

Use **Add Edit to All Tracks**. Plain Add Edit depends on track targeting and the current clip selection, and UXP can neither read nor set targeting. "All Tracks" is also what Rough Cut needs. The one remaining dependence, locked tracks, is handled by making sure the test sequence has none.

### Fixture

A disposable copy made by `Sequence.createCloneAction` (its own transaction, per facts row) of a short sequence holding **one linked A/V clip** (V1 + A1, plus A2 if the media has two channels), with media at least 10 s long and no effects. Name it `CutDeck AddEdit Probe <nonce>`. Cut point T = start + 120 frames exactly (ticks = 120 × `getTimebase()`), well inside the clip and on a frame boundary.

### Flow (guarded probe button + helper + native)

1. **Panel (UXP), read-before:** clone, find the copy by name, `setActiveSequence(copy)`, `setPlayerPosition(T)`, then read back `getActiveSequence()` (guid matches copy) and `getPlayerPosition()` (== T exactly). Snapshot every item on every track: track, start, end, in, out, project-item path, name. Refuse if any item is selected (`getIsSelected`) or the sequence differs from the fixture shape.
2. **Panel → helper (`core/rpc.js`):** new bounded method `native_split_request {nonce, expected_timecode}`. The helper writes `%TEMP%\CutDeckCutterSpike\request-<nonce>.json` and waits for `result-<nonce>.json` (timeout 10 s). The helper never sends a command ID: the native side hard-codes the one allowed command.
3. **Native, in `Update`:** if a request file exists, delete it first (one shot), compare `GetTimeDisplayString` to `expected_timecode`; on mismatch write `refused`. Otherwise call `ExecuteCommand("global", "cmd.sequence.razorateditline.all")` once and write `{error, timeDisplayBefore, timeDisplayAfter}`. Requests older than 10 s are refused. Requests read before the button exists are not acted on.
4. **Panel, read-after:** re-check the active sequence guid and playhead, re-read every track. **Pass** only if each item spanning T became exactly two items, `[start,T)` and `[T,end)`, with the same project item, `in2 == in1 + (T − start)`, the outer in/out unchanged, and every other item byte-identical. The item count must have grown by exactly the number of tracks crossing T.
5. **Links (manual, no API):** the user clicks the left V1 piece; the panel reads `getIsSelected` on the audio pieces. Linked means exactly the left audio pieces are selected and the right ones are not. Repeat on the right piece.
6. **Undo:** the user presses Ctrl+Z once and the panel re-reads; the result must equal the step-1 snapshot. Then press Ctrl+Shift+Z and the step-4 read must match again.
7. Record a facts row for each outcome (WORKS/CATCH/BROKEN), including any refusal.

### Questions this test must answer (unknown today)

- Does a `global` ExecuteCommand act on the **active sequence**, or on the timeline panel with keyboard focus? Repeat the test once with the Project panel focused. If the cut lands elsewhere or does nothing, binding needs a focus step, and that has to be found before any wider use.
- Is `Update` called while Premiere sits idle, and how often? The lifecycle trace should log the first `Update` and the request pickup latency.
- Does the cut fall exactly on T, or on T ± 1 frame (display rounding vs tick position)?
- Does the edit land as one undo step, separate from the clone?

### Out of scope

Lift/Extract, multicam/nested/speed-changed clips, locked tracks, more than one cut, and any integration into Rough Cut. A failed or refused run leaves the disposable copy for inspection and touches nothing else.

### Build checks before installing

- The synthetic host gains `ExecuteCommand` and transport stubs. The harness must prove: no execution without a request; mismatched timecode is refused; stale requests are refused; exactly one execute per request; the request is deleted before execution; and only the hard-coded command ID is ever passed.
- The panel side follows the existing guarded-probe pattern (`features/probes.js`). Tests run against `tests/fakes/premiere.cjs`, and `node tools/adobe/check-api.mjs` must pass.

### Live Add Edit result, 2026-10-16
Ran on a copy of the `test` sequence in the คชาภา EP35 project (Premiere PID 16332), with one 25 fps clip on V1 and A1. The plugin trace shows `get_transport_ref` 0, `first_update`, `request_consumed`, `execute` and `executed`, all error 0. The panel reported an exact split at 00:00:04:20 (frame 120) on both tracks. The source time continued across the cut, nothing else changed, the playhead and active sequence stayed put, and the source sequence was untouched. Check Add Edit: clicking the left video piece selected only the left audio piece, so links were kept. One Ctrl+Z matched the before-read and Ctrl+Shift+Z matched the after-read, so the cut is one undo step, separate from the copy. The helper took the plugin's result file and the panel kept the full JSON only in the UXP console, so the trace is the retained file evidence. Still open from the plan: whether the cut follows the active sequence when the timeline panel doesn't have focus; a non-zero start timecode; and multi-track, locked-track, multicam, nested and speed-changed clips. Rough Cut integration has not started.

### Focus test, 2026-10-16
Setup: the helper was stopped, the probe started on `test` (making copy `CutDeck AddEdit Probe mvats98t`, active, playhead read back at 00:00:04:20), and the Project panel was focused while the panel retried the helper connection. Then the helper was started. The plugin consumed the request and the timecode matched; `ExecuteCommand` returned 0 and the trace logged `executed`. **Nothing was cut.** The copy read back unchanged: 7 problems, and no 'Your sequence changed'. History lists the copy and rename transactions with no Add Edit entry after them, unlike the first run. Conclusion: `global` Add Edit acts on the focused timeline, not on the active sequence, and its return code does not report whether it did anything. That answers the plan's first open question. A Rough Cut built on this route would need the timeline focused at each dispatch, which neither UXP nor the SDK can set or check, so per-cut read-back is mandatory and a no-op must be treated as failure. The first run likely worked because `openSequence` / `setActiveSequence` left the timeline focused. That is unproven, so it isn't a binding guarantee. Side note: History also shows nine `Copy & Overwrite Selection` entries between the two runs. Neither the probe nor these test steps created them (the plugin trace shows one execute per run).
