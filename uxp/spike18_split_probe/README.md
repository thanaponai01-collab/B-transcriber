# CutDeck spike #18 — split probe

## UPDATE (2026-08-25, round 12): clone+trim confirmed on a real cut; now repositioning the clone into the tail

Round 11's first attempt accidentally re-used a stale in/out mark (the
clip's own end had gotten stuck at 24s from an earlier round). Re-run with a
genuine in/out mark inside the full clip (`57.080s`–`135.960s`) gave a
clean, fully confirmed result: `item[0]` (trimmed original) read back
`end=out=135.960s` exactly as predicted, and `item[1]` (the clone at the
temp offset) read back the **full pre-trim duration** (`2950.120s`) —
confirming the clone captured the original's untouched state even with the
trim happening in the same commit. **The single-transaction clone+trim
split design is confirmed working** for the head/trim half.

This round does the other half: repositioning the clone from its temp
parking spot to its real final position, right after the trimmed head, so
it becomes the tail. This needs its own real test, not an assumption from
round 10 — round 10's `createSetEndAction` test happened to have `start=0`
*and* `in=0` on that clip, so "the bound snaps to match the new value" and
"the bound shifts by the same delta" were indistinguishable outcomes. This
clone sits at `start=3600s, in=0.000s` (start ≠ in) — a case where those two
theories genuinely diverge, so it's a real test. `main.js` now finds the
clone via a new `findItemNearStart()` helper (its return value still isn't
chainable, so it has to be re-queried regardless of offset) and calls
`createSetStartAction` **only** (no `createSetInPointAction` — same fix as
round 10/11) to move it to `cutAbsSec`. **Untested — this is what the next
live run needs to report.** The correct answer for a real split is: the
in-point should land on `cutMediaSec` (continuing exactly where the head's
trim cut off), not stay at `0` and not snap to `cutAbsSec`'s own value — the
log's `ANALYSIS` line spells out what each possible result would mean.

## UPDATE (2026-08-25, round 11): ROOT CAUSE FOUND — retrying the original clone+trim design with the fix

Round 10's live run: `createSetEndAction` alone committed cleanly, **and the
out-point moved with it automatically** — `AFTER` showed
`end=24.000s out=24.000s` from a single call, with no
`createSetOutPointAction` anywhere. **Premiere derives the media bound from
the sequence-time bound on its own.** Every crash since round 7 happened
because this file was staging `createSetEndAction` *and*
`createSetOutPointAction` together, which conflict internally — that
"belt and suspenders" call was the bug, not a safety net. The fix: never
call `createSetOutPointAction`/`createSetInPointAction` alongside
`createSetEndAction`/`createSetStartAction` — the single call is sufficient.
This also answers, for real, the question flagged since round 1's file
header: "whether `createSetStartAction`/`createSetEndAction` alone were
enough" — yes.

This round retries round 7's original scenario — clone (to the temp offset)
+ trim the original, together in one transaction — with the fix applied:
only `createSetEndAction`, no out-point call. **Untested — this is what the
next live run needs to report.** If it commits cleanly, the
single-transaction clone+trim split design (which looked dead after round
7) is back alive — round 7's crash was this bug, not a fundamental
clone+trim incompatibility. The `ANALYSIS` log line spells out exactly what
a clean result should look like for both items.

## UPDATE (2026-08-25, round 10): round 8's clone-poisoning theory is dead — trim itself crashes, even with zero clone history; isolating which trim call is the trigger

Round 9's live run (both V1 and A1): `BEFORE` showed exactly 1 item, the
untouched original — confirmed clean, no clone anywhere in the session. The
trim still threw the identical `A nullptr was dereferenced`. **Round 8's
clone-poisoning theory is wrong.** The crash comes from the trim itself,
independent of any clone history. Everything staged without a JS error
first — `createSetEndAction` returned a valid action, `addAction` accepted
it, `createSetOutPointAction` exists and was staged too — so both trim
actions land fine; only the native commit fails.

The one remaining untested variable, named in this file's own open-questions
list since round 1 ("whether `createSetStartAction`/`createSetEndAction`
alone were enough, or `createSetInPointAction`/`createSetOutPointAction`
were also required"): does staging **both** the sequence-time bound
(`createSetEndAction`) and the media bound (`createSetOutPointAction`) on
the same item in one commit crash, versus either alone? This round stages
**only** `createSetEndAction` — no out-point call at all. **Untested — this
is what the next live run needs to report.** Two outcomes:

- **Commits cleanly** — `createSetOutPointAction`, or specifically staging
  both together, is the crash trigger. Worth checking on that same run
  whether the out-point moved on its own (Premiere auto-deriving the media
  bound from the sequence-time bound) — if so, a real split may not even
  need to call `createSetOutPointAction` separately at all.
- **Still crashes** — `createSetEndAction` alone is already broken, which
  rules out the "these two conflict" theory and points further out: the
  `cutAbsSec` value, or trimming this specific item/track/host build at all.
  Would need an even smaller isolation next (e.g. a call that's supposed to
  be a total no-op, or trying `createSetStartAction` instead) or escalating
  to Adobe/community with a minimal repro.

## UPDATE (2026-08-25, round 9): round 8's bigger finding — a committed clone crashes a later, unrelated trim; testing trim with no clone at all

Round 8's live run (both V1 and A1, independently): transaction 1 (clone
alone) committed cleanly both times. Transaction 2 — a **freshly re-fetched
item, pure trim, zero clone actions anywhere in it**, in its own separate
transaction — still threw the identical `A nullptr was dereferenced` from
inside `executeTransaction`. So round 8's own hypothesis (simultaneous
staging is what's broken) is wrong, or at least incomplete: a *committed*
clone appears to poison the track such that even a later, completely
unrelated transaction touching it crashes the same way.

But there's a control this project hasn't run yet: **every trim attempt so
far (round 7, round 8) happened with a clone earlier in the same session.**
Nobody has tried a trim with no clone anywhere in its history. If that also
crashes, the clone-poisoning theory is wrong and trim itself is broken here
regardless of clone — a very different, bigger finding. If it commits
cleanly, round 8's finding stands.

This round removes the clone entirely — `main.js` now stages only a trim of
the untouched original, no `createCloneTrackItemAction` call anywhere.
**Untested — this is what the next live run needs to report**, and it needs
to run on a genuinely clean clip (undo any leftover clones from round 7/8
first). The `ANALYSIS` log line spells out what a clean commit vs. a crash
each mean.

## UPDATE (2026-08-25, round 8): round 7 crashed natively; testing two separate transactions instead of one

Round 7's live run: the clone staged fine (`clone call returned: [object
Action]...`, no JS error), then `executeTransaction` itself threw `A nullptr
was dereferenced` — no exception frame inside the callback, meaning our
staging code (clone, then the two trim actions) ran to completion without a
JS-level error, and the native commit choked when actually applying the
combination. This is a real crash, not a guess-gone-wrong: clone alone
(rounds 5–6, live-confirmed twice) and trim alone (proven safe in a real
production plugin, `leancoderkavy/premiere-pro-mcp`, which stages
`createSetStartAction`/`createSetEndAction`/etc. routinely) are each
individually fine. The suspect is specifically **combining a clone with
another structural edit inside one compound transaction** — not trim in
general, and the JS-level clone-then-trim staging order inside that one
callback was never actually the tested variable (it stayed constant; only
"together" vs "separate" changes between round 7 and this round).

This round: same two operations, split into two separate transactions —
commit the clone alone first (transaction 1, reusing the already-proven
round 5/6 code unchanged), then commit the trim of the original alone
second (transaction 2, re-fetching a fresh item reference right before it,
same discipline as every prior transaction in this file). **Untested — this
is what the next live run needs to report.** Two outcomes:

- **Both commit cleanly** — the nullptr crash is specifically about
  simultaneity, and the real plugin's split recipe needs two transactions
  per split (one undo step each, not one shared undo step across the whole
  split — a real design change from the original "single transaction, single
  undo" goal, worth flagging on #18 if confirmed).
- **Transaction 2 also crashes** — the finding gets bigger: a clone leaves
  the project in a state that even an unrelated *later* transaction can't
  tolerate, which would point at something needing to happen between the
  two transactions (a save? a redraw? re-reading sequence state some other
  way?) rather than just "don't combine them."

## UPDATE (2026-08-25, round 7): testing clone+trim composed in one transaction

Round 5 re-confirmed with a clean single-click before/after (1 item → 2
items, clone correctly full-duration at the offset position). Round 6's
clipboard permission fix is still awaiting its own live confirmation.

This round tests the question that's been open since this file's very first
commit: **does clone+trim actually compose into a clean split when done
together, and does the order matter?** Every prior round either cloned alone
(rounds 4–6) or tried to trim the *clone's* return value (round 3 — doesn't
work, it's not chainable). Neither ever tested trimming the *original*
(`freshHeadItem` — a real, valid, chainable reference, unrelated to the
clone-chainability problem) in the same transaction as the clone.

`main.js` now stages, in one transaction: clone the original onto the
`PROBE_OFFSET_SEC` temp position (as before), then trim the original's end/
out-point back to the sequence's marked **out** point (`bSec`) — not the in
point (`aSec`), which is `0` for this test sequence and would trim the head
to a degenerate zero-length item. **Untested — this is what the next live
run needs to report.** The log's new `ANALYSIS` line spells out exactly what
to compare: does item[0] show the trim applied, and does item[1]'s duration
match the original's *full* length (clone captured pre-trim state) or the
*trimmed* length (clone captured post-trim state)? Whichever it is answers
the ordering question directly, live, instead of guessing from the type
defs — decides whether the real plugin should clone-then-trim or
trim-then-clone.

## UPDATE (2026-08-25, round 6): nonzero-offset clone confirmed working; copy-log needs its own manifest permission

**Round 5 succeeded.** A live run's log showed the track already holding 2
items before that particular click even started: `[0]` the original
(`start=0.000s end=2950.120s`) and `[1]` a real duplicate at
`start=3600.000s end=6550.120s in=0.000s out=2950.120s` — correct duration,
correct in/out (full copy of the original's source range, just shifted
+3600s in sequence time). That `[1]` was produced by an *earlier* click of
the same round-5 build; the click that generated the log ran again with the
destination already occupied, so its own before/after pair was another
no-op overwrite (expected, consistent with round 4/5 — overwriting existing
content is still a no-op either way). **The real finding: a same-track,
nonzero-`timeOffset`, `isInsert=false` clone onto genuinely empty track
space produces a distinct, correctly-shaped second item.** The two-
transaction redesign (commit clone+head-trim, re-query the track for the
new item by its known predicted position, commit a second transaction to
finish the tail + disable) is now unblocked — no longer guessing on top of
an unverified clone geometry.

Also this round: added a "Copy log to clipboard" button (dual-fallback:
`navigator.clipboard.writeText` first, `require("uxp").clipboard.copyText`
second — pattern confirmed against a real live Premiere UXP plugin,
`rtwoo/soundscape-generator`). First live click failed with a genuine,
informative error: `Clipboard access not supported for 3P plugins with
manifest version upto 4. Valid manifest entry required from manifest
version 5.` We're already on `manifestVersion: 5` (round 1 fix) — clipboard
needs its own explicit `requiredPermissions` entry too. Confirmed against
the same official Adobe sample used for the earlier manifest fixes
(`sample-panels/premiere-api/public/manifest.json`):
`"requiredPermissions": { "clipboard": "readAndWrite" }`. Added to
`manifest.json`. **Untested** — manifest changes typically need a full
plugin reload (remove + re-add in UXP Developer Tool, not just a panel
refresh) to take effect; confirm the copy button works on the next round.

## UPDATE (2026-08-25, round 5): zero-offset clone confirmed to be a no-op — testing a nonzero offset next

Round 4's live run: `executeTransaction returned: true` (committed, no
throw), but `logTrackItems()` showed **exactly 1 item both before and after,
byte-identical** (`start=0.000s end=2950.120s in=0.000s out=2950.120s`,
`disabled=false` both times). A same-track, zero-time-offset,
`isInsert=false` (overwrite) clone is confirmed to be a no-op — "overwrite"
means the clone replaces the original in place rather than coexisting with
it, at least in this degenerate 100%-identical-span case. Rules out the
zero-offset case entirely for building a split.

One variable changed for this round: `main.js` now clones with a large
nonzero `timeOffset` (`PROBE_OFFSET_SEC = 3600`, i.e. 1 hour past the clip's
own start) so the clone lands on empty track space with nothing to
overwrite — same track, same `isInsert=false`, everything else unchanged.
**Untested — this is what the next live run needs to report.** This only
tests whether a nonzero-offset clone produces a genuine second item at all,
not yet where a real split's tail needs to land — that positioning logic is
a later round, once there's a confirmed way to get an item reference to the
new clone after commit (still via re-querying the track by position, since
the return value stays non-chainable regardless of offset).

If this also produces only 1 item, `isInsert=false` may not be usable for
producing a duplicate at all, and `isInsert=true` (which ripples/shifts the
timeline, per its own doc text) would need trying next — a bigger design
question, since the whole appeal of "clone in place" was avoiding ripple.

## UPDATE (2026-08-25, round 4): lockedAccess fix confirmed live; now probing what clone actually produces

Round 3's `lockedAccess` fix worked — `"The script object is no longer
valid"` is gone. The live run got all the way to `createCloneTrackItemAction`,
which succeeded and returned `[object Action] ownKeys=[] protoMethods=[]` —
confirming, live, what the type signature and both reference sources already
predicted: the clone is not chainable. `stageSplit()` correctly logged the
WARNING and aborted before staging anything else, so nothing committed —
the safe outcome. (Also resolved in passing: the audio clip really is a
~50-minute source file, matching the timeline in the test screenshot — not
a wrong-track bug as previously flagged.)

The one-transaction clone+trim design is confirmed dead: there's no item
reference to chain a trim onto. The obvious next move is a two-transaction
redesign (commit clone + head-trim, re-query the track for the new item by
position, commit a second transaction to finish the tail + disable). **Not
done yet** — that would build on a real unknown: nobody has verified what a
**same-track, zero-time-offset, `isInsert=false` (overwrite)** clone actually
produces. Adobe's own sample only demonstrates cloning to a *different*
track, with a nonzero time offset, `isInsert=true`. Guessing the redesign on
top of that gap risks another wrong-assumption round-trip.

So this round is diagnostic only: `main.js` now stages *just* the clone (no
trims) inside one transaction, commits it for real, and calls the new
`logTrackItems()` helper before and after to log every item's start/end/
in/out. **Untested — this is what the next live run needs to report.** Do
not click twice on the same clip before recording the result — inspect the
before/after item list, record it on issue #18, then `Ctrl+Z` before trying
anything else. Three possible outcomes, all informative:

- **Item count goes 1 → 2**, and the second item's start/end differ from the
  first only in track position (or reveal some geometry) — the clone
  actually duplicated in place. The redesign can proceed knowing where to
  look for the new item after commit.
- **Item count stays 1** — `isInsert=false` at zero offset either overwrote
  the original in place (a no-op duplicate) or was silently rejected. Would
  mean the clone needs a nonzero `timeOffset` (matching Adobe's own sample)
  even for a same-track split, with the clone moved back afterward.
- **The commit itself throws or `executeTransaction` returns `false`** —
  same-track same-position overwrite may be an invalid edit outright, ruling
  out `isInsert=false` for this use case entirely.

## UPDATE (2026-08-25, round 3): found the missing `lockedAccess()` wrapper

Round 2's re-fetch-before-use fix did **not** clear `"The script object is no
longer valid"` — same error, same stack, on a freshly re-fetched item with no
further awaits before the transaction call. That confirms round 2's own
fallback hypothesis: staleness isn't about elapsed time.

Diffed against two real sources instead of guessing again: Adobe's own
official sample (`AdobeDocs/uxp-premiere-pro-samples`,
`sample-panels/premiere-api/src/sequenceEditor.ts`) and an independent
third-party UXP Premiere plugin (`leancoderkavy/premiere-pro-mcp`, which
enforces the pattern via a dedicated eslint rule,
`@adobe/premierepro/prefer-locked-access-wrapper`). **Every single
`executeTransaction` call in both sources, with no exception, runs inside
`project.lockedAccess(() => {...})`.** This file was calling
`executeTransaction` bare. `lockedAccess`'s own doc text — "project state
will not change during the execution of callback function" — is exactly the
guarantee a stale-script-object error would indicate is missing.

Fixed in `main.js`: `executeTransaction` now runs inside
`project.lockedAccess(() => {...})`. Also dropped the incorrect `await` on
`executeTransaction`'s return — its type signature is synchronous `boolean`,
not `Promise<boolean>`; the `await` was harmless (a no-op on a non-Promise
value) but wrong. **Untested — this is the next thing a live run needs to
confirm.**

Both sources also never chain a further `create*Action` call off
`createCloneTrackItemAction()`'s return value — only ever
`compoundAction.addAction(cloneAction)`. This corroborates (independently of
the type signature alone) that `stageSplit()`'s duck-type "happy path" is
expected to lose to the fallback WARNING/abort branch. If the `lockedAccess`
fix clears the crash and the next run lands in that fallback, **that is the
expected result, not a new mystery** — see "The one thing to watch first"
below for what to do next in that case (the two-transaction redesign).

Separately, still unexplained and still worth checking independently of the
above: the audio clip on audio track 0 is still reading back as
`start=0.000s end=2950.120s` (~49 min) against a visible ~24s clip on the
timeline. Confirm what's actually on audio track 0 before trusting a split
against it.

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
