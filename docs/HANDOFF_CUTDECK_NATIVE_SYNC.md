# Handoff: native Sync, step 2 — wire the planner to a real button

**Written 2026-09-24** on branch `feat/cutdeck-transform-align`, at `8ce102d`. Scope: the
**Sync Multi-Cam** button of the UXP panel's Cut & Sync tab. Read `CLAUDE.md` (rule 2: the UXP
API gate), `uxp/cutdeck/README.md`, and this file. Rough Cut is out of scope and keeps its XML
route.

## Status (2026-09-23): A and B built, waiting on the live run

- **A, done:** `plan_sync` job in `cutdeck/xml_bridge.py` (`VERSION` is now `cutdeck-xml-2`);
  `plan_sync(..., progress=)` plus `SyncPlan.media_duration_s` (each file's audio length, which
  the read-back uses as "the file's length"). Tests: `tests/test_cutdeck_plan_sync_bridge.py`.
  The 200-clip socket test with ~200-char paths is ~54 KB of the 64 KB limit, so **300 clips only
  fit with shorter paths**.
- **B, done:** `uxp/cutdeck/timeline/nativeSync.js`, wired to the Sync button in `main.js`;
  `readSequence`/`groupUnits` moved there from `syncProbe.js`. The Audio Track picker now sits
  under Rough Cut. Tests: `tests/cutdeck_native_sync.test.cjs`.
- **No separate probe was built.** Sync only ever edits the `_Synced` copy, and its read-back
  names each of the four unknowns below if it goes wrong ("did not land", "N ticks off",
  "other item(s) on the copy", audio count). The first live run is the probe. No fallbacks
  (one transaction per clip, place-then-move) are written: add one only if the read-back
  shows it's needed.
- `workflow.prepareSync` and `follow`'s sync branch are unused by the button now; part C
  removes them.
- **Live 2026-09-23:** the first run failed with "The script object is no longer valid": a
  `createEmptySelection` selection is only valid inside its callback (Adobe's
  eslint-plugin-premierepro rule `no-empty-selection-escape`). Fixed by building the selection and
  the remove action inside that callback, within the transaction. The re-run worked (user report).
  Still to confirm before part C: the result matches the user's manual sync on a real shoot, and
  one Ctrl+Z undoes it. **Confirmed by the user the same day**: placement, links, one Ctrl+Z.
- **Live 2026-09-23, Renfest shoot:** an unrelated clip (HOST SEGMENTS) was "synced" on top of the
  interviews: coarse PSR 9-12 is chance level against a 37-min session, one piece passed, and the
  planner fell back to the coarse start when the fine match refused it. Fixed: the fine match
  must confirm (stepping up to `FINE_TRIES` windows across the overlap), or the clip is unmatched.
- **User requests, same day:** clips that can't sync lie flat on the first V/A tracks after a
  `UNPLACED_GAP_S` (30 s) gap, spaced by their whole file; and every panel start restarts the
  helper (`restart` request: the helper spawns its own replacement; refused mid-job, skipped
  while a job waits to be resumed).

## Why this exists

Today's Sync exports the sequence as FCP7 XML, re-stacks it in the helper (`cutdeck/xml_sync.py`)
and imports a new sequence. The user wants off XML: the round trip **merges or duplicates their
audio tracks**, and it matched every clip against one reference clip only. The replacement does
the matching in the helper and the placing natively in Premiere.

## Decisions already made with the user (do not re-open)

- **One button, no options.** Sync no longer reads the Reference Audio dropdown; that stays for
  Rough Cut. Say so in the UI.
- **The user's workflow:** they drag cam1's clips, then cam2's, cam3's, then the recorder audio,
  flat in a row, onto one sequence. Sync is the **first** step of the edit: no titles, graphics
  or nests to worry about. Skip anything without a media file and name it in the report.
- **Layout: one track pair per clip.** Clip k goes to its own V_k + A_k (audio-only clips get
  an A track only). 100+ tracks is fine. "Simplify / flatten" is a later, separate feature.
- **Full clips only.** Sync places the whole file. A clip trimmed on the timeline comes back
  full length. No trim handling.
- **Clips that cannot sync go to the back**, after the synced ones, each with its reason.
- **Work on a copy** named `<name>_Synced`; the original is never edited. **Refuse** to run on a
  sequence whose name already ends in `_Synced`.
- **One Ctrl+Z** should undo the placing.
- Source Monitor In/Out marks: keep placing from the file as the probe did; read-back flags any
  clip that lands shorter than its file ("check its In/Out marks").

## What is proven

**Live, in Premiere 26.5** (the "Test Sync Moves" probe, `uxp/cutdeck/syncProbe.js`, `73138b2`):

| Call (declared in `@adobe/premierepro` 26.2.1 `premierepro.d.ts`) | Result |
|---|---|
| `ClipProjectItem.cast(item.getProjectItem()).getMediaFilePath()` | works for every clip |
| `Sequence.createCloneAction()` in a transaction | copies the sequence; find it by new guid |
| `ProjectItem.createSetNameAction` on the copy's project item | renames it |
| `SequenceEditor.createOverwriteItemAction(projectItem, time, newV, newA)` | **the placement route.** Video + audio land together, **linked** (the user checked), full length, and a track index equal to the track count **creates** the track |
| `createCloneTrackItemAction` | copies **video only**: do not use it to move clips |
| `AudioClipTrackItem.createMoveAction(half a frame)` | audio **can** start between frames |
| 100 clones in one `executeTransaction` | near-instant; **one Ctrl+Z undid all 100** |

**Off-host** (`8ce102d`): `cutdeck/sync_plan.py` `plan_sync(clips, loader) -> SyncPlan`. It places
clips through overlaps (sessions grow as clips join), in 60 s coarse chunks at 2 kHz plus fine
16 kHz windows. It refuses ambiguous repeated sound, reports drift, and lays out sessions in
timeline order with unplaced clips at the back. `tests/test_cutdeck_sync_plan.py` has one test
per shooting scenario, and each safeguard has a test that fails when it is removed. The same
commit fixed the GCC-PHAT lag bug in `cutdeck/sync.py` (late clips read as negative offsets).

## Step 2: what to build

### A. Helper: a `plan_sync` job (`cutdeck/xml_bridge.py`)

- New request `{type: "plan_sync", clips: [{id, path, duration_s}]}`. Validate each path
  (the existing `_input_file` helper). Claim the single job slot with `_allocate()`: matching is
  CPU-heavy and must not overlap a Rough Cut. Return the job; the panel polls `status` as it
  does today (`follow` in `main.js`).
- Run `plan_sync` in `asyncio.to_thread`. The loader is a thin adapter over
  `cutdeck.sync.extract_mono_audio(path, start_s=, duration_s=, sample_rate=)`. Its argument
  order differs from `sync_plan.Loader(path, rate, start_s, duration_s)`.
- Add an optional `progress(done, total, stage)` callback to `plan_sync` so `status` can report
  "Reading audio 12/40" and "Matching". Keep `plan_sync` pure otherwise.
- The result on the job is the plan as JSON: per clip `status, start_s, session, matched_to,
  confidence, drift_ms, reason`, plus `sessions` and `duration_s`.
- **Protocol:** a new panel that sends `plan_sync` to an old helper gets "Unknown request type".
  Bump `VERSION` (`cutdeck-xml-1` → `-2`) in **both** `cutdeck/xml_bridge.py` and
  `uxp/cutdeck/workflow.js`, so `hello` refuses the mismatch clearly.
- The websocket `max_size` is 65536 bytes. 300 clips with long Windows paths fit; add a test
  that sends a realistic 200-clip request.
- Not needed now: caching each file's coarse audio across runs. Add it only if a real run is
  slow.

### B. Panel: native Sync (`uxp/cutdeck/main.js` `doSync`, a new `timeline/nativeSync.js`)

Reuse `syncProbe.js`'s proven pieces: `readSequence`, `groupUnits`, and the copy-and-rename
steps. Move them into the new module rather than importing a probe.

1. **Check.** A sequence is open, and its name doesn't end in `_Synced`. Then run
   `ensureHelper()`.
2. **Read** every clip. Group linked items into clips with `groupUnits`: same file, same
   start, same source In. Audio items with no video are recorder clips. Items with no file
   path are skipped and listed.
3. **Plan.** Send `plan_sync` with one entry per clip, taking `duration_s` from the timeline,
   then poll until the job is ready.
4. **Copy, then clear and place in ONE transaction.** First clone the sequence, then find and
   rename the copy. The clone must be its own transaction, because its result has to be found
   before anything can be placed in it. Then, in a single second transaction:
   - remove every original item from the copy (`createRemoveItemsAction` with a
     `TrackItemSelection`);
   - for clip k, add `createOverwriteItemAction(projectItem, start, v_k, a_k)`. The start is
     `round(start_s × 254016000000)` ticks. **Video clips snap to a whole frame**;
     `getTimebase()` gives ticks per frame. Audio-only clips keep the exact tick.
   Track indexes: `v_k` counts video clips. `a_k` advances by each clip's audio-item count, so
   a stereo or multi-channel clip keeps all its tracks.
5. **Read back.** Re-fetch everything (references go stale across transactions, issue #18).
   Then check every clip:
   - its start is within 1 tick of the plan (or of the snapped frame);
   - its audio-item count matches the original;
   - its length equals the file's.
6. **Report** in the status line: "42 synced in 2 sessions. 3 at the back: C0014 no audio,
   C0021 matched nothing. C0030 drifts +45 ms, check the end." Open `_Synced`.

### Unknowns to settle in Premiere before relying on them (probe first, as `syncProbe.js` did)

- **Several overwrites in ONE transaction, each onto a track that doesn't exist yet.** Proven
  for clones (100, one transaction), not for overwrite. If later indexes don't create tracks,
  fall back to one transaction per clip; one Ctrl+Z per clip is worse, so tell the user.
- **Overwrite at a between-frames time for audio-only files.** The probe only proved
  `createMoveAction` by half a frame. If overwrite snaps, place at the frame, then move by the
  remainder.
- **Overwrite of an audio-only file** with a video track index. Check what it does, or pass -1
  as `adjustmentLayer.js` does for the unused side.
- **Removing every item from the copy** with `createRemoveItemsAction`: ripple off; check that
  links are respected and nothing is left behind.

### C. Retire XML Sync (only after one real shoot passes)

Remove `prepare_sync` / `_run_sync` from the helper, `cutdeck/xml_sync.py` and its tests, and
`prepareSync` from `workflow.js`. Keep `cutdeck/sync.py`: the planner uses it.

## Tests

- Python: `.venv\Scripts\python.exe -m pytest tests/test_cutdeck_sync_plan.py tests/test_cutdeck_sync_audio.py -q`,
  plus a new bridge test for `plan_sync` (validation, the job slot, the result shape, the
  version bump).
- JS: `node --test tests/*.cjs`. Test `nativeSync.js` against a fake host, the way
  `tests/cutdeck_sync_moves_probe.test.cjs` fakes Premiere: track-index assignment,
  frame snapping vs exact audio ticks, refuse on `_Synced`, and a read-back that catches a
  short or missing clip.
- **Live acceptance** (the user): one real multi-cam shoot. Cameras should start at different
  times, and include a recorder split into several files if possible. Compare with their
  manual sync, check the links hold, and press Ctrl+Z once.

## Rules

- **UXP API gate** (CLAUDE.md rule 2, enforced by a hook): prove every Adobe call against the
  26.2.1 typings before writing it. Enum values and runtime behavior need a live probe.
- The 8 GB VRAM ceiling is irrelevant here (no models), but the helper's one-job-at-a-time
  rule still applies.
- The user runs several machines. Sync must not assume one fixed PC.
