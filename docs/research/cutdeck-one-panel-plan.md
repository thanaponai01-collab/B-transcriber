# CutDeck one panel — build plan

Date: 2026-10-26. Status: steps 0–7 **built** (726/726 panel tests); step 8, the live check in Premiere, not done.

Goal: fold the **CutDeck** and **CutDeck Transform** panels into one CutDeck panel with four
tabs — **Cut, FX, Transform, Align** — one shared status bar, and no brand row. The ClubFriday
panel was a demo and is removed from the plugin.

Design source: the v4 mockup agreed in chat on 2026-10-26 (summarized under "Target layout").

---

## Decisions already made

| Topic | Decision |
| --- | --- |
| Tabs | Cut, FX, Transform, Align, in that order. Icon plus short label. Last tab used is remembered per user. |
| Brand row | Removed. The panel tab already says "CutDeck". Helper dot and ⋯ menu sit on the tab row. |
| Sequence card and resume banner | Shown on the Cut tab only. |
| FX | Icon-only cards (as now), preset grid, one-line gesture hint. The long "Tools and Shortcuts Guide" in Settings is removed. |
| Transform | Laid out like Premiere's Effect Controls: fx Motion (Position, Scale, Scale Width, Uniform Scale, Rotation, Anchor Point, Anti-flicker Filter, then Crop Left/Top/Right/Bottom) and fx Opacity (Opacity, Blend Mode). Foldable blocks, header reset, per-row reset. No keyframe stopwatches. |
| Align | One frame drawing. Its four edges and two center lines are the six align actions (hover lights the line, click aligns). Nine dots on the drawn clip set the anchor. Frame / Selection / Group switch above, one row of four Distribute buttons below. The drawing is fixed; it does not show the clip's live position. Corners are not clickable. |
| Settings | Stays a sheet opened from the ⋯ menu. |
| Probes | Leave the top level of the ⋯ menu; one "Probes" item expands them in place. |
| Busy | Every tab stays clickable while a job runs. |
| Text-layer picker | Keep today's behavior (`#align-text-layer-switcher`, `onSelectTextLayer`): hidden unless a Graphic with several text layers is selected. Placed under the clip line on the Transform tab. Not otherwise redesigned. |
| ClubFriday panel | **Removed** from the plugin (answered 2026-10-26). The Python `clubfriday/` server and quote editor stay; only the Premiere panel side goes. |
| Workspaces | Accepted: "CutDeck Transform" and "ClubFriday" leave Window > UXP Plugins, and saved workspaces that dock them lose those slots. |

---

## UXP limits the build must respect

Each one is sourced; none needs a live probe.

| Limit | Source | Rule for this build |
| --- | --- | --- |
| CSS Grid and `aspect-ratio` gave 0×0 tiles in this UXP build | comment on `.fx-preset-grid`, `uxp/cutdeck/core/theme.css` (confirmed live with getBoundingClientRect) | Flex only. |
| `gap` on a wrapped flex row is subtracted twice | same comment | Margins for spacing on wrapped rows. |
| CSS transitions and animations are not supported | `reference/adobe/docs/uxp-api/known-issues.md`, CSS section | No motion; the existing `transition` rules are inert, leave them. |
| Text fields always render above other content | same file, `z-index` note | The Settings sheet and ⋯ menu must not be expected to cover text inputs; hide the active view while the sheet is open (today's behavior). |
| Percent is not in the documented unit list | `reference-css/general/units.md` | Position the Align drawing's lines and dots in px computed at render. |
| `hide()` / `destroy()` don't fire | header of `core/alignPanel.js` | Polling can't key off panel visibility; key it off the active tab instead. |

APIs the build relies on, all in `reference/adobe/api/uxp.txt` or already used live:
`HTMLElement.clientWidth` (declared), `:hover`, `position: absolute` and `z-index` (⋯ menu,
Settings overlay), pointer events (drag-to-scrub in `core/alignPanel.js`). Sequence frame size
comes from the existing `transformParams.readSequenceFrameSize` (snapshot field `seqFrame`).
**No new Premiere API is needed**, so `tools/adobe/check-api.mjs` should not change.

---

## Target layout

```
[●] [ Cut | FX | Transform | Align ] [⋯]
---------------------------------------------
 Cut:       (resume banner) · sequence card · Sync · Rough cut (audio, Speech/Silence)
 FX:        AL / Matte / Hold icon cards · preset grid · hint line
 Transform: Sequence › clip line · fx Motion (incl. Crop) · fx Opacity · hint line
 Align:     Frame|Selection|Group · frame drawing (6 lines, 9 anchor dots) · Distribute ×4
---------------------------------------------
 status bar (one)
```

---

## Steps

Each step ends green on `node --test tests/*.cjs` before the next starts.

### 0. Remove the ClubFriday panel

- `manifest.json`: delete the `cutdeck.clubfriday.panel` entrypoint, the
  `http://127.0.0.1:8010` network domain and the `"http"` launchProcess scheme (both used only
  by the quote-editor button; checked with grep: the only `openExternal` is that button).
  Keep `.vbs` / `.cmd`; the helper start uses them.
- `main.js`: delete the `cfPanel` / `cf` wiring and the ClubFriday show() hook.
- `index.html`: delete `#view-clubfriday`.
- Delete `core/clubFridayPanel.js`, `features/clubFriday.js` and
  `tests/clubfriday_panel.test.cjs`.
- Tests that name it: drop `core/clubFridayPanel.js` from `UI_SEAM_FILES` in
  `tests/panel_ui_contract.test.cjs`; `tests/cutdeck_rpc.test.cjs` line ~301 expects the 8010
  domain, change it to the helper URL only; `tests/cutdeck_align_panel.test.cjs` entrypoint list
  is rewritten in step 1.
- Docs: `docs/architecture.md` (panel → server edge), `features/clubfriday.md` (panel trace),
  `VERIFY.md` line ~86, `clubfriday/README.md` (steps that say to use the Premiere panel). The
  server and its own tests are untouched.
- Check: `grep -ri "clubfriday\|8010" uxp/cutdeck tests/*.cjs` returns nothing (built `.ccx`
  under `package/` excepted); all `.cjs` tests green; `python -m pytest` for `clubfriday/` tests
  unchanged and green.

### 1. One entrypoint for CutDeck

- `uxp/cutdeck/manifest.json`: delete the `cutdeck.align.panel` entrypoint. Raise
  `cutdeck.panel` `minimumSize.height` if the Transform tab needs it (decide in step 4 from the
  real row count; start at 420).
- `uxp/cutdeck/main.js`: drop the `"cutdeck.align.panel"` show() hook. Start align polling at
  startup instead (step 3 gates it).
- `core/alignPanel.js`: `mount()` is no longer needed; `#view-transform` lives in the main flow.
  Remove `mount`/`unmount` and the "ships hidden" logic that only existed for the move.
- Tests: `tests/cutdeck_align_panel.test.cjs` asserts three entrypoints, the
  `<div id="view-transform" hidden>` markup and the align show() hook; rewrite those assertions
  to the new shape (one entrypoint, `cutdeck.panel`; transform view in the main flow).
- Check: the test file is red before the edit and green after; the manifest test names exactly
  the entrypoints left.

### 2. Tab row and four views

- `index.html`: remove the `.brand` text; put the status dot, a four-tab row
  (`tab-edit`, `tab-adj`, new `tab-transform`, new `tab-align`) and the ⋯ button in one flex row.
  Keep the existing ids so `tests/panel_ui_contract.test.cjs`' id lists only grow.
- Move `#job-banner` and `#seq-card` inside `#view-edit`.
- Split the current transform markup: the field rows stay in `#view-transform`; the anchor grid,
  align and distribute blocks move to a new `#view-align` (rebuilt in step 5).
- `core/panel.js` `renderTabs` / `bindTabs`: four values (`edit`, `adj`, `transform`, `align`).
- `main.js`: initial `tab` read from storage (`cutdeck.tab`, try/catch), written on change.
- Check: a panel-contract test that clicking each tab shows exactly one view; tab survives a
  reload of state from storage.

### 3. Polling follows the tab, one status bar

- `features/align.js` already skips a poll when `isMounted()` is false. Pass
  `isMounted: () => ["transform", "align"].includes(mainCtl.state.tab)` from `main.js`, so the
  transform poll runs only while one of those tabs is showing. Force one refresh on entering
  either tab.
- Status: keep both controllers. The bottom bar shows `#status` (main controller) on Cut and FX,
  and `#align-status` on Transform and Align. While the main controller is busy, the bar shows
  the main status on every tab, prefixed with the job's tab ("Cut: Rough cut… 40%"), and the Cut
  tab carries a busy dot. This matches today's rule that transform polling pauses while the main
  controller is busy (`isMainBusy`).
- Check: test that the poll does not run on Cut/FX and runs on Transform/Align
  (`tests/cutdeck_align_poll_rate.test.cjs` is the place); test which status shows per tab and
  while busy.

### 4. Transform tab as Effect Controls

- Markup and CSS only; the field ids (`align-position-x` … `align-blend-mode`), scrub, commit and
  per-row reset handlers are unchanged.
- Two foldable blocks, "fx Motion" and "fx Opacity". Crop rows move to the end of Motion under a
  small "Crop" divider. Fold state is UI-only, kept in storage. The ▸/▾ arrow swaps glyphs (no
  rotation animation).
- Block header reset buttons call the existing `onResetField` for each row of that block.
- "Sequence › clip name" line plus refresh at the top (the current clip line, restyled).
- Flex rows: label flexes, values fixed width, reset at the end.
- Check: existing transform tests (`cutdeck_transform_*`, `cutdeck_input_commit`,
  `cutdeck_align_panel`) stay green with no assertion changes beyond markup location; new test
  for the block reset calling `onResetField` once per row.

### 5. Align tab drawing

- `#view-align`: Frame / Selection / Group pills (existing `data-align-to`), the drawing, one
  hint line, then the Distribute row (existing `data-act="distribute"` values).
- The drawing is a `position: relative` box. In render: width = `clientWidth` of the view; height
  = width × seqFrame.height / seqFrame.width, capped at 200 px (a 9:16 frame gets narrower, not
  taller). Six line hit-areas (12 px thick, `data-act="align-edge"` with the existing
  `data-align` values left / hcenter / right / top / vcenter / bottom) and a centered clip box
  with nine dots (`data-act="align-anchor"`, existing `data-anchor` values). All placed in px.
- Line highlight is CSS `:hover` only. Results go to the status bar.
- No new intents: the drawing binds to `onAlign`, `onAnchor`, `onDistribute` as the old buttons
  did. The old button markup is removed.
- No `seqFrame` yet (no sequence) → draw 16:9 and show the existing "No sequence open" text.
- Check: test that each line and dot dispatches the same intent and value the old button did;
  test the height for 1920×1080, 1080×1920 and a missing frame.

### 6. FX tab, Settings, ⋯ menu

- FX: add the one-line hint under the preset grid. The cards are already icon-only.
- Settings: delete the "Tools and Shortcuts Guide" block.
- ⋯ menu: Settings, Copy status report, Probes (expands the probe items in place), Reload
  panel. Probe items keep their ids and `data-probe` values, so `cutdeck_feature_probes` tests
  hold.
- Check: probe ids still bound (`panel_ui_contract`), Settings markup has no help box.

### 7. Docs and checks

- `FEATURES.md` / `features/cutdeck.md`: one panel, four tabs; remove "CutDeck Transform panel".
- `docs/arch-design-panel-ui.md` and the `core/alignPanel.js` header: the second-panel rationale
  becomes history; state that both seams now render into one panel.
- `VERIFY.md`: add the new tests with a fail-proof note each.
- `work/cutdeck-history.md`: one entry.
- Full run: `node --test tests/*.cjs` (includes `node tools/adobe/check-api.mjs`).

### 8. Live check in Premiere (not covered by tests)

Install the rebuilt `.ccx`, then on a real project:

1. Only one CutDeck panel is listed; it opens on the last tab used.
2. Each tab renders at the 300 px minimum width with no clipped controls.
3. Transform values follow a clip click and an Effect Controls drag only while Transform or
   Align is showing.
4. Start a rough cut, switch to Align: the status bar shows the job, the Cut tab shows the dot.
5. Align drawing: each line and dot moves the clip as the old buttons did, on a 16:9 and a 9:16
   sequence.
6. Settings sheet and ⋯ menu open over every tab.

Record results in `work/cutdeck-history.md`. No new `docs/PREMIERE_FACTS.md` rows are expected,
since no new Premiere API is used.

---

## Out of scope

The `clubfriday/` server and quote editor, keyframes, a live clip position in the Align drawing, corner
(two-axis) align, and any new Premiere API.
