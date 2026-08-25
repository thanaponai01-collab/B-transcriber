# CutDeck spike #18 — split probe

**Throwaway.** Answers one question for issue #18: does clone+trim compose
into a clean split in UXP, and in what order? Not wired into `cutdeck/`,
`bridge.py`, or `mark_export.py` — those already exist for the real
mark-and-apply plugin (#19–#22) and depend on this spike's answer, not its
code. Delete this folder once #18 is closed, unless its answer says the
approach works and #22 wants to start from it.

## UPDATE (2026-08-25, round 2): clone throws "script object is no longer valid"

With the API-name fixes above in place, **Split A1 clip 1** got further: the
sequence in/out and the clip's own start/end/in/out all read correctly, and
`stageSplit()` began staging split "A" -- then `createCloneTrackItemAction`
threw:

```
FAILED: The script object is no longer valid.
Error: The script object is no longer valid.
    at ... e.SequenceEditor.createCloneTrackItemAction (...)
    at stageSplit (main.js:167:38)
```

The `headItem` reference handed to the clone call was fetched several
`await`s earlier (`readTimes()`, the `sequenceEditor` lookup) before the
transaction opened. Lowest-risk fix tried: re-fetch the item fresh,
immediately before entering `executeTransaction`, so the gap between fetch
and use is as small as possible -- rather than restructuring the
transaction callback to be `async` (untested whether that's even tolerated;
the type signature declares it synchronous-void). **Still unverified.** If
this *also* throws the same error, that would show the staleness isn't
about elapsed time at all, but something `executeTransaction` itself
invalidates on entry -- meaning items would need to be re-fetched from
*inside* the callback, which raises the async-callback question above for
real.

**Separately worth checking, not yet explained:** the audio clip found on
audio track 0 read back as `start=0.000s end=2950.120s` (~49 minutes) --
far longer than the ~24s clip visible on the timeline in the screenshot.
Either audio track index 0 isn't the track carrying the visible clip, or
something else is off. Confirm what's actually on audio track 0 before
trusting a split against it once the staleness error clears, or the spike
will cut the wrong asset even if the clone/trim logic is otherwise correct.

## UPDATE (2026-08-25): panel paints, but first live run hit wrong API names

The manifest fix below got the panel loading and painting for real (confirmed
live). First click of **Split V1 clip 1** got as far as reading the
sequence's in/out (`in=0.000s out=24.000s`, correct for the test clip) and
then failed immediately in `getFirstItem()`:

```
FAILED: neither getTrackItemCount() nor .trackItemCount exists on audio track 0
FAILED: neither getTrackItemCount() nor .trackItemCount exists on video track 0
```

Before re-testing, diffed the whole file against Adobe's actual
`premierepro.d.ts` (`github.com/adobe/premierepro-types`, fetched fresh
rather than working from memory again — recollection was already wrong once,
for the manifest fields below) and found three more guesses that would have
failed the same way, one at a time, each costing another live round-trip:

- **`Track.getTrackItemCount()` / `.getTrackItem(0)` don't exist at all.**
  The real API is `track.getTrackItems(Constants.TrackItemType.CLIP, false)`,
  which returns the whole array directly. This is the bug the log above
  actually hit. Fixed in `getFirstItem()`.
- **`TrackItem.getStart()` / `.getEnd()` don't exist either** — this would
  have been the very next failure once the item-access bug was fixed. Real
  names are `getStartTime()` / `getEndTime()`. Fixed in `readTimes()`.
- **`createCloneTrackItemAction` is not a `ppro.TrackItem` static** — no such
  export exists at all. It lives on `SequenceEditor`, obtained via
  `ppro.SequenceEditor.getEditor(sequence)`. Fixed in `stageSplit()` /
  `runSpike()` (now threads a `sequenceEditor` argument through).
- The types declare `createCloneTrackItemAction` as returning bare `Action`
  (an opaque `{}` type, no methods) — a real hint that the "chainable
  TrackItem" happy path was optimistic, but **not proof**: this same file's
  manifest schema fields (below) were also copied from memory and were
  wrong, so doc-vs-runtime mismatches are an established risk here, not a
  hypothetical one. The duck-type check in `stageSplit()` is left in place
  rather than replaced with an assumption — the next live run is still what
  actually answers this.

`Sequence.getInPoint()`/`getOutPoint()` (added for the in/out-point scoping
change) and `TickTime.seconds` / `TickTime.createWithSeconds()` were both
checked against the same source and are confirmed correct as already
written. `callOrProp()` also now logs the object's actual shape on failure
(via `describe()`) instead of just naming the two guesses that failed —
`toSeconds()` already did this; the track/sequence getters didn't yet, which
is why the failure above named the guesses but not what was actually on the
track object.

**Split-logic questions (clone/trim call order, single-transaction undo
behavior, whether the clone hands back a chainable item) are still fully
open** — the fixes above just get the next live run to the point where it
can actually test them.

## RESOLVED (2026-08-25): manifest used two fields that don't exist in the real schema

Earlier same-day note (superseded below) concluded this was an unfixable
host-side compositing bug, based on: DOM fully populated, layout computed
correctly, DevTools' own hover-highlight overlay rendering correctly, and
even a zero-dependency test page (`<body style="background:red">`, no CSS
file, no JS) rendering nothing. That evidence was real, but the conclusion
drawn from it wasn't — Adobe's own official sample panel
(github.com/AdobeDocs/uxp-premiere-pro-samples) was tried on this exact
install per this file's own suggested next step, **and it rendered fine.**
Same Premiere build, same GPU, same machine. That rules the host out and
puts the cause back in this plugin.

Diffing `manifest.json` against both of Adobe's current sample manifests
(`sample-panels/premiere-api/public/manifest.json`,
`sample-panels/metadata-handler/manifest.json`, fetched live from the repo)
found two real divergences:

- **`preferredDockPosition: "floating"` is not a field in the current UXP
  Premiere manifest schema.** A code search across the entire sample repo
  for that string returns zero hits. Both real samples instead declare
  `preferredFloatingSize` and `preferredDockedSize` (explicit `{width,
  height}` objects). This file had invented a field name rather than
  reading a real schema.
- **`manifestVersion` should be the bare number `5`, not the string `"5"`.**
  Both real samples use the number. This directly contradicts commit
  `a1668d4`'s claim (sourced from recollection, not verified against a real
  manifest) that it "must be" a string — that claim was wrong. (That same
  commit's `host.app: "premierepro"` fix was correct and independently
  confirmed: `metadata-handler`'s manifest uses the array form of `host`
  ours had removed, and `premiere-api`'s uses the object form ours already
  had — both are apparently accepted, so the array-vs-object change wasn't
  the load-bearing part of that fix; the app-id string was.)

`manifest.json` now matches the real schema on both points.

**Update:** fixing `manifestVersion` to the real number `5` turned on real
schema validation — UDT then rejected the plugin outright with `Expected
atleast a single entry in the icons list` (this is progress, not a setback:
it confirms the schema-divergence diagnosis, since the string `"5"` had
apparently been hitting a laxer/legacy parser that let a malformed manifest
through silently, which is consistent with the panel loading-but-blank
symptom this whole thread started from). Added `icons/icon.svg` (a
throwaway placeholder) and populated both the top-level `icons` array and
the entrypoint's `icons` array, matching the shape both real Adobe samples
use. **Reload the plugin and confirm it now loads at all, then confirm the
panel paints** — GPU toggle, restart, and Premiere update are no longer the
leading hypotheses; they were reasonable when the host looked like the only
suspect, but the sample-panel control test moved the suspicion back here.

The split-logic questions this spike exists to answer (clone/trim call
order, single-transaction undo behavior, etc.) are **still fully open** —
none of them could be tested because the panel never became visible enough
to click a button.

## Load it (dev mode — the default, matches issue #18)

UXP Developer Tool → **Add Plugin** → point at this folder's `manifest.json`.
Load, then open the panel from Premiere's plugin panel list.

Open the browser DevTools console for the plugin too (UXP Developer Tool →
the plugin's row → the `</>` / "Debug" icon) — `main.js` logs everything to
both the on-panel log box and `console.log`, but the console is where you'll
see full object dumps if a line gets truncated on-panel.

## Install it as a `.ccx` instead (optional, for convenience)

Issue #18 says load via UXP Developer Tool, not a `.ccx` install — the
reason is #17's documented cold-start bug: an *installed* plugin's
`ws://127.0.0.1` **network permission** isn't honored on cold start. This
spike declares no network permission at all (no `requiredPermissions`, no
WebSocket), so that specific bug may simply not apply here — but that's
untested, not confirmed. If it does misbehave, that itself is useful signal
for #17/#22 (the real plugin *does* need the WebSocket).

To package it:

1. UXP Developer Tool → **Add Plugin** on this folder, if not already added.
2. Click the plugin's **⋮** menu → **Package**. First time only: UDT prompts
   to generate a self-signed certificate — any placeholder name/org/email is
   fine, this is for local install, not Marketplace distribution.
3. UDT writes a `<name>.ccx` next to this folder (or wherever you point it).
   Double-click it — this hands off to Creative Cloud Desktop's installer
   (must be running). Confirm the install prompt.
4. **Fully quit and reopen Premiere Pro** (not just close/reopen the
   project) so it re-scans installed plugins.
5. Check **Window → Extensions** (or **Plugins**, depending on version) for
   "CutDeck Spike #18" — it should now open without UXP Developer Tool
   running at all.

If the panel doesn't appear, or throws immediately on open, or you see
anything resembling `"Permission denied to the url ... Manifest entry not
found"`: that's #17's cold-start bug showing up even without a declared
network permission. Fall back to the dev-mode load above (still fully
intact — installing the `.ccx` doesn't remove the ability to load it via
UXP Developer Tool too) and note the finding on #17, since it changes what
#22's real plugin needs to work around.

## Before clicking anything

Open a **throwaway copy** of a project (per this repo's existing convention
for anything that mutates a live sequence — see `docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md`
Phase 0). Put a clip on V1 and a clip on A1, each long enough to mark an
in/out point inside it. **Mark an in point and an out point on the timeline
(I / O) that fall entirely within the target clip's span** before clicking —
the spike reads the sequence's work-area in/out via
`Sequence.getInPoint()`/`getOutPoint()` and refuses with a clear error if
they don't land inside the clip.

## What the two buttons do

Issue #18 specifies "one button" and "two hardcoded times." This has two
buttons instead of one — deliberately: acceptance requires repeating the
probe on an audio track, which a single hardcoded-track button can't do
without a code edit and plugin reload between runs. The two "hardcoded
times" are the sequence's own marked in/out points rather than numbers baked
into the code — deliberately too, so the spike (and the real plugin it
feeds) only ever touches the work area the editor marked, never the whole
clip. Both buttons run the same logic (`runSpike("video")` /
`runSpike("audio")` in `main.js`) against the first item on V1 / A1 of the
active sequence:

1. Read the sequence's marked in/out points (`Sequence.getInPoint()`/
   `getOutPoint()`) and the clip's current start/end/in-point/out-point;
   refuse if the in/out doesn't land entirely inside the clip.
2. Inside **one** `project.executeTransaction(...)`:
   - Clone the clip in place, *before touching it* (`createCloneTrackItemAction`,
     zero offset, `isInsert=false`) — so the clone inherits the original's
     untouched end/out-point.
   - Trim the original's end + out-point back to cut point A (the head).
   - Trim the clone's start + in-point forward to cut point A (the tail).
   - Repeat the clone+trim step on the tail, at cut point B, producing the
     final tail and leaving a middle piece spanning [A, B].
   - `createSetDisabledAction(true)` on the middle piece.
3. Log the transaction's return value.

This is **one hypothesis**, not a known-working recipe. It deliberately
does **not** match issue #18's literal phrasing ("trim the original's end
back to the cut point first, then clone, then correct the clone's in-point
and start") — cloning after trimming would hand the clone an already-
truncated end/out-point, which the issue's phrasing doesn't mention
correcting back. Cloning first sidesteps that: the clone only ever needs
its start/in-point corrected, never its end/out-point. **Record on the
issue whether trim-then-clone (the literal order #18 describes) also works,
and which order Premiere actually prefers** — that's still open. The other
real unknown is what `createCloneTrackItemAction` hands back.

## The one thing to watch first: the clone's return value

`stageSplit()` in `main.js` logs `clone call returned: ...` every time. Two
outcomes:

- **It duck-types as a TrackItem** (has a `createSetStartAction` method) —
  the code chains straight off it. It also tries `compoundAction.addAction()`
  on it in case the clone mutation itself still needs explicit staging (the
  log line before the trim steps says whether that call was accepted or
  threw — a throw there is expected and harmless if the clone is already
  implicit once `createCloneTrackItemAction` is called inside the
  transaction). This is the happy path the rest of the script assumes.
- **It doesn't** (looks like a bare Action descriptor, or something else) —
  the script logs a `WARNING`, stages just the clone action with no further
  chaining, and the whole transaction throws deliberately (see
  `"aborting before B/disable so this transaction commits nothing rather
  than a half-cut state"` in the log) rather than silently committing a
  malformed split.

If you hit the second case: read what `describe()` printed for the clone
result (own keys + prototype methods) in the console. That tells you the
actual shape without guessing. Likely next step: the clone may only be
resolvable by re-reading the track's item list *after* this transaction
commits (i.e., clone-and-trim-original in one transaction, commit, then a
**second** transaction to trim/disable the newly-appeared item found by
position). That would mean the true single-transaction, single-undo-step
recipe isn't `clone→trim` at all, or needs a different call — which is
itself a real, useful answer to record on the issue.

## Other places the code is guessing

Confirmed correct against Adobe's `premierepro.d.ts` (see the 2026-08-25
update above) and no longer flagged here: `Sequence.getInPoint()`/
`getOutPoint()`, `TickTime.seconds` / `TickTime.createWithSeconds(n)`,
`Track.getTrackItems(trackItemType, includeEmptyTrackItems)`,
`TrackItem.getStartTime()`/`getEndTime()`/`getInPoint()`/`getOutPoint()`,
`SequenceEditor.getEditor(sequence).createCloneTrackItemAction(...)`. Every
`callOrProp()` call still dumps the object's actual shape via `describe()`
if a name turns out wrong anyway — the type defs are a strong hint, not a
guarantee, per this same file's own manifest-schema lesson above.

Still genuinely open:

- **Whether `createCloneTrackItemAction`'s returned `Action` is ever
  chainable at runtime**, despite the types declaring it opaque — the duck-
  type check in `stageSplit()` is the thing that answers this for real.
- Everything assumes the clip has **speed 1.0 and is not reversed** — no
  check for either, unlike the real mark-and-apply plugin's `live_clip.py`
  which refuses both. Fine for a spike against a known test clip; not fine
  to reuse as-is past this issue.

If a call throws with a message like `"X is not a function"`, that's the
fastest signal something above is wrong — the log right above the error
will have the object's real method list from `describe()`.

## Recording the result

Copy the answers to these straight into issue #18 when done (its own
acceptance list, repeated here for convenience):

- [ ] One clip becomes three items with edit points at A and B, frame-accurate.
- [ ] The middle item reads back `isDisabled() === true` and appears greyed out.
- [ ] The outer two items are unchanged in content (tail after B is the
      right footage, not a repeat of the head).
- [ ] Nothing shifted — the last item still ends where the original ended.
- [ ] **Ctrl+Z reverses the entire operation in one step.**
- [ ] Repeat on the audio track — `createSetDisabledAction` mutes an
      `AudioClipTrackItem` as expected.
- The exact working call order + parameter values that actually worked
  (especially `timeOffset`, `isInsert`, `alignToVideo`), if different from
  what's in `main.js`.
- Whether `createSetStartAction`/`createSetEndAction` alone were enough, or
  `createSetInPointAction`/`createSetOutPointAction` were also required.
- Any intermediate state Premiere rejected (an exception, or a silently
  wrong result caught by the acceptance checks above).
- Whether one transaction really produced one undo step.
- Rough per-split timing, to extrapolate to the ~200–400 span × N track
  scale in #17.

If clone+trim doesn't compose into a clean split at all, say so on the
issue and stop there — per #18's own instructions, that invalidates #17's
approach rather than something to work around quietly.
