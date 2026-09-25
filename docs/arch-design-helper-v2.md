# Architecture & Design: CutDeck helper v2 (the hub)

Date: 2026-09-24. Scope: `cutdeck/xml_bridge.py` (the helper on `ws://127.0.0.1:7891`),
`cutdeck/ai_backend.py` + `cutdeck/mcp_server.py` (MCP), and the panel's side of the socket
(`uxp/cutdeck/core/rpc.js`, `workflow.js`, `features/roughCut.js`, `timeline/nativeSync.js`,
`transform/frameBounds.js`).

## Verdict

Today the helper is a batch-job runner that only the panel can use for Premiere work. The
panel pulls results from it, and nothing else can touch Premiere. v2 makes the helper the
**hub** and the panel the **Premiere driver**:

```
 MCP agent ─┐                       ┌─ GPU lane: one job at a time (rough cut, transcribe)
 Python/CLI ┼──►  helper (hub)  ────┼─ CPU lane: one job at a time (sync matching), beside the GPU lane
 panel UI  ─┘    ids · events ·     └─ job.json on disk: survives a helper restart
                 job store
                     │  commands sent back to the panel over its open connection
                     ▼
              UXP panel = the Premiere driver (fixed command list, never arbitrary JS)
```

**ExtendScript is not part of this.** `docs/PREMIERE_FACTS.md` records it as retired:
Premiere 26.3 silently ignores QE razor/ripple on some installs, and support ends in
September 2026. The "external script" ability comes from the driver instead (move 3): any
local script sends a fixed command to the helper, and the panel runs it with the UXP calls
already proven live.

## Status (2026-09-24)

| Move | State | Check that passed |
|---|---|---|
| 1 Protocol v2 | **built** | `tests/test_cutdeck_helper_v2.py` (ids out of order, 1 MB request, watch), `tests/cutdeck_rpc.test.cjs` (20), `tests/test_cutdeck_panel_wire.py` (real `rpc.js` against the real helper) |
| 2 Lanes | **built** | `test_sync_holds_the_cpu_lane_not_the_gpu_lane`, `test_replies_carry_the_request_id_and_do_not_wait_for_slower_ones` |
| 3 Premiere driver | **built, live-proven 2026-09-24** (panel registered; `read_sequence`, `add_markers` with comment) | helper + MCP + CLI: `test_cutdeck_helper_v2.py`; panel: `tests/cutdeck_driver.test.cjs`; wire: `test_cutdeck_panel_wire.py` |
| 4 Durable jobs | **built** | `test_a_job_running_when_the_helper_stopped_reads_as_interrupted`, `test_mcp_reports_an_interrupted_job`, rough-cut feature test |
| 5 Warm GPU worker | **measured, not built** | 3.2 s imports + 1.5 s model load, 2026-09-24 |
| 6 JSON input | **built, live-proven 2026-09-24** (job e8b96443: 33:50 sequence, 420 cuts, read-back clean; no earlier XML-route job on it to compare counts) | `tests/test_cutdeck_sequence_json.py` (golden against the real export, real ffmpeg mixdown), `cutdeck_workflow.test.cjs` |
| 7 C++ add-on | **not now** | — |

Changed while building, and why:
- A job that was **prepared** (not running) when the helper stopped stays `prepared`. Its
  `source.xml` is on disk and `start` reads it from there, so it can still run. Only `running`
  becomes `interrupted`.
- `prepare` now checks everything before it claims a job folder. Before, a refused prepare
  left an empty folder behind.
- The panel's driver connection is its own quiet `createRpc` (1 connect attempt, no status
  messages), so reconnecting doesn't flash "Connecting to helper…" in the panel.

## What was wrong (read, 2026-09-24)

| # | Finding | How we know |
|---|---|---|
| F1 | Replies have no id, so `rpc.js` sends one call at a time. Rough Cut and Sync poll `status` every 1.5 s. Messages are capped at 64 KB (≈200 clips). | traced: `rpc.js` queue, `roughCut.js pollDelay`, `nativeSync.js POLL_MS`, `serve(max_size=65536)` |
| F2 | A single `active` slot covers every job, so Sync's matching (CPU only) blocks, and is blocked by, a rough cut. | traced: `XmlJobs._allocate` |
| F3 | `frame_bounds` compares PNGs directly on the helper's only request loop, so every client waits while it runs. | traced: `dispatch` calls `frame_bounds.measure_request` synchronously |
| F4 | Jobs live only in memory. After a restart `status` answers "Unknown job", although each job's `job.json` is on disk. MCP lists an `interrupted` state that nothing produces. | traced: `XmlJobs.jobs`, `ai_backend.MCP_STATE` comment |
| F5 | Nothing outside the panel can edit Premiere: MCP publishes `live_premiere_control: False`. | traced: `ai_backend.capabilities` |
| F6 | Rough Cut exports the whole sequence as FCP7 XML only so the helper can read the reference track's media paths and positions back out of it. Sync already reads clips natively and sends JSON. | traced: `workflow.prepare`, `xml_audio_extract.extract_mixdown` |
| F7 | Each rough cut starts a fresh Python child. | traced: `XmlJobs._run` |

## Decisions

- **One socket, one protocol, both directions.** Requests carry an `id`, replies echo it, and
  requests on a connection are handled concurrently. The helper pushes job updates to
  connections that asked to `watch` a job. Server `max_size` goes to 16 MiB (the MCP client
  already allows that).
- **No request-level idempotency keys.** I proposed them to make `prepare` safe to resend.
  Resume already recovers a lost reply, and nothing would resend, so the key would be dead
  code.
- **Lanes, not a process pool.** One GPU lane (rough cut, transcribe) and one CPU lane (sync
  matching). `frame_bounds` runs on a worker thread (`asyncio.to_thread`). A process pool
  would add pickling and lifecycle code for work that already releases the GIL in numpy.
- **The driver runs a fixed command list.** `read_sequence`, `apply_cuts`, `add_markers`,
  each built on code or calls recorded as working live. No `eval`. The panel refuses a
  command while it is already busy instead of queueing behind the user.
- **Keep the GPU worker cold (move 5 measured, not built).** Measured on this machine
  (2026-09-24): importing torch + faster-whisper takes **3.2 s** and loading
  `whisper-th-medium-ct2` on the GPU **1.5 s** (1.25 s with a warm disk cache). That's
  about 5 s against rough cuts that transcribe at ~3.5× realtime (minutes per job). A worker
  kept warm would also hold ~1.5 GB of VRAM between jobs, against the one-model-at-a-time
  rule. The cost is ~1–3 % of a job, so it isn't worth it.
- **Rough Cut input as JSON; the helper writes the minimal XML itself.** The panel reads
  the audio tracks natively (media path, start, In/Out ticks, clip disabled, track muted)
  and sends them in `prepare`. The helper turns that into the small FCP7 subset that
  `check_reference_audio` / `extract_mixdown` / `xml_recut` already read, so the analysis
  code is unchanged. Channel mapping doesn't matter: the extractor mixes every channel of
  each file to mono (`ffmpeg -ac 1`), which is what the XML route did too. Transitions and
  nested sequences are still refused where a cut lands (`planCutApply` in the native apply).
- **No native C++ add-on (hybrid plugin) now.** Adobe's docs support it from Premiere 26.2,
  the panel's `minVersion`. It would replace the `.vbs` + `shell.openPath` launch. But it
  needs the Hybrid SDK from the Adobe Developer Console (an Adobe login), a C++ toolchain,
  and code signing for distribution. There's no current evidence that launching the helper
  is failing. Revisit if helper start becomes a recurring support problem.

## Moves

Each move names its check. All checks run without Premiere (fakes + real sockets). Moves 3
and 6 also need one live Premiere run, listed under **Live acceptance**.

### 1. Protocol v2: ids, concurrency, pushed job events

- Helper (`serve`): each incoming message is dispatched as its own task. A reply carries
  the request's `id` when it had one. `{"type":"watch","job_id"}` replies with the job now
  and then pushes `{"event":"job","job":…}` on that connection each time its progress or
  state changes, until it ends. `max_size` is 16 MiB.
- Panel (`rpc.js`): one persistent socket. Calls are matched to replies by `id`, with no
  queue. `rpc.watch(jobId, onUpdate)` resolves with the finished job. The existing
  retry-before-send and never-resend rules stay.
- `roughCut.js` and `nativeSync.js` wait on `watch` instead of polling every 1.5 s.
- `VERSION` becomes `cutdeck-xml-5` on both sides.
- **Check:** tests that (a) two calls on one socket get their own replies out of order,
  (b) `watch` receives progress then the terminal state, (c) a 1 MB request is accepted,
  (d) the panel's follow loop makes no `status` calls.

### 2. Two lanes, and `frame_bounds` off the loop

- `XmlJobs.active` stays the GPU lane (rough cut, transcribe). New `cpu_active` is the CPU
  lane (`plan_sync`). `restart` is refused while either lane is busy.
- `frame_bounds` runs through `asyncio.to_thread`.
- **Check:** a sync starts while a rough cut runs; a second sync is refused; a `status`
  request is answered while `frame_bounds` is still measuring.

### 3. The panel as the Premiere driver

- Panel → helper: `{"type":"register_driver","commands":[…]}` on its persistent socket,
  sent again on every reconnect. The panel reconnects by itself (5 s, backing off to 30 s),
  so a restarted helper finds it again.
- Any client → helper: `{"type":"premiere","command":…, "args":…}`. The helper forwards
  `{"call":<id>,"command","args"}` to the driver, waits for
  `{"type":"driver_reply","call":<id>,…}`, and returns that reply. Without a panel connected
  it fails with a clear message. If the driver disconnects, pending calls fail.
- Commands (`uxp/cutdeck/features/driver.js`):
  - `read_sequence`: the active sequence's identity, In/Out, timebase and track counts
    (`workflow.capture`).
  - `apply_cuts {job_id}`: the helper looks up the finished rough-cut job and sends its cut
    list; the panel applies it to a **copy** with `applyNativeCut`, the route Rough Cut
    already uses. For a panel job the active sequence must be the one analysed. For an MCP
    job its length must match the cut list's `sequence_duration_frames`.
  - `add_markers {markers:[{start_s, duration_s, name, comment}]}`: one transaction of
    `Markers.createAddMarkerAction` on the active sequence (432 in one transaction recorded
    as working, ledger 09-24).
- MCP gains `premiere_status`, `premiere_read_sequence`, `premiere_apply_cuts`,
  `premiere_add_markers`. `live_premiere_control` becomes true, noting that it needs the
  panel open.
- Scripts: `python -m cutdeck.premiere_cli status | read_sequence | apply_cuts <job_id> |
  add_markers <file.json>`, or `cutdeck.ai_backend.Backend().premiere(command, args)` from
  Python.
- **Check:** real-socket tests (helper + fake driver client + MCP backend): a command
  round-trips, no driver gives a clear error, a driver disconnect fails the pending call,
  `apply_cuts` refuses unknown or unfinished jobs. Panel tests with the Premiere fake:
  `add_markers` makes one transaction, `apply_cuts` refuses a mismatched sequence, and a
  busy panel refuses.
- **Risk:** any local process can send these commands. The origin check still blocks web
  pages. The commands are fixed, `apply_cuts` edits only a new copy, and markers are one
  Ctrl+Z.

### 4. Jobs survive a helper restart

- `status` (and `watch`, `start`) for an id that isn't in memory reads
  `<jobs>/<id>/job.json`. A job that was `running` there belonged to a helper that stopped,
  so it becomes `interrupted` (saved, with a message). A `prepared` job stays startable. MCP maps `interrupted` → `interrupted`. The panel
  shows the message and clears the job, as it does for `failed`.
- **Check:** a test writes a running `job.json`, builds a fresh `XmlJobs`, and gets
  `interrupted`; the MCP view says `interrupted`.

### 5. Keep the GPU worker loaded: **measured, not built** (see Decisions).

### 6. Rough Cut input as JSON

- Panel: `workflow.prepare` reads every audio track (`AudioTrack.isMuted`, and per clip
  `getStartTime/getInPoint/getOutPoint`, `isDisabled`, `getMediaFilePath`) and sends
  `sequence: {ticks_per_frame, end_ticks, audio_tracks:[{enabled, clips:[…]}]}` in
  `prepare`. `exportAsFinalCutProXML` is no longer called.
- Helper: `cutdeck/sequence_json.py` validates the JSON and writes `source.xml` in the
  FCP7 subset the pipeline reads. `prepare` does this, and `start` runs unchanged.
- **Check:** a golden test builds the XML from JSON and gets the same
  `check_reference_audio`, `audio_track_groups` and `extract_mixdown` inputs as the scrubbed
  real export for the same clips; bad JSON is refused before any job folder is made; the
  panel test sends the JSON and never calls the XML export.

### 7. Native C++ add-on: **not now** (see Decisions).

## Live acceptance (needs Premiere, not runnable from tests)

1. Load the panel; the helper log shows `driver registered`.
2. From a terminal: `python -m cutdeck.premiere_cli read_sequence`. Expect the active
   sequence's name.
3. Rough Cut in Protected mode on a real sequence: the result matches the previous XML route
   (same cut count on the same In/Out).
4. `python -m cutdeck.premiere_cli add_markers` with one test marker: it appears, and one
   Ctrl+Z removes it.

Add each outcome as a row in `docs/PREMIERE_FACTS.md`. The rows waiting on this run are
marked UNPROBED there: `AudioTrack.isMuted`, `AudioClipTrackItem.isDisabled`, and the
`comments` argument of `Markers.createAddMarkerAction`.

The panel must be reloaded (UXP Developer Tool, or reinstall the `.ccx`) to pick up
`cutdeck-xml-5`. On its next start it restarts an older helper by itself.
