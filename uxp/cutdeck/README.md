# CutDeck for Premiere

**Role: production.** This is the only CutDeck panel. Install via the packaged `.ccx` (issue #40); no UXP Developer Tool needed. It talks to the helper on `ws://127.0.0.1:7891`.

Mark **In / Out** on the timeline and click **Rough Cut**. The panel captures
the sequence's audio tracks as JSON. The helper analyses source audio and returns
frame cuts; the panel applies them to a **copy**, checks the result clip by clip,
files it under **CutDeck > Rough Cuts**, then opens it. Your original stays untouched.
Split pieces' audio is unlinked from video. Large cuts may need more than five Undo steps.

XML-file input and XML rewriting are retired. Use the panel or the MCP
`premiere_rough_cut` tool. Before applying a newly analysed cut list, the panel checks
that the source audio snapshot and sequence duration still match; a changed source
requires a new analysis. See [the current architecture](../../docs/rough-cut.md).

While the panel is open it is also the helper's **Premiere driver**: MCP agents
(`premiere_*` tools) and scripts (`python -m cutdeck.premiere_cli status | read_sequence |
apply_cuts <job_id> | add_markers <file.json>`) reach Premiere through it, with a fixed
command list. A command is refused while the panel is busy with your own action.

## First-time setup

1. Use Premiere **26.2 or later** (this machine currently has 26.5).
2. In **UXP Developer Tool**, add this plugin if it isn't already added
   (**Add Plugin**, select `uxp/cutdeck/manifest.json`), then use its **⋮**
   menu → **Package**. First time only, UDT prompts to generate a
   self-signed certificate — any placeholder name/org/email is fine, this is
   for local install, not Marketplace distribution. UDT writes `cutdeck.ccx`
   next to the plugin folder.
3. Double-click `cutdeck.ccx`. This hands off to Creative Cloud Desktop's
   installer (must be running); confirm the install prompt.
4. **Fully quit and reopen Premiere Pro** (not just close/reopen the
   project) so it re-scans installed plugins.
5. Open the **CutDeck** panel from Premiere's **Window > UXP Plugins** menu.
   No UXP Developer Tool needs to be running or even installed at this
   point. Accept Premiere's plugin permissions if prompted.

Nothing to start by hand for the helper: the first time a session clicks
**Rough Cut In–Out**, **Sync Multi-Cam**, or **Resume last job** and the
helper isn't already answering, the panel launches it itself via UXP's
`shell.openPath` on `Start CutDeck (Hidden).vbs` and waits (up to 15s) for it
to come up. Premiere will ask for one-time consent to launch it; accept it.
No console window appears — the `.vbs` wrapper runs `Start CutDeck.cmd`'s
python process hidden (UXP itself has no way to pass a hidden-window flag,
so the wrapper does it instead) — and it uses this project's existing
`.venv`, models, configuration, and FFmpeg installation.
If it doesn't come up and you need to see why, run **`Start CutDeck.cmd`**
directly instead — the hidden path gives no visible error on failure.

### Development (source-load, no packaging)

Enable **Developer Mode** in Premiere's Plugins preferences and UXP Developer
Tool (version 2.2 or later). In **UXP Developer Tool**, choose **Add Plugin**,
select `uxp/cutdeck/manifest.json`, and click **Load** with Premiere running.
Open the **CutDeck** panel from Premiere's **Window > UXP Plugins** menu.
Accept Premiere's plugin permissions if prompted. Installing the `.ccx`
above does not remove the ability to source-load this way too — the two
coexist.

**Recommended for daily use:** register
`Start CutDeck.cmd` as a Windows Scheduled Task that runs at login, instead
of relying on the panel's launch-on-click fallback above. It avoids the
one-time consent prompt entirely, and the helper is simply already there
every session, without needing launch-on-click consent prompts. The panel's own launch (previous step) exists for
when that isn't set up, not as a replacement for it.

## Use

1. Open your source sequence. Set timeline In and Out marks. The panel reads
   them automatically on open; click the refresh icon (top right) or the
   sequence card to re-read after changing the marks.
2. Leave **Reference Audio** on its default to select the dialogue
   command, or select a specific Premiere audio track.
3. Leave the **Speech + Silence** preset selected for aggressive silence
   cutting with ASR protection for short speech. **Silence Only** skips ASR,
   just like the existing command's `-NoAsr` switch.
4. Click **Rough Cut In–Out**. CutDeck creates a sequence
   named `Your sequence — CutDeck <job identifier>` and opens it, filed in a
   **`CutDeck` bin in the Project panel** (created once, on first use, at the
   project root — every result after that lands in the same bin instead of
   scattering at the root).

**Sync** needs no marks or Reference Audio. Lay every camera's clips and the recorder's
files in a row on one sequence and click Sync. The helper matches each clip by its own
audio; the panel copies the sequence to `Your sequence_Synced` and, in one step (one
Ctrl+Z), puts each synced clip on its own video and audio tracks. Clips that match nothing
sit flat on the first tracks after a 30 s gap, and the status line says why. Your
sequence is not edited, and Sync refuses to run on a `_Synced` copy.

The diagnostics drawer (gear icon, top right) holds the read-only timing
probe, the connection probe, and copy-status.

The result is a native Premiere sequence, not a file to import. Analysis files
(`sequence.json`, `cuts.json`, `job.json`, `process.log`) stay in
`output/premiere/<job identifier>/`. No XML is exported or written beside footage.

The source sequence is never edited. Material before In is preserved; material
after Out shifts earlier by the removed duration across all tracks. Only the
In/Out range plus 2 seconds each side is extracted and analyzed, so a short range
on a long sequence is fast.

Before any audio is extracted, the helper checks the read and refuses clearly:
the Reference Audio track (with no choice made, the first track that is not muted
and has clips; a track you pick is used even if it is muted), missing or
offline source media, source media with no audio stream, and audio clips with no
media file (nested sequences). Transitions and nested clips where a cut lands are
refused by the native cut. While it runs, the status line names the track and file being analyzed
(for example `A2 (interview.wav)`). If processing fails, the message quotes the
error from `process.log` instead of only an exit code.

Track indices are Premiere audio tracks (A1 is 0), independent of channel count.
Audio extraction reads original source media; it does not render Premiere gain,
EQ, panning or crossfades.

## Recovery

- **Connection lost / panel reloaded:** click **Resume last job** — it launches
  the helper again if needed. While the same helper remains running, processing
  continues even if the panel disconnects.
- **"Permission denied to the url ws://127.0.0.1:7891":** UXP registers the plugin's
  network permission later than the panel's first request, so a cold start can be
  denied even though the manifest declares the domain. The panel now retries the
  connection five times over about three seconds, which also covers a helper that is
  still starting up.
- **"Cannot reach CutDeck helper" persists after accepting the launch prompt:**
  `shell.openPath` cannot report why a launch failed beyond an error string, and
  cannot run hidden or pass arguments — if `Start CutDeck.cmd` itself has a problem
  (no Python found, a broken `.venv`), its console window says so. Run it manually
  once to see the real error.
- **Source changed during analysis:** the stale result is discarded before any copy or edit.
  Click Rough Cut again to analyse the current source. Older saved JSON results without
  a source snapshot retain their previous identity checks; start a new job for this guard.
- **Switched sequences:** the cut is only applied to the sequence it was analysed
  from. Open it again and click Rough Cut (it resumes the pending job).
- **Helper restarted:** its live job list is reset and the pending job clears
  itself. Existing files remain in `output/premiere/<job identifier>/`. Start a new job.
- **Cut doesn't match the plan:** the copy is left open for inspection and the
  status names the first mismatched clip. Your original sequence is untouched.
- **Dismiss last job:** clears the panel's recovery entry so you can start again.
  It does not cancel a running analysis or remove job files.
- **Processing failed:** inspect `process.log` in the job folder. `job.json` and
  `cuts.json` record the captured range and result. Job files are retained;
  they are not automatically deleted.

The helper runs one GPU job (rough cut, transcription) at a time; Sync matching runs
beside it in its own lane. It listens only on `127.0.0.1:7891` and accepts only
predefined job operations. Job progress is pushed to the panel (no polling), and a job
still reads back after a helper restart (a job that was running reads as interrupted).
Stop it with Ctrl+C in its window when finished.

## Verification status

Offline checks cover JSON analysis, exact CFR/NTSC timing, reference-track selection,
range offsets, speech protection, helper restart/reconnection, worker errors, source
snapshot refusal, exact native golden output and bounded stale-handle recovery.
The captured XML native-plan golden remains an independent fixture; its bytes are frozen.

Live Premiere still needs confirmation: run the repaired workflow on the previously
failing sequence and check playback, first/last removed frames, track alignment, the
retained original and clip-by-clip read-back. Offline fakes cannot prove host commits.
Native edits refuse unsupported transitions, nested/multicam clips and retimed clips
where cuts land. A native razor is not used without an installed-host probe.

## Layout

The panel follows the layered architecture and conventions defined in [docs/arch-design-cutdeck-panel.md](../../docs/arch-design-cutdeck-panel.md):

- **UI Seams (`core/`):** `core/panel.js` and `core/alignPanel.js` own all DOM access under a pure `render(state)` / `bind(intents)` contract. Styling is tokenized in `core/theme.css`.
- **Composition & Controllers (`main.js`):** Composition root wiring UI intents to feature actions and host operations.
- **Timeline & Host (`timeline/`, `transform/`):** Resolution detection, adjustment layer creation/placement, keyframe capture/apply, and native transform geometry.
- **Conventions:** Layer rule (Composition → UI → features → domain → host → `premierepro`), single owner per host concern, direct in-place editing under `uxp/cutdeck/core/` (no source mirror). See the module table and conventions in `docs/arch-design-cutdeck-panel.md`.

## Development


```powershell
.venv\Scripts\python.exe -m cutdeck.helper
.venv\Scripts\python.exe -m pytest tests/test_cutdeck_premiere.py tests/test_cutdeck_rough_cut_cli.py -q
node --test tests/cutdeck_assembly.test.cjs tests/cutdeck_workflow.test.cjs tests/cutdeck_rpc.test.cjs
```

`workflow.js` captures sequence audio and validates source identity before native apply;
`core/rpc.js` owns the helper socket and pushed events; `features/driver.js` serves
fixed Premiere commands. `cutdeck/helper.py` owns persisted jobs and launches
`python -m cutdeck.rough_cut` to analyse JSON. Shared extraction is in
`cutdeck/audio_extract.py`, exact timing in `cutdeck/sequence_timing.py`.

The helper on port 7891 is the one server to start (`Start CutDeck.cmd`). The old
`python -m cutdeck.xml_bridge` command only forwards to this helper. The old
`cutdeck.xml_recut` and `scripts/cut_xml.ps1` commands stop with replacement instructions.
For offline JSON analysis use `python -m cutdeck.rough_cut sequence.json --cuts-json cuts.json`;
optional frame bounds are a half-open interval. XML input and output are unsupported.

API references checked during implementation:

- [Project import and sequence operations](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/project)
- [Sequence marks](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequence)
- [TickTime](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/ticktime)
- [UXP networking](https://developer.adobe.com/premiere-pro/uxp/resources/recipes/network/)
- [Adobe sample manifest](https://github.com/AdobeDocs/uxp-premiere-pro-samples/blob/main/sample-panels/premiere-api/public/manifest.json)
- [Component / ComponentParam](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/component) —
  reading/setting real effect parameters
- [VideoComponentChain](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocomponentchain) /
  [VideoFilterFactory](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videofilterfactory) —
  listing and applying real effects (`timeline/effects.js`)
- [AdobeDocs sample: effects.ts](https://github.com/AdobeDocs/uxp-premiere-pro-samples/blob/main/sample-panels/premiere-api/src/effects.ts) —
  the `executeTransaction`/`createInsertComponentAction` shape `effects.js` follows

### Run the keyframe probe (gates animated presets)

**Check Keyframes** (diagnostics drawer) is read-only. It answers the one thing blocking
animated presets: are keyframe times counted from the sequence, the clip's first frame, or
the source media? It also records this build's interpolation-mode numbers (Linear/Hold/Bezier).

1. Pick a clip that starts **later than 0:00** on the timeline **and is trimmed at its head**
   (its In point is not the media's first frame). Speed at 100%. Otherwise two readings
   coincide and the probe correctly refuses a verdict.
2. Select only that clip. In Effect Controls, turn on the Scale stopwatch so it keyframes at
   the playhead. Move the playhead, add a second keyframe, right-click it > **Bezier**.
3. Move the playhead **back onto the first keyframe** and click **Check Keyframes**.
4. Read the VERDICT, then copy the full report (also JSON in the UDT console) somewhere
   before animated presets are built on it.

### Quick-effect preset buttons (Adj & FX page)

Below the Adjustment Layer card, at least `MIN_QUICK_PRESETS` (9, in
`core/panel.js`) captured presets each get their own button, laid out as a 3x3 grid of
small buttons. Same Click/Ctrl+Click/Shift+Click gestures as the Adjustment Layer card itself
(span / per-clip / 50-50 cut transition) — clicking one both places the AL that way AND
applies that preset's real captured effect to every AL it just placed, via
`timeline/effects.js`'s `applyCapturedPreset`. One combined action, same as the Adjustment
Layer card, just per-preset. The old quick frame-length cycle badge was removed — the
Transition (50/50) frame length is still set in Settings (frame stepper / mini pills).

**Capture** (Settings > Presets) is the only way to fill a slot: select a clip or Adjustment
Layer that already has a real effect applied to it in Premiere, name it, click Capture — it
reads the item's actual `VideoComponentChain` via `effects.js`'s `captureEffectFromTrackItem`
and saves it to its own `localStorage` key (`cutdeck.fx.presets`), separate from
`cutdeck.adj.settings` so a bad/oversized preset can't corrupt core settings.

Below the Capture row, every captured preset gets a rename/remove row
(`#fx-preset-manage-list`, `core/panel.js`'s `renderPresetManageList`/
`bindPresetManage`): edit the text field (renames on blur/Enter) or click × (removes it and its
quick-effect button immediately — no confirmation, same as every other destructive action in
this panel). Rename/remove are plain `localStorage` writes, not Premiere calls, so they're
wired directly through `main.js`'s `onRenamePreset`/`onRemovePreset` intents rather than
`act()`.

**Where presets are saved** (Settings > Presets > **Choose folder…**, `presetStore.js`): pick a
folder and each preset is its own file there, named after it (`Zoom In.json`). Pick a synced
folder (OneDrive, Dropbox) and choose the same folder on each machine to share one library;
linking a folder writes in any of this machine's presets it doesn't already have. Removing a
preset (×) moves its file into a `Removed` subfolder, never deletes it. Other `.json` files in
the folder are ignored; a CutDeck preset file that can't be read is reported and left
untouched. An older single `cutdeck-presets.json` is split into per-preset files on load and
renamed to `.migrated`. With no folder chosen, presets stay in this plugin install's
`localStorage` only.

**Animated presets:** Capture includes keyframes. Each keyframe is stored as an offset from the
captured clip's first frame and replayed at the same offset from each Adjustment Layer's
start, with its Linear/Hold/Bezier interpolation. It is not stretched to fit, so a 5-frame zoom
stays 5 frames long. This rests on the **Check Keyframes** result from Premiere 26.5
(keyframe times are relative to source media). Position/Anchor Point interpolation can't be
read (Premiere's `PointKeyframe` has no getter), so those keep Premiere's default. After
applying, CutDeck reads the keyframes back and names any that didn't land as captured.
Premiere's own Motion is still skipped, so animate the **Transform** effect, not Motion.

**Historical note (before Check Keyframes ran):** a captured Keyframe's
`TickTime` convention (clip-relative vs. sequence-relative) isn't documented anywhere in
Adobe's reference, so animated presets (the old Zoom In/Whip Pan/Camera Shake-style names)
are a deliberate later step, gated on the **Check Effect Chain** probe (diagnostics drawer)
the same way `timelineRange.js`'s `OUT_CONVENTION` was gated on Check Timing. Run that probe
against a plain, effect-free Adjustment Layer first — it confirms this build's real
fixed-effect matchNames (Motion/Opacity/Time Remapping), which `effects.js` currently guesses
by display name.

There is deliberately no built-in-effect browser any more (`VideoFilterFactory.getDisplayNames`
listing every installed effect) — presets are captured-only. That code path was built, worked,
and was removed once it was clear captured presets were the only source wanted; see git
history on `timeline/effects.js` if a live effect browser is wanted back later.
