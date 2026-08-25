# CutDeck spike #18 — split probe

**Throwaway.** Answers one question for issue #18: does clone+trim compose
into a clean split in UXP, and in what order? Not wired into `cutdeck/`,
`bridge.py`, or `mark_export.py` — those already exist for the real
mark-and-apply plugin (#19–#22) and depend on this spike's answer, not its
code. Delete this folder once #18 is closed, unless its answer says the
approach works and #22 wants to start from it.

## BLOCKED (2026-08-25): panel content never paints on this install

Loaded successfully (dev mode, developer mode enabled, correct manifest),
and the panel opens with no console errors. But nothing in it ever renders
— confirmed this is **not our code**:

- DOM is fully populated (verified in DevTools Elements tab — every
  element from `index.html` is present).
- Layout computes correctly (Computed tab showed a real box model: correct
  padding/margin/width for a button element).
- DevTools' own hover-highlight overlay (drawn independently of the page,
  directly by the browser engine) renders in the correct position when
  hovering a DOM node.
- A zero-dependency test page (`<body style="background:red">` + inline
  blue `<h1>`, no CSS file, no JS) **still rendered nothing.**

That combination — DOM/layout/DevTools-overlay all working, but the page's
own content layer never composited to screen, even with zero CSS/JS
involved — points to a **host-side panel-compositing bug** in this
Premiere Pro install (title bar reads "Premiere Pro v26.3.2.2 **(Debug)**"
— a debug build, which may be relevant). Not something fixable from inside
the plugin.

**Before spending more time on the split logic itself, resolve this:**
- Check for a Premiere Pro update (a non-Debug build may not have this).
- Try Adobe's own official minimal UXP sample panel
  (github.com/AdobeDocs/uxp-premiere-pro-samples) on this same install —
  if it *also* renders blank, this is an Adobe-side bug worth reporting
  (community.adobe.com has an active bug-reports section for exactly this
  category of issue — several UXP-in-Premiere-Pro load/render bugs are
  already tracked there).
- Try toggling the Mercury Playback Engine renderer setting
  (GPU vs. Software Only) in Premiere's Preferences — panel compositing
  bugs are sometimes GPU-driver-related.
- A full machine restart (not just Premiere) is cheap to try first.

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
Phase 0). Put a clip on V1 at least 5–6 seconds long — long enough that the
default A=2s/B=4s cut points land inside it — and a clip on A1 for the
second button. Adjust the A/B fields in the panel if your clip is shorter.

## What the two buttons do

Issue #18 specifies "one button" and "two hardcoded times." This has two
buttons and the times are editable number inputs instead — deliberately:
acceptance requires repeating the probe on an audio track, which a single
hardcoded-track button can't do without a code edit and plugin reload
between runs, and editable fields avoid the same reload cycle just to try a
different A/B on a differently-sized test clip. Both buttons run the same
logic (`runSpike("video")` / `runSpike("audio")` in
`main.js`) against the first item on V1 / A1 of the active sequence:

1. Read the clip's current start/end/in-point/out-point.
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

- **`.seconds` on TickTime values** (`toSeconds()` in `main.js`). If this
  throws, the log line right before it dumps every enumerable property the
  object actually has — use that to fix the accessor name.
- **`TickTime.createWithSeconds(n)`** as the way to build a time to pass
  into `createSetStartAction` etc. — unverified against a live host.
- **`getTrackItemCount()`/`getTrackItem(0)`** as the track's item-access
  API — falls back to bare `.trackItemCount` if the getter doesn't exist,
  but only for the count, not for item access.
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
