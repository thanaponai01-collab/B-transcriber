# Handoff: move more of Rough Cut / Sync / XML export's work into the helper

**Written 2026-09-23** on branch `feat/cutdeck-transform-align` (the latest commit at the time
was `f1183ef`). Scope is the **Cut & Sync** tab of the UXP panel and the XML export → recut
pipeline only. The Adj & FX tab has its own handoff (`docs/HANDOFF_CUTDECK_AL_FX_NEXT.md`).
Read `CLAUDE.md`, `uxp/cutdeck/README.md` and `docs/HANDOFF_CUTDECK_XML_RECUT.md` first.

## The principle

UXP gives the panel only a narrow window into Premiere, and nothing else: no processes, no
FFmpeg, no GPU. The Python helper (`ws://127.0.0.1:7891`, `cutdeck/xml_bridge.py`) has the
venv, FFmpeg/ffprobe, the ASR models and the SQLite store. So the split should be:

> **The panel reads Premiere and makes the few Premiere calls only it can make. The helper
> does all the thinking, checking and heavy lifting. After anything the panel does to
> Premiere, it reads back to confirm.**

The panel's only jobs are to read the marks and timebase, run `exportAsFinalCutProXML`, and do
`importFiles` / `openSequence`. That part is already right. The gains are in what the helper
does, when it does it, and what it tells the panel.

## How it works today (traced from the code)

- **Panel** (`uxp/cutdeck/workflow.js`, `main.js` `doCut` / `doSync` / `follow`):
  1. `capture` reads the In/Out ticks, the sequence end, the timebase and the audio track
     *count*.
  2. It sends `prepare` to the helper.
  3. `exportAsFinalCutProXML` writes the whole sequence to the helper's `source_path`.
  4. It sends `start`, polls `status` every 1.5 s, then `importResult` imports the result into the
     `CutDeck` bin with an identity check.
- **Helper** (`cutdeck/xml_bridge.py` `XmlJobs`) resolves the reference audio track
  (`reference_audio_track`), converts ticks to frames (`range_from_ticks`), and picks the output
  path beside the footage (`result_path`). It then runs `python -m cutdeck.xml_recut` as a
  subprocess (`_run`). Multi-cam Sync is native since 2026-09-23 (`plan_sync`, see
  HANDOFF_CUTDECK_NATIVE_SYNC.md). Jobs run one at a time
  because of the GPU.
- **`cutdeck/xml_recut.py`** extracts a mixdown from the XML (`xml_audio_extract.py`), then
  runs VAD, optional ASR, rules and a surgical XML rewrite.

## Candidate work, highest value first

### 1. Stop re-transcribing the same footage (traced; biggest time win)
`xml_recut.py` at about lines 700–714: when the mixdown is its own temp file, it **purges** the
job's transcript data after reading the words ("Our own temp mixdown is deleted below and can
never be resumed"). The README also notes that the **whole sequence's audio** is analyzed even
for a short In/Out. Together these mean that every re-run on the same sequence (a new In/Out, a
changed preset, Speech+Silence after Silence Only) redoes full ASR.
- The idea is to cache by the *content* of the extracted audio: a sha256 of the mixdown, or of
  (source media paths, source in/out, track) before extraction. Keep the transcript instead of
  purging it, and reuse it on a hit. `transcribe/db/store.py` already has media sha256 and
  resumable jobs (see `CLAUDE.md` "job_phase"). Find out why the XML path opted out before
  changing it.
- Stretch goal: extract only the In/Out range plus a padding margin, when the rules don't need
  whole-sequence context. **Check this with the user.** The README says keeping the full
  analysis context was deliberate.

### 2. Check the job before the expensive part (issue #28)
Issue #28 (open) asks that bad input be refused *before* ASR, with one owner for sequence
timing, reference-track selection and source-reference resolution. The two known gaps:
reference-track selection doesn't check whether the track is enabled, and negative or
out-of-range indexes are accepted. The helper should run this check at `prepare`/`start` and
return a clear refusal the panel can show straight away. Media checks belong here too, using
ffprobe (already used in `xml_export.py`):
- source file missing or offline
- variable frame rate (`xml_export.py` already refuses VFR in the other direction, GAP-2)
- a source frame rate that differs from the sequence
- no audio stream

Keep the surgical XML rewriting exactly as it is. The issue says so explicitly.

### 3. Give the panel real track information, not just a count
Today the Reference Audio dropdown shows only `audio_track_count` (`capture`). The helper can
list each track from the XML: its name, whether it's enabled, whether it has clips, and which
one it would pick by default. Then the dropdown can say *what* will be analyzed. The open
question is **when**: it needs an XML export, which today only happens at job start. The options
are a cheap on-demand "Inspect" (export to a temp file, have the helper parse it and reply), or
showing the information in the status line once the job starts. Ask the user; an extra export on
every refresh is probably too slow for long sequences, and that needs measuring.

### 4. Better progress and failure messages (small)
`follow` shows `progressText(job)`, and failures show `job.message`. The helper could report the
phase it's in (extracting / VAD / ASR / rules / writing), an estimated time left based on media
duration and the measured speed of past runs (`eval_run.rtf` exists for the eval harness), and on
failure the last meaningful line of `process.log` instead of a generic message.

## Rules for the new session
- **Probe or measure before building.** For #1, time a repeat run first so the win is proven,
  not assumed. Premiere-side behavior must be checked by the user in the live app. Use the
  panel's diagnostics-drawer probe pattern (`capabilityProbe.js`) for anything new on the
  Premiere side.
- **Keep the job protocol backward-compatible, or bump `VERSION`** (`cutdeck-xml-1` in
  `workflow.js`, checked by `hello`). The panel and helper ship from the same repo but can be
  running different versions during a session.
- **"Resume last job" must keep working:** `prepare` mints a new job, so no blind resend
  (`core/rpc.js` header).
- **Tests:**
  - Python: `.venv\Scripts\python.exe -m pytest tests/test_cutdeck_premiere.py tests/test_cutdeck_xml_recut_cli.py tests/test_cutdeck_xml_recut.py -q`
  - JS: `node --test tests/*.cjs` (includes a `node --check` pass over every plugin file).
    Premiere runtime errors are in `%APPDATA%\Adobe\Premiere Pro\Logs\UXPLogs_*.log`.
- The user runs several machines. The 8 GB VRAM ceiling is a deliberate design floor, and
  engines still load strictly one at a time.

## Questions to ask the user first
1. How often do you re-run Rough Cut on the same sequence? That decides whether #1 comes first.
2. Should a short In/Out still analyze the whole sequence's audio (the current deliberate
   choice), or only the range plus padding?
3. For track information (#3): on-demand Inspect, or only once the job starts?
