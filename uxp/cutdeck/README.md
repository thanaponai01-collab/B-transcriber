# CutDeck for Premiere — XML workflow

**Role: production.** This is the only CutDeck panel — `cep/cutdeck` was retired (issue #41) once Adobe confirmed CEP's retirement and the live acceptance gate (issue #38) passed. Install via the packaged `.ccx` (issue #40); no UXP Developer Tool needed. It talks to the helper on `ws://127.0.0.1:7891`.

Mark **In / Out** on the timeline, click **Rough Cut In–Out**, and continue in
a newly imported sequence. CutDeck automatically exports and imports XML using
the same processing command as `scripts/cut_xml.ps1`. No MCP is involved.

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
every session — the same tradeoff CEP's silent auto-spawn makes, without
needing `child_process`. The panel's own launch (previous step) exists for
when that isn't set up, not as a replacement for it.

## Use

1. Open your source sequence. Set timeline In and Out marks. The panel reads
   them automatically on open; click the refresh icon (top right) or the
   sequence card to re-read after changing the marks.
2. Leave **Reference Audio** on its default to match the working XML
   command, or select a specific Premiere audio track.
3. Leave the **Speech + Silence** preset selected for aggressive silence
   cutting with ASR protection for short speech. **Silence Only** skips ASR,
   just like the existing command's `-NoAsr` switch.
4. Click **Rough Cut In–Out**, or **Sync Multi-Cam** for a multi-camera sync
   using the same In/Out and Reference Audio. CutDeck creates a sequence
   named `Your sequence — CutDeck <job identifier>` and opens it, filed in a
   **`CutDeck` bin in the Project panel** (created once, on first use, at the
   project root — every result after that lands in the same bin instead of
   scattering at the root).

The diagnostics drawer (gear icon, top right) holds the read-only timing
probe, the connection probe, and copy-status.

The rough cut XML is written to a **`CutDeck` folder beside your footage**, named
after the sequence and job, so it sits with the media instead of inside this repo:

```
D:\Footage\CFD 94  interview_A.mp4
  CutDeck    Interview — CutDeck 4f2a1b9c.xml
```

"Beside your footage" means the folder holding the media on the audio track that was
analyzed — the same track the cuts come from. Only the result goes there; `source.xml`,
`job.json`, `report.json` and `process.log` stay in `output/premiere/<job identifier>/`.
If the media cannot be located or written to (a disconnected drive, a sequence with no
audio), the result falls back to the job folder and the panel says so rather than
failing the cut. A run that finds no cuts leaves nothing in your media folder.

The source sequence is never edited. Material before In is preserved; material
after Out shifts earlier by the removed duration across all tracks. The entire
sequence audio is still analyzed, preserving the existing analysis context.
In/Out only limits the final cuts. A short selected range therefore does not yet
make a long sequence fast to analyze.

The helper maps Premiere stereo tracks to their expanded XML channel groups.
Audio extraction otherwise has the same behavior and limitations as the existing
XML workflow: it reads original media, not a rendered Premiere effects mix.

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
- **Switched projects:** return to the original project and resume. The helper
  never imports into whichever unrelated project happens to be active.
- **Helper restarted:** its live job list is reset. Existing files remain in
  `output/premiere/<job identifier>/`. Start a new job, or recover a completed
  `rough_cut.xml` using the existing manual workflow.
- **Import not confirmed:** inspect Premiere's Project panel for the unique result
  name. Resume opens an already imported matching result rather than importing
  it twice. If the result cannot be identified, automatic re-import stops.
- **Dismiss last job:** clears the panel's recovery entry so you can start again.
  It does not cancel a running analysis or remove job files.
- **Processing failed:** inspect `process.log` in the job folder. `job.json` and
  `report.json` record the captured range and result. Job files are retained;
  they are not automatically deleted.

The helper serializes jobs to avoid loading multiple GPU analyses at once.
It listens only on `127.0.0.1:7891` and accepts only predefined job operations.
Stop it with Ctrl+C in its window when finished.

## Verification status

Automated tests cover exact CFR/NTSC range conversion, scoped XML cuts and sync,
stereo-track mapping, unchanged no-cut output, CLI reports, worker errors,
duplicate starts, real WebSocket reconnection, and panel import identity checks.

**Still requires a live Premiere acceptance run:** panel rendering/loading;
XML export with In/Out set still exporting the full sequence; In/Out edge
interpretation; XML import and result discovery; playback/audio sync on the
result. The installed version meets the documented API minimum, but these host
behaviors have not been exercised by the automated tests.

For the first live run, use a short test sequence with stacked tracks, two
silence gaps, and speech on both sides of the marks. Compare with your existing
XML result. Verify the first/last removed frame, track alignment, playable audio,
and that the original sequence is unchanged. Repeat once with no cuts and once
after disconnecting/reopening the panel during analysis.

Existing XML limitations remain: transitions and nested sequences are refused;
keyframed effects at split points can be refused; speed changes are not validated
by the existing transformer. XML recutting removes link groups, so synchronized
clip positions do not imply linked selections when dragging clips afterward.

## Native assembly (in progress — Phase 0/1 only)

A second, separate workflow is being built alongside the XML one: mark In/Out and
append that range to a reusable rough-cut sequence, with no export, no import and
no helper. See `docs/HANDOFF_CUTDECK_TIMELINE_IN_OUT.md`. What exists today:

- `timelineRange.js` — normalizes Premiere's marks into an exact half-open
  `[in, outExclusive)` interval in BigInt ticks.
- `assemblyPlan.js` — pure intersection and placement math (handoff section 6).
- `capabilityProbe.js` — Phase 0 probe 1, behind the **Check Premiere timing
  (read-only)** button.

No production code path mutates a timeline yet. (The `assembleProbe.js` mutation
probe from issue #25 was retired unrun on 2026-09-21: the XML recut route made
native assembly of the *Mark/Apply* kind unnecessary.)

### Run the timing probe (a gesture waiting on a human)

`timelineRange.OUT_CONVENTION` is deliberately `null`, and every call throws until
it is set. Adobe's reference does not say whether `Sequence.getOutPoint()` names
the last **included** frame or the first **excluded** one, and guessing is wrong by
exactly one frame on every single add — invisible once, obvious after fifty.

1. Open any sequence. The helper does **not** need to be running.
2. Set In and Out **on the same frame** (press `I` then `O` without moving the
   playhead). This is the crispest test; any range also works.
3. Click **Check Premiere timing (read-only)**. Nothing is created or changed.
4. Read the VERDICT line, and cross-check `durationIfExclusive` /
   `durationIfInclusive` against the duration Premiere itself shows in the Program
   Monitor. Whichever matches is this build's convention.
5. Set `OUT_CONVENTION` in `timelineRange.js` to `"exclusive"` or `"inclusive"`,
   and record the full report (it is also in the UXP Developer Tool console as
   JSON) on issue #25.

The same report answers the rest of probe 1 in passing: the true ticks-per-frame
and whether it divides 254016000000 exactly at a known rate, what an unset mark
returns on this build, whether `getZeroPoint` exists, and whether this UXP runtime
supports BigInt at all.

### Still not built

Phase 0 probes 4-6 (sequence insertion, undo/failure, 50 repeats) and the
subsequence-extraction question. Until Phase 0 reports, no backend is chosen and
`assemblyHost.js` / `assemblySession.js` do not exist.

## Development


```powershell
.venv\Scripts\python.exe -m cutdeck.xml_bridge
.venv\Scripts\python.exe -m pytest tests/test_cutdeck_premiere.py tests/test_cutdeck_xml_recut_cli.py tests/test_cutdeck_xml_recut.py -q
node --test tests/cutdeck_assembly.test.cjs tests/cutdeck_workflow.test.cjs tests/cutdeck_rpc.test.cjs
```

`workflow.js` contains the Premiere operations; `core/rpc.js` (mirrored from `panel/core/`, shared with the CEP panel) owns the helper socket and
its retry rule; `main.js` handles panel state. `cutdeck/xml_bridge.py` launches the
existing CLI in a subprocess.
The helper on port 7891 is the one server to start (`Start CutDeck.cmd`). The split probe
remains separate from this XML integration. (`bridge.py`, `live_clip.py` and `mark_export.py`
— the retired mark-and-apply `plan` path — were removed under issue #25.)

New CLI options: `--range-start-frame`, `--range-end-frame` (half-open interval),
`--report`, and `--no-save-plan`. The helper uses all four. Existing unscoped
command invocations keep their behavior.

API references checked during implementation:

- [Project XML export](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/projectconverter)
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

### Quick-effect preset buttons (Adj & FX page)

Below the Adjustment Layer card, up to `MAX_QUICK_PRESETS` (currently 9, in
`panel/core/panel.js`) captured presets each get their own button, laid out as a 3x3 grid of
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
(`#fx-preset-manage-list`, `panel/core/panel.js`'s `renderPresetManageList`/
`bindPresetManage`): edit the text field (renames on blur/Enter) or click × (removes it and its
quick-effect button immediately — no confirmation, same as every other destructive action in
this panel). Rename/remove are plain `localStorage` writes, not Premiere calls, so they're
wired directly through `main.js`'s `onRenamePreset`/`onRemovePreset` intents rather than
`act()`.

**Where presets are saved** (Settings > Presets > **Choose folder…**, `presetStore.js`): pick a
folder and presets live in `cutdeck-presets.json` there. Pick a synced folder (OneDrive,
Dropbox) and choose the same folder on each machine to share one preset list; linking a
folder that already has presets merges them with this machine's. With no folder chosen,
presets stay in this plugin install's `localStorage` only, which a reinstall or a switch
between source-load and the packaged `.ccx` does not carry over. Every edit re-reads the file
before writing, so one machine never erases another machine's newer presets, and a
`cutdeck-presets.json` that isn't valid is reported and left untouched, never overwritten.

**v1 is static-value effects only — no keyframes/animation**: a captured Keyframe's
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
