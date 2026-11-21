# Native cutter spike

Experimental Windows Control Surface plugin for investigating a native Rough Cut
backend. It lists Premiere's commands, and runs one fixed command, Add Edit to All
Tracks (`global` / `cmd.sequence.razorateditline.all`), once per request file in
`%TEMP%\CutDeckCutterSpike`. A request is refused unless Premiere's displayed SMPTE
timecode equals the expected one, playback is stopped, and the request is fresh. The
plugin deletes the request before running it.

The Python request side (`cutdeck/native_split.py`) and the panel's "Test Native Add
Edit" probes were removed on 2026-11-21. The menu route (`premiere_menu_command`
"Sequence > Add Edit to All Tracks") does the same cut live, so this plugin is the last
resort, kept for a command that is in neither the menu nor the shortcut file
(docs/PREMIERE_CONTROL_MAP.md). Git history before that date has the request code.

## Build and native boundary checks

Prerequisites: the owner-supplied `files/Premiere Pro 26.0 C++ SDK`, Visual Studio
2022 C++ Build Tools (v143), and Windows SDK 10.0.26100. SDK files remain local.

From the repository root:

```powershell
pwsh -File tools/native-cutter-spike/verify.ps1
```

This compiles the `.acsrf` plugin and a test host, loads the actual plugin through
Windows, exercises full/partial/empty command catalogs and failed SDK acquisition,
and checks that suites/strings are released. Request scenarios check that only a
fresh, well-formed request with the matching timecode runs, exactly once and only
the fixed command; no-request, mismatch, stale, pre-connect, playing, wrong display
mode, missing transport, extra lines, wrong nonce and an undeletable request run
nothing. The harness points TMP at `output/native-cutter-spike/harness-temp`, so its
requests never reach a running Premiere. The host
is synthetic: passing these checks does not establish real Premiere behavior.
Proof is retained under `output/native-cutter-spike/`.

## Real Premiere gate

The SDK sample uses `C:\Program Files\Adobe\Common\Plug-ins\ControlSurface` for
Windows native control-surface plugins. The built file is
`output/native-cutter-spike/CutDeckCutterProbe.acsrf`. Installing it requires
administrator access. Never overwrite another existing plugin.

Save and restart Premiere after installing, then choose **Edit > Preferences >
Control Surface > Add > CutDeck Cutter Probe (read only)**. With a project open,
the plugin writes a uniquely named `commands-<pid>-<time>-<counter>.json` under
`%TEMP%\CutDeckCutterSpike`. Require `complete: true`, zero errors, matching row
counts, and the current Premiere process ID. Preserve exact command/context IDs.

Only the one Add Edit command can run, and only on a request. Whether it acts on the
active sequence at the playhead, on exact frames, as one undo step and with links kept
is what the live disposable-sequence test must establish.
To remove it, remove its Control Surface entry, close Premiere, then remove only
the installed `CutDeckCutterProbe.acsrf` whose hash matches the installation receipt.

## SDK sources used

- `Examples/Headers/adobesdk/controlsurface/plugin/ControlSurfacePluginSuite.h`
- `Examples/Headers/adobesdk/controlsurface/plugin/ControlSurfaceSuite.h`
- `Examples/Headers/adobesdk/controlsurface/host/ControlSurfaceHostCommandSuite.h`
- `Examples/Headers/adobesdk/controlsurface/host/ControlSurfaceHostSuite.h`
- `Examples/Headers/adobesdk/AdobesdkStringSuite.h`, `SPBasic.h`, `SPSuites.h`
- `Examples/Projects/ControlSurface/ControlSurface.vcxproj` for build settings

Only declarations are reused through includes; proprietary SDK files and binary
outputs must not be committed.
