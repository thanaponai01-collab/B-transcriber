# CutDeck for Premiere — XML workflow

Mark **In / Out** on the timeline, click **Rough Cut In–Out**, and continue in
a newly imported sequence. CutDeck automatically exports and imports XML using
the same processing command as `scripts/cut_xml.ps1`. No MCP is involved.

## First-time setup

1. Use Premiere **26.2 or later** (this machine currently has 26.5).
2. Double-click **Start CutDeck.cmd** in the project folder. Keep that helper
   window open while using CutDeck. It uses this project's existing `.venv`,
   models, configuration, and FFmpeg installation.
3. Enable **Developer Mode** in Premiere's Plugins preferences and UXP Developer
   Tool (version 2.2 or later). In **UXP Developer Tool**, choose **Add Plugin**, select
   `uxp/cutdeck/manifest.json`, and click **Load** with Premiere running.
4. Open the **CutDeck** panel from Premiere's **Window > UXP Plugins** menu.
   Accept Premiere's plugin permissions if prompted.

This is a source-loaded development build. It has not yet been packaged or
validated as a distributable `.ccx` installer.

## Use

1. Open your source sequence. Set timeline In and Out marks.
2. Click **Read timeline range** to see the sequence and range in the panel.
3. Leave **Dialogue audio** on its default to match the working XML command,
   or select a specific Premiere audio track.
4. Leave the usual preset selected for aggressive silence cutting with ASR
   protection for short speech. **Faster · silence only** skips ASR, just like
   the existing command's `-NoAsr` switch.
5. Click **Rough Cut In–Out**. CutDeck creates a sequence named
   `Your sequence — CutDeck <job identifier>` and opens it.

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

- **Connection lost / panel reloaded:** start the helper if needed and click
  **Resume last job**. While the same helper remains running, processing continues
  even if the panel disconnects.
- **"Permission denied to the url ws://127.0.0.1:7891":** UXP registers the plugin's
  network permission later than the panel's first request, so a cold start can be
  denied even though the manifest declares the domain. The panel now retries the
  connection five times over about three seconds, which also covers a helper that is
  still starting up. If it still fails, the helper is genuinely not running.
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
no helper. See `docs/HANDOFF_CUTDECK_TIMELINE_IN_OUT.md`. **Nothing in this panel
mutates a timeline** — everything that does lives in `uxp/spike_assemble_probe/`,
loaded separately against a disposable project. What exists here today:

- `timelineRange.js` — normalizes Premiere's marks into an exact half-open
  `[in, outExclusive)` interval in BigInt ticks.
- `assemblyPlan.js` — pure intersection and placement math (handoff section 6).
- `capabilityProbe.js` — Phase 0 probe 1, behind the **Check Premiere timing
  (read-only)** button.

### Run the timing probe (one of two gestures waiting on a human)

The other is the assemble probe below. They are independent: this one is read-only
and settles the Out-point convention on a real project; that one mutates a
disposable project and settles whether issue #25's route exists at all. Neither
blocks the other, so run them in whichever order is convenient.

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

### The mutation probe lives elsewhere — `uxp/spike_assemble_probe/`

Everything that **mutates a project** is deliberately not in this panel. Issue #25's
three-point-edit route (create a matching sequence, place every span, disable the CUT
ones, ripple the disabled ones out on Apply) depends on five API calls, **none of
which has executed once in this project**. A separate throwaway plugin answers three
of those unknowns in one click at N=3 spans instead of 443:

1. does `createSetSettingsAction` carry a 29.97/59.94 timebase across, or fabricate 25?
2. do three interleaved `setInOut`/`overwrite` pairs survive **one** transaction?
3. does `createRemoveItemsAction(sel, ripple=true, ANY)` work at all?

See `uxp/spike_assemble_probe/README.md` for how to run it and what each verdict
means. It needs a **disposable project** and no helper. Until it has run, no backend
is chosen and `assemblyHost.js` / `assemblySession.js` do not exist.

### Still not built

Phase 0 probes 4-6 (sequence insertion, undo/failure, 50 repeats) and the
subsequence-extraction question. Those are separate gestures; do not fold them into
the assemble probe's one click.

## Development


```powershell
.venv\Scripts\python.exe -m cutdeck.xml_bridge
.venv\Scripts\python.exe -m pytest tests/test_cutdeck_premiere.py tests/test_cutdeck_xml_recut_cli.py tests/test_cutdeck_xml_recut.py -q
node --test tests/cutdeck_assemble_probe.test.cjs tests/cutdeck_assembly.test.cjs tests/cutdeck_workflow.test.cjs tests/cutdeck_rpc.test.cjs
```

`workflow.js` contains the Premiere operations; `rpc.js` owns the helper socket and
its retry rule; `main.js` handles panel state. `cutdeck/xml_bridge.py` launches the
existing CLI in a subprocess.
The original `cutdeck/bridge.py` and split probe remain separate from this XML
integration.

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
