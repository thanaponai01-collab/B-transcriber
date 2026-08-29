# HANDOFF — CutDeck: XML recut (multi-layer sequence, sync-preserving)

**For:** Claude Code, working in `Transcriber_v2` (repo: `B-transcriber`).
**Hardware:** RTX 3070, 8 GB VRAM. Windows host. (Nothing in this handoff needs the GPU.)
**Prime directive:** unchanged — *a false cut is worse than a missed one*. One layer down,
that reads: **a silent mis-split is worse than a loud refusal.**
**Discipline:** every phase ends with the full suite green plus the acceptance tests listed
per phase. Read `CLAUDE.md`, `IMPLEMENT_CUTDECK.md` §B, `HANDOFF_CUTDECK_LIVE_SEQUENCE.md`
and `TODO_LEDGER.md` first. Update `TODO_LEDGER.md` as phases land.

---

## Why this handoff exists

`HANDOFF_CUTDECK_LIVE_SEQUENCE.md` set out to cut an already-assembled Premiere sequence
**in place**, via generated ExtendScript driving the QE DOM (`cutdeck/jsx_export.py`). That
route was retired (issue #23) and replaced by a **UXP mark-and-apply** plugin
(`cutdeck/mark_export.py` + `cutdeck/live_clip.py`, issue #17/#19/#20) — split composes
from UXP primitives that do exist (`createCloneTrackItemAction` + the trim actions), so
**the "UXP has no split/razor action" claim once made about this is false and already
corrected in `TODO_LEDGER.md`'s issue #17 section**; an earlier draft of this handoff
repeated the retired claim, which was a re-derivation error, not new evidence — do not
cite it again.

The reason a second, independent mode is still worth building is different, and current:

- The mark-and-apply **plugin itself is blocked by a host bug**, not a capability gap: the
  UXP panel loads with a correct DOM (confirmed in DevTools) but **nothing paints on
  screen** in Premiere 26.3.2.2 — a panel-compositing bug, isolated via DevTools' own
  hover-highlight overlay rendering correctly in the right place throughout (see
  `uxp/spike18_split_probe/README.md`, 2026-08-25). Unresolved as of this writing.
- Classic ExtendScript/QE DOM (`jsx_export.py`'s original route) is supported only
  **through September 2026** and the user's Premiere build has already dropped the
  `File > Scripts` menu — a dying path regardless of the panel bug.

So this handoff is not a workaround for a missing UXP capability — it is a **second, fully
independent mode** that keeps working even if the panel-compositing bug is never fixed,
because it has no live-Premiere or plugin-panel dependency at all.

**This handoff is that transformation.** The editor exports their synced sequence as FCP7
XML; CutDeck rewrites it; the editor imports the result as a *new* sequence. The original
project is never touched by anything but Premiere itself.

### Relationship to the other two modes

| Mode | Module | Input | Risk |
|---|---|---|---|
| `new_sequence` | `xml_export.py` | one media file + `CutPlan` | a bad export fails to import |
| `in_place` | `jsx_export.py` | `CutPlan`, live Premiere | a bad edit corrupts a live project |
| `recut_sequence` | `xml_recut.py` **(this handoff)** | the editor's own XML + `CutPlan` | a bad rewrite produces a wrong-but-plausible new sequence |

`jsx_export.py` is **superseded, not deleted** — see Phase 4.

---

## The core invariant (read this before writing any code)

**A cut is a global time-domain operation, not a per-clip edit.**

Everything at or after a cut point moves left by exactly the cut's frame count. Everything.
Clips on every video and audio track; empty gaps; sequence markers; tracks that are locked,
muted, or disabled. Nothing is exempt, because an exemption *is* the desync.

The testable form, and the sync guarantee this whole mode rests on:

> For every pair of clipitems on different tracks, their relative timeline offset is
> identical before and after the transform — unless one of them fell inside a cut region.

Sync is therefore preserved **by construction**, not by matching Premiere's sync-lock
semantics, not by hoping ripple-delete propagates. That is the entire reason this design
beats the in-place one.

### What the user's sequences actually are (confirmed 2026-08-29, do not re-derive)

- **Manual vertical stacks**, not Multi-Camera Source Sequences. N angles synced by hand
  onto V1..Vn, audio angle already chosen. There is no live multicam clip to flatten, so
  FCP7 XML round-trips the structure essentially losslessly.
- **No effects, no Lumetri, no MOGRTs, no speed changes, no nesting.** Believe this for
  today's sequences and *not* for next quarter's — hence Phase 2's strict refusal list.
- Angle switching is finished **before** CutDeck runs. If that ever stops being true, this
  entire approach is wrong and must be revisited, not patched.

---

## PHASE 0 — the fixture (human-only, gates everything)

**No parser is written until a real Premiere export exists in this repo.** This project has
paid for guessed structure three times (`TICKS_PER_FRAME`, the UXP capability assumption,
the `store.get_last_passing_eval()` filter gap). A parser written against an *imagined*
xmeml would ship with passing tests, which makes it more dangerous, not less.

**Human step:**
1. Duplicate a real sequence; trim to **30–60 seconds** containing **at least two clear
   silence gaps** and at least 3 stacked video tracks.
2. `File > Export > Final Cut Pro XML`.
3. Also export the matching **full-sequence audio mixdown** (see Phase 3's duration guard —
   it must span the whole sequence, not an in/out range).
4. Run the scrubber (`scripts/scrub_fcpxml.py`, Phase 1) over the XML and **eyeball its
   output** before it is committed.
5. Commit the scrubbed XML to `tests/fixtures/`. Keep the raw export **local only** — it
   carries absolute paths to real footage and possibly client names, and this repo is on
   GitHub.

**Acceptance:** a scrubbed `.xml` fixture in `tests/fixtures/`, plus a line in
`TODO_LEDGER.md` recording its track counts and rate. Later, a **second** fixture — the
same sequence after the editor manually cuts it in Premiere — becomes the ground truth the
transformer's output is compared against. One is enough to start.

---

## PHASE 1 — `scripts/scrub_fcpxml.py` (buildable now, no fixture needed)

Path/name sanitizer so a fixture is committable the moment it exists. Pure string work over
a parsed tree; makes no assumptions about sequence structure, which is exactly why it can be
written before Phase 0 lands.

**Build:**
- Rewrite every `<pathurl>` to a stable dummy (`file://localhost/C:/fixtures/<n>.<ext>`),
  one dummy per distinct real path so `<file>` id de-duplication stays observable.
- Neutralize `<name>` on `<sequence>` and on `<file>` elements; **leave `<clipitem><name>`
  alone** where it carries a CutDeck round-trip key (`cd###_p###_s####`).
- Leave every numeric element untouched — rates, frames, durations, ids are the fixture's
  entire value.
- Print a summary of what it changed, so step 4 above is a real review, not a rubber stamp.

**Acceptance:** `tests/test_scrub_fcpxml.py` — a synthetic xmeml in, no real-looking absolute
path out, every `<start>/<end>/<in>/<out>/<rate>` byte-identical, and two clipitems that
shared a source path still share one dummy path.

---

## PHASE 2 — `cutdeck/xml_recut.py`, the transform (needs the Phase 0 fixture)

**Method: surgical tree rewrite. Not model-and-regenerate.**

Parse the editor's XML into an ElementTree, mutate only the numbers that must change, and
re-serialize everything else as it arrived. Anything the code does not understand survives
because the code never looks at it. Model-and-regenerate would be cleaner and would silently
drop every element nobody thought to model — and "nobody thought to model it" is by
definition not enumerable.

```python
def recut(source_xml: str, plan: CutPlan) -> str:
    """Apply a CutPlan's CUT spans to an exported FCP7 sequence, in place in the tree.

    Pure: string in, string out, no side effects, no Premiere dependency.
    """
```

**Per cut span, per track, three cases plus a fourth:**

| Case | Action |
|---|---|
| clipitem wholly outside the cut, after it | shift `start`/`end` left by the cut's frames |
| clipitem straddles a cut boundary | razor it — trim `out`/`end` (or `in`/`start`) accordingly |
| clipitem wholly inside the cut | remove it |
| gaps, markers, locked/muted/disabled tracks | shift identically — **no exemptions** |

**Frame rate:** the source XML's own `<sequence><rate>` is authoritative. A `CutPlan` derived
from an audio-only mixdown may carry a **fabricated 25fps** `Timebase` (see
`sequence_mixdown.py`'s own warning) — a disagreement is a **hard refusal**, never a silent
reconcile. Better still: feed the XML's real rate *back* into the mixdown step so `--fps`
stops being something a human must remember to type correctly.

**Frame math goes through `transcribe.timebase` only.** Same rule as both sibling modules.
No float fps, no float seconds, ever.

**Tracks: cut every one, unconditionally, preserving each track's `<locked>`/`<enabled>`
flags in the output.** Note this is the *opposite* of `jsx_export.py`'s loop, which skips
locked/muted tracks — and deliberately so. In a live sequence, skipping protects work the
editor locked. In a freshly generated sequence nothing is being clobbered, and a track that
doesn't shift is precisely the desync this mode exists to prevent.

**Links:** rewrite `<link>` / `<linkclipref>` / `<clipindex>` correctly when a clipitem
splits. **This is the first thing to sacrifice.** Timeline geometry and therefore sync are
guaranteed by the global shift regardless of links; linking only governs what happens when
the editor drags a clip afterwards. If the real fixture shows Premiere's link structure is
nastier than expected, ship a correct **unlinked** sequence rather than a subtly wrong linked
one — and record that choice in the ledger.

**Markers:** shift with everything else. A marker inside a cut region is **dropped and
counted**, and the count is reported to the user. A marker that doesn't shift is a wrong note
the editor will trust.

**Refusal list: strict.** Refuse on *anything* not a recognised plain clipitem when a cut
boundary lands inside it — `<transitionitem>`, nested sequences, speed/time-remap, clipitems
carrying `<filter>`. The refusal message **names the exact clip and its timecode**.

Strict is chosen over permissive on purpose, and it is self-correcting: every time it stops
the editor on something harmless, that structure gets added to the recognised list *with a
test*, and the tool is permanently smarter. Permissive never generates that feedback — it
generates a wrong sequence nobody audits.

**Acceptance (`tests/test_cutdeck_xml_recut.py`), against the Phase 0 fixture:**
- **Structural invariant:** for every pair of clipitems on different tracks, relative offset
  is unchanged unless one was inside a cut. This is the sync guarantee, tested mechanically.
- **Duration identity:** output sequence duration == input duration − summed CUT frames,
  exactly, in frames.
- A clipitem wholly inside a cut is gone; one straddling a boundary is trimmed, not dropped.
- A locked/disabled track shifts exactly like an unlocked one.
- Markers shift; a marker inside a cut is dropped and counted in the report.
- A `<transitionitem>` under a cut boundary raises, and the message contains the clip name
  and timecode.
- A VFR timebase refuses, matching `xml_export.to_xml`'s GAP-2 behaviour.
- Every element the transform doesn't understand is byte-identical in the output.

---

## PHASE 3 — CLI + the duration guard

**One command:**

```
python -m cutdeck.xml_recut sequence.xml mixdown.wav [--dry-run] [--config ...] [--db ...]
```

- Routes the mixdown through the **existing, unmodified** `sequence_mixdown.plan_from_mixdown`
  → `ingest()` → `build_cut_spans(tokens=[], ...)` path. Silence-only; no ASR engine is
  imported anywhere in the call path (assert this in a test, as Phase 2 of the live-sequence
  handoff does).
- Writes `<yourfile>_cut.xml` **beside the input**. The sequence `<name>` inside becomes
  `<original name> — CutDeck`, because that is the string Premiere shows in the bin next to
  the original. The `cd###_p###` round-trip key stays in the clip comments where the
  machinery already looks for it, not in the name a human reads fifty times a day.
- `--dry-run` prints the plan and writes nothing.
- Persists the plan to the DB on the way through, same as the other modes.

**The duration guard — the most important twelve lines in this handoff.** Hard-refuse unless
the mixdown's duration matches the sequence duration declared in the XML (within one frame).

If the editor ever exports the mixdown over an in/out range or the work area instead of the
whole sequence, **every cut lands at the wrong time, uniformly** — and the result is plausible
enough to reach a delivery unnoticed. It is the nastiest silent failure in this design and it
costs one comparison to eliminate.

**Acceptance (`tests/test_cutdeck_xml_recut_cli.py`):**
- `--dry-run` writes no file and prints the span summary.
- A mixdown shorter than the sequence refuses, with both durations in the message.
- No `engines.*` import reachable from the CLI entry point.
- Output filename and internal sequence name match the rules above.

---

## PHASE 4 — mode registration + superseding `jsx_export.py`

- `cutdeck/export_mode.py` gains `MODE_RECUT_SEQUENCE = "recut_sequence"` → `xml_recut.recut`.
  Its docstring must state plainly that this callable takes `(source_xml, plan)` and is
  therefore **not interchangeable** with the other two exporters. The dispatcher exists so
  callers never infer the mode from context; leaving the newest mode out of it defeats that,
  but pretending the signatures match would be a trap of a different kind.
- `config.yaml`'s `cutdeck.mode` accepts the new value; unrecognized values still raise.
- `jsx_export.py` gets a docstring header marking it **superseded**: the XML recut path is the
  supported route for cutting live sequences; the in-place path remains unverified against a
  live Premiere and will not be pursued. Leave the code and its tests in the tree — deleting
  costs a git-archaeology trip if Adobe ever ships a UXP razor; keeping it *without* the
  marker costs the next session another day trying to make it work. **The marker is the value.**

**Acceptance:** `tests/test_cutdeck_mode_selection.py` extended — three modes resolve, an
unknown one raises.

---

## PHASE 5 — human gate (cannot be Claude Code's acceptance)

**The editor imports one generated XML into Premiere and scrubs the cut points on a real
3-angle stack.**

Phases 2–3 prove the invariant and the arithmetic. Neither proves Premiere reads the file the
way we think it does. Until this is done, this mode is **believed correct, not correct** — and
it is recorded in `TODO_LEDGER.md` as *unresolved*, alongside the two human gates already
sitting there unrun. It does not get to become "believed correct" quietly.

---

## Deferred, on purpose

**Word-level cuts (filler / repeat) are phase one-of-two's other half.** Nothing here forecloses
them: same `CutPlan` type, `blade=BLADE_WORD` instead of `BLADE_VAD`. What they additionally
need is an ASR pass over the mixdown (a separate job) and a decision about
`xml_export.py`'s audio-crossfade-at-word-joins behaviour, which has never been verified against
a real Premiere import either. Build and ship silence-only, prove it on real footage, *then*
decide whether word-level cuts on a multicam stack are worth the added blast radius.

---

## Closing invariants

- **Frame math has exactly one authority: `transcribe/timebase.py`.** No module reimplements
  rounding.
- **No new producer of cut decisions.** This handoff adds a consumer of `CutPlan`; `rules.py`
  and the reconciler are untouched.
- **VFR refuses rather than guesses**, matching `xml_export.py`'s GAP-2.
- **Fail loudly, never plausibly.** Strict refusals, the duration guard, and the counted
  marker drops are all the same principle: an error the editor reads costs a minute; a
  wrong-but-plausible sequence costs a delivery.
- **Human-only tasks are called out, not silently omitted:** Phase 0's fixture export and
  Phase 5's real-footage verification both gate this mode's use on anything that matters.
