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

## Development

```powershell
.venv\Scripts\python.exe -m cutdeck.xml_bridge
.venv\Scripts\python.exe -m pytest tests/test_cutdeck_premiere.py tests/test_cutdeck_xml_recut_cli.py tests/test_cutdeck_xml_recut.py -q
node --test tests/cutdeck_workflow.test.cjs
```

`workflow.js` contains the Premiere operations; `main.js` handles panel state and
the socket. `cutdeck/xml_bridge.py` launches the existing CLI in a subprocess.
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
