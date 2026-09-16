# CutDeck spike — assemble probe (issue #25, Phase 0)

**Throwaway.** Delete this whole folder once it has answered. Nothing in the repo
imports it; `rm -rf uxp/spike_assemble_probe` is the whole retirement.

## Why it exists

Issue #25 replaced the razor with a three-point edit: place every span, disable the
CUT ones, and let Apply ripple the disabled ones out. The geometry is built and
tested (`cutdeck/assemble_export.py`, `uxp/cutdeck/assemblyPlan.js`). The API calls
are not — **not one of them has executed once in this project.** They come from
Adobe's published type definitions, which is the same evidentiary footing that
produced eighteen confident, wrong rounds on the clone route (#18/#24).

This spends one click to find that out at **N=3 spans instead of 443**.

## Three unknowns, one click

That deliberately breaks the one-variable-per-round discipline #18 used. The reason
is that these three are independent and produce log signatures that cannot be
mistaken for one another:

| # | Question | Why it decides something |
|---|---|---|
| 1 | Does `createSetSettingsAction(source.getSettings())` carry the real timebase? | A fabricated 25 fps silently corrupts every 29.97 and 59.94 job. This project's `media` rows *already* read `25/1` from `probe()`'s fallback. |
| 2 | Do three interleaved `setInOut`/`overwrite` pairs survive **one** transaction? | Three distinct ranges = the cheap path lives. Three identical = the shared `ClipProjectItem` resolves against the last value, and the fallback is one transaction per span (acceptable now: undo is `deleteSequence`). |
| 3 | Does `createRemoveItemsAction(sel, ripple=true, ANY)` work? | Apply is built **entirely** on this call. |

Unknown 1 gates 2 and 3: a destination on the wrong timebase makes every placement
wrong by construction, so the probe refuses to measure against it.

## Run it

1. **Open a disposable project.** This mutates. Never a real edit.
2. Open a sequence whose **first clip on V1** is at least **12 frames** long. The
   probe carves three spans of 1/2/3 units from it (distinct starts *and* distinct
   lengths, so a partial collapse is as visible as a total one) and places them
   back to back. No marks needed; the helper does not need to be running.
3. Load `manifest.json` in the UXP Developer Tool, open **CutDeck Assemble Probe**
   from Window > UXP Plugins.
4. Click **Run assemble probe (N=3 spans)** once.
5. **Copy log to clipboard** and paste the whole thing onto issue #25. The same
   report is in the UXP Developer Tool console as JSON.
6. **Delete the `CutDeck probe — assemble` sequence by hand.** The probe never
   deletes it — a half-built sequence is the evidence (issue #25).

## Reading the verdicts

```
VERDICTS  settings:  inherited | fabricated | unreadable
          placement: independent | collapsed | distinct but wrong | wrong item count | threw
          removal:   exact | wrong length | threw | unverifiable | not reached
```

- `inherited / independent / exact` — the whole route is live. Build `assemblyHost.js`.
- `fabricated` — stop. The destination must be created another way; nothing past it
  is worth measuring.
- `collapsed` — the route lives, at one transaction per span. Record the cost and
  re-plan Build for 443 transactions.
- `distinct but wrong` — read the `seams` and `mismatches` lines. A seam is a
  one-frame gap (black flash) or overlap (a frame eaten by `createOverwriteItemAction`).
- `threw` on removal — Apply needs a different primitive. That is a route-level
  finding, not a bug to patch here.

Anything the probe could not do — a missing method, a method that throws, an
unreadable value — is recorded as a finding rather than raised. A probe that dies
on the first surprise tells you less than the build it was probing.

## What is mock-proven and what is not

`tests/cutdeck_assemble_probe.test.cjs` (25 tests) drives `assembleProbe.js` against
`tests/fixtures/cutdeck_assemble_host.cjs`, a small real timeline with a shared
`ClipProjectItem`. It proves the probe **tells the verdicts apart** and survives
every way a host can disappoint it. It proves **nothing about Premiere.** Until the
click above happens, every verdict is `null`.

```powershell
node --test tests/cutdeck_assemble_probe.test.cjs
```

## Layout

`assembleProbe.js` holds all the orchestration and takes the host as an argument —
that is what makes it testable in Node. `main.js` holds only what cannot be tested
outside Premiere: `require("premierepro")`, the log element, the two buttons.

Scaffolding (`describe()`, the `lockedAccess`-wraps-`executeTransaction` pattern,
the dual-fallback copy-log) is carried over from `uxp/spike18_split_probe/`, which
earned it across eighteen live rounds. `runSpike()` is not.
