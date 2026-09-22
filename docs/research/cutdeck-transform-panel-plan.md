# CutDeck Transform & Align — API verification + new-panel plan

Date: 2026-09-22. Companion to [cutdeck-transform-alignment-api.md](cutdeck-transform-alignment-api.md).

Three parts: (1) what survived verification against Adobe's own sources, (2) the plan for a
**separate panel** rather than the in-tab section the research doc recommended, (3) prior art —
Easify 4 — and what the CEP/ExtendScript stack it uses does and does not buy.

No Premiere runtime experiment has been performed — every "unknown" below is still unknown.

**Build status (2026-09-22): Phases 0 and 0a are shipped** (commits `412887c`, `5644394`).
Phase 0's probe and the second panel exist and are tested off-host; what does *not* exist yet
are the probe's **answers**, which require running it in Premiere. Phase 1 is blocked on that.

---

## Part 1 — Verification

### Sources used

| Source | Why |
| --- | --- |
| `developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/*` | The pages the research doc cites, read directly |
| `@adobe/premierepro@26.2.1/src/premierepro.d.ts` (4388 lines, via jsDelivr) | Adobe's **complete** declared API surface for the release line `uxp/cutdeck/manifest.json` pins (`minVersion: 26.2.0`) — this is what makes "not documented" a checkable claim instead of a reading-coverage claim |
| `uxp/cutdeck/timeline/effects.js`, `uxp/cutdeck/capabilityProbe.js` | Runtime observations already captured on the installed build |

### Verdict

**The research doc's central claim holds, and is now stronger than it was.** Its load-bearing
sentence — "Adobe does not document a turnkey timeline-clip `align`, `distribute`, or
rendered-bounds method on the classes inspected" — was hedged to the classes inspected. A grep
of the entire declaration set for `align|distribute|bounds|opaque` returns only `TickTime`'s
`alignToFrame()` / `alignToNearestFrame()`, a `SnapEvent` doc comment, and the Apache licence
header. There is no clip-geometry API at any version in this line. The hedge can be dropped.

Every method the doc names exists with the signature it claims. Confirmed individually:
`VideoClipTrackItem.getComponentChain()` / `getIsSelected()`; `Sequence.getSelection()` /
`getFrameSize(): Promise<RectF>` / `getPlayerPosition()`; `TrackItemSelection.getTrackItems()`;
`Component.getMatchName()` / `getParamCount()` / `getParam(i)` / `getDisplayName()`;
`ComponentParam.createKeyframe(number|string|boolean|PointF|Color)` /
`createSetValueAction(kf, safeForPlayback?)` / `isTimeVarying()` / `getValueAtTime(TickTime)` /
`getStartValue()`; `VideoComponentChain.getComponentCount()` / `getComponentAtIndex()` /
`createInsertComponentAction()` / `createAppendComponentAction()` / `createRemoveComponentAction()`;
`VideoFilterFactory.getMatchNames()` / `createComponent(matchName)` (static);
`PointF(x?, y?)` with read/write `x` and `y`; `ClipProjectItem.getFootageInterpretation()`.

### Corrections and additions

Six things the research doc got wrong, missed, or left as an unknown that is in fact documented.
These change the plan, not just the prose.

**1. `RectF` has no origin — it is a size, not a rectangle.**

```ts
export declare type RectF = { new (): RectF; (): RectF; width: number; height: number; };
```

The doc's "axis-aligned enclosing rectangle" and "transformed source-rectangle corners" cannot be
`RectF`. The geometry adapter needs CutDeck's own `{x, y, width, height}` type. `RectF` appears
only as a return value (`getFrameSize`, `getVideoFrameRect`, `getPreviewFrameRect`).

**2. Sequence pixel aspect ratio *is* documented — and it is a string.**

The doc routed pixel aspect through `ClipProjectItem.getFootageInterpretation()` only.
`SequenceSettings` exposes it directly: `getVideoPixelAspectRatio(): Promise<string>`. Note the
type — parse it, don't arithmetic on it. `SequenceSettings.getVideoFrameRect(): Promise<RectF>`
is a second, equivalent route to frame size alongside `Sequence.getFrameSize()`;
`capabilityProbe.js` already uses the `getSettings()` route.

**3. The `{value: {value: X}}` double wrapper is documented, not merely observed.**

`effects.js` records discovering this at runtime on 2026-09-22 and calls it a host observation.
It is in Adobe's own types:

```ts
export declare type Keyframe = { value: { value: string | number | boolean | Color | PointF }; position: TickTime; ... };
export declare type PointKeyframe = { value: { value: PointF }; ... };
```

The unwrap in `captureEffectFromTrackItem` is a contract, safe to depend on. The doc's line 21
claim that `PointKeyframe.value` has a `{value: PointF}` shape is correct and applies to the
generic `Keyframe` too.

**4. `VideoFilterComponent` is declared as the empty type `{}`.**

`effects.js` found at runtime that `VideoFilterFactory.createComponent()`'s return value has no
`getParam` and that the insert must commit before a param-capable `Component` can be fetched back.
That is the documented shape, not a build quirk — `export declare type VideoFilterComponent = {};`.
The insert-then-refetch two-transaction pattern is the only available one and will apply
unchanged if Transform ever has to be *added* to a clip that lacks it.

**5. `isSelected` does not exist at any version in this line — and CutDeck relies on it.**

The doc flags this as "should be checked against the installed host". It is checkable and settled:
`getIsSelected(): Promise<boolean>` is the only form (two declarations, `VideoClipTrackItem` and
`AudioClipTrackItem`); the string `isSelected` appears nowhere. `effects.js`'s
`isTrackItemSelected()` tries `it.isSelected()` as a function, then `it.isSelected`, then
`it.selected`, and never tries `getIsSelected()` — so its whole per-track fallback path returns
`false` for every item when `seq.getSelection()` is the thing that failed. Pre-existing, outside
this work, flagged separately.

**6. Adobe's `keyframe.ts` sample gives no PointF precedent.**

The doc cites it, correctly, for the `lockedAccess` + `executeTransaction` + `createSetValueAction`
shape. It does not construct a `PointF` anywhere. So the *point-valued write path* — the one this
whole feature stands on — has no Adobe sample behind it, only a type signature. It is gate 2 below
for a reason.

### What remains genuinely unknown

Unchanged from the research doc, and confirmed as unknowable from documentation:

- **No parameter map.** Adobe documents no Motion or Transform parameter indices, names, or units.
  The only match names anywhere in the declarations are the doc-comment examples `PR.ADBE Solarize`
  and `AE.ADBE Mosaic`. Motion and Transform are never named.
- **No units.** Nothing states whether Position and Anchor Point are pixels or normalized, or
  whether they share a space. `effects.js`'s header records a Transform point param logging as
  `[0.5, 0.5]`, which *suggests* normalized — but that was an incidental capture of whatever was
  selected, not a controlled probe, and it says nothing about Motion.
- **No *direct* source dimensions.** `ProjectItem` has none; `ClipProjectItem` has none;
  `FootageInterpretation` exposes pixel aspect ratio and frame rate but not width or height.
  `createSetScaleToFrameSizeAction()` exists but is a setter with no matching getter — which
  `capabilityProbe.js` already ran into and worked around by reading live Motion values instead.
  **But there is an indirect route — see Part 3.** An earlier draft of this document called source
  dimensions "blocked on inference, not on a probe". That was wrong, and Part 3 corrects it.

The research doc's six runtime gates all stand. Gate 3 ("establish a reliable dimension source for
each supported media type") is the weakest — but Part 3 identifies a candidate source
(`Metadata.getProjectColumnsMetadata`) that makes it a probe question rather than a dead end.

---

## Part 2 — New panel plan

### The one deliberate departure

The research doc recommends a compact section inside the existing **Adj & FX** tab. This plan
builds a **second panel entrypoint** instead, as asked. The reasons it is defensible:

- **Space.** Adj & FX is already an AL action card plus a 3×3 quick-effect grid inside a 340px
  docked width. Transform needs numeric position/scale/rotation fields, a nine-point picker, and
  six align buttons — that is not a "compact section" at that width.
- **Where the work happens.** Transform work happens next to Effect Controls and the Program
  Monitor. A separate panel can be docked there; a tab inside CutDeck cannot be, without dragging
  the cut/sync workflow along with it.
- **Blast radius.** A separate document cannot break Cut & Sync or the quick-effect grid. Given
  that the parameter units are unknown and gates 2–4 may come back unfavourably, a feature that
  can be shipped dark and abandoned without touching shipped UI is worth the extra entrypoint.

Costs, stated plainly: two HTML documents to keep themed, a second render/bind seam, and
cross-panel state (settings, captured presets) that this plan does **not** assume is shared —
see gate 0.

### Manifest shape — **corrected 2026-09-22, gate 0a answered**

An earlier draft of this plan proposed a second HTML document with its own per-entrypoint
`"main": "align.html"`. **There is no such field.** Adobe's manifest schema allows exactly
`type`, `id`, `label`, `description`, `shortcut`, `icon`, `minimumSize`, `maximumSize`,
`preferredDockedSize` and `preferredFloatingSize` on an entrypoint; `main` is a single top-level
property. Building the planned shape would have shipped a panel that opened blank.

**The real mechanism:** every panel in a plugin shares ONE document. Extra panels are containers
inside it, moved into their own root by the `show()` hook of `entrypoints.setup()`:

```js
entrypoints.setup({
  panels: {
    "cutdeck.panel": { show() {} },                       // content already static in the document
    "cutdeck.align.panel": { show(rootNode) { alignPanel.mount(rootNode); } },
  },
});
```

Two consequences that changed the build:

- **`hide()` and `destroy()` are documented by Adobe as "not working as expected yet" in
  Premiere.** Nothing may depend on them firing. No such hooks are registered; the container
  stays where `show()` put it, and that is correct behavior rather than a leak.
- **Gate 0a's localStorage question dissolves.** One document means one JS context, so the two
  panels already share `localStorage`, module instances and the id namespace. The id namespace
  being shared is the new risk, and is covered by a collision test.

Multi-panel plugins also need `"requiredPermissions": { "ipc": { "enablePluginCommunication": true } }`.

### File layout

Respects the repo's existing boundaries: `core/panel.js` is the only file allowed to touch the
DOM, geometry stays out of event handlers, and host discovery stays out of geometry.

```
uxp/cutdeck/
  index.html                  EXTENDED — #view-transform, the transform panel's container,
                              shipped `hidden` so it never flashes inside Cut & Sync. Not a
                              second document: there is only ever one (see above).
  main.js                     EXTENDED — its own small alignState + actAlign(), and the guarded
                              entrypoints.setup() that registers both panels.
  core/
    alignPanel.js             DONE — the DOM seam for the transform panel. render/bind, plus
                              mount(rootNode) which relocates the container into the root
                              Premiere creates. Mirrored from panel/core/ by
                              scripts/sync_panel_core.py like its sibling.
  transform/
    params.js                 new — HOST DISCOVERY ONLY. Finds the Motion/Transform component on a
                              track item and maps semantic names (position, scale, anchor, rotation)
                              to real param indices for THIS build. Returns nulls, never guesses.
                              No geometry, no DOM.
    geometry.js               new — PURE. Rect/point math, nine anchor targets, the anchor-move
                              compensation, align and distribute solving. No `require("premierepro")`,
                              so it is unit-testable off-host.
    apply.js                  new — writes values via createKeyframe/createSetValueAction inside
                              lockedAccess + executeTransaction. Lifted from effects.js's proven
                              two-phase pattern. No geometry, no DOM.
  capabilityProbe.js          EXTENDED — one new read-only probe (below). Not a new file: this is
                              where every "ask the build, don't guess" question in this plugin lives.
```

`transform/params.js` must not import `timeline/effects.js` and vice versa. What they genuinely
share — selection lookup, the fixed-component skip list, the `{value:{value:X}}` unwrap, the
`runInTransaction` helper — should be lifted out of `effects.js` into a small
`timeline/componentAccess.js` at the moment the second consumer appears, not duplicated and not
imported across the seam. That lift is part of Phase 1, not a later cleanup.

### Phase 0 — probe first, build nothing

A single new read-only probe in `capabilityProbe.js`, `probeTransformParams(ppro)`, exposed as a
menu item next to "Check Effect Chain". It reports, for each selected track item:

- every component's index, display name and **match name** — the Motion and Transform match names
  this build actually uses, which no Adobe source states;
- for each param: index, `displayName`, `isTimeVarying()`, and `getStartValue()` unwrapped through
  the documented double wrapper, with the **raw JSON** alongside the unwrapped value so point
  shape (`{x,y}` vs array) is visible rather than inferred;
- `Sequence.getFrameSize()`, `SequenceSettings.getVideoFrameRect()`,
  `getVideoPixelAspectRatio()` (string — reported raw), and the installed Premiere version;
- whether the item is an adjustment layer, and whether `getIsSelected()` exists on it.

Run it on: a clip whose source matches the sequence, a clip whose source does not, a clip with
non-square pixels, an adjustment layer, and a graphic. **Nothing in Phase 1 is written until this
has been run on at least the first two.** This is the same discipline `timelineRange.js`'s
`OUT_CONVENTION` was held to, and it is cheap: the probe is read-only and safe in a real project.

### Phase gates

| Phase | Ships | Blocked until |
| --- | --- | --- |
| **0** | ✅ **SHIPPED** `probeTransformParams` + `formatTransformReport`, wired to the ⋮ menu and to the transform panel's own button | — |
| **0a** | ✅ **SHIPPED** second entrypoint `cutdeck.align.panel`, `#view-transform` container, `core/alignPanel.js` seam, guarded `entrypoints.setup()` | — (was independent of 0; both gate questions are now answered above — no per-entrypoint `main` exists, and one shared document makes `localStorage` sharing moot) |
| **1** | ⬅ **NEXT** Read-only display of the selected clip's position/scale/rotation/anchor, live | **Phase 0 must be RUN in Premiere on ≥2 clip shapes.** The code ships; the answers do not exist yet. Proves param mapping before any write |
| **2** | Numeric edit of those four, one clip at a time, with undo | Research-doc gate 2 — write a point, read it back, confirm in Effect Controls *and* Program Monitor, undo |
| **3** | Nine-point anchor picker, preserve-position off | Phase 2. `P_new = P_old + R·S·(A_new − A_old)` is geometry reasoning, **not** an Adobe formula — it is a hypothesis Phase 3 tests, and it may be wrong if Position and Anchor use different spaces |
| **4** | Preserve-position on; batch across a multi-clip selection | Gate 4 — nine targets × {100%, nonuniform scale} × {0°, 90°, arbitrary} |
| **5** | Align to sequence frame: left/centre/right/top/middle/bottom | Gate 3 **and** a decided answer for source dimensions. Expect "refuse clearly when unknown" |
| **6** | Align to selection bounds; distribute centres; distribute equal gaps (distinct commands, ≥3 clips) | Phase 5 |

Animated params (`isTimeVarying() === true`) are **skipped with a visible explanation** from
Phase 1 onward, in every phase. Setting a current-time keyframe requires knowing the parameter's
time domain, which `effects.js` deliberately sidestepped by standardizing on `getStartValue()` and
which this feature does not resolve. Silently flattening a user's animation to implement alignment
is the one failure mode that would make the panel untrustworthy.

### Definition of done for Phase 1

The panel shows the selected clip's four transform values; they match Effect Controls digit for
digit on a matched-source clip, a mismatched-source clip, and an adjustment layer; changing the
selection updates them; a clip with no readable Transform shows "unavailable" rather than zeros.

### Known risks

- **Units unknown until Phase 0.** If Position and Anchor turn out to be in different spaces, the
  anchor compensation in Phase 3 is wrong and Phases 3–6 need re-planning. This is the single
  largest unknown and Phase 0 is cheap, so it is the first thing done.
- **Source dimensions have no read path.** Phase 5's frame alignment needs a clip's rendered extent.
  With no documented source width/height, the honest v1 is: align using the sequence frame and the
  clip's own scale, and refuse when the media type does not yield dimensions.
- **Two panels, one settings store.** Unverified whether `localStorage` is shared across
  entrypoints in one plugin. Gate 0a answers it; until then the new panel keeps its own key.
- **Selection reliability.** `seq.getSelection()` is already proven unreliable on this build
  (`adjustmentLayer.js`, `effects.js`). The new panel must reuse the existing fallback path, not
  write a third one — and that fallback has a bug (Part 1, item 5) that should be fixed first.

---

## Part 3 — Prior art: Easify 4, and what CEP actually buys

Prompted by [aescripts.com/easify](https://aescripts.com/easify/). Easify 4 (Leyero) is an
animation toolkit for **both** Premiere Pro and After Effects, listing compatibility with Premiere
Pro 2024–2027, and its Pro tier ships **Align & Distribute** for Premiere. So a shipping commercial
product already does the thing Part 2 plans.

### Is it CEP or UXP?

**CEP — strong inference, not proven.** The product page never names its stack. The evidence:
Premiere Pro **2024** is version 24.x, and Adobe's own UXP introduction page states Premiere UXP
support at **25.6**. A product supporting 2024 cannot be UXP-only. Adobe has confirmed CEP will
stop working in a future Premiere and that UXP became standard release in Premiere 2026, so
Easify's Premiere side is a CEP extension either wholly or as the compatibility path for older
hosts. Nothing here was verified by inspecting the package.

### What CEP/ExtendScript actually gives that UXP does not

Checked against the Premiere ExtendScript reference (`docsforadobe/premiere-scripting-guide`,
`docs/sequence/component.md`, `docs/sequence/componentparam.md`, `docs/item/projectitem.md`).
The intuition that CEP is simply "more powerful, so that's how they did align" does **not** survive
contact with the API.

**Where the two stacks are the same — and both are equally awkward:**

- ExtendScript reaches params as `component.properties[index]` — **also index-based**, with a
  **localized, read-only `displayName`**, exactly like UXP's `getParam(i)` + `.displayName`. CEP
  does not solve the "no parameter map" problem. The ExtendScript docs even attach a note about
  comparing ZString dictionary files across locales to recover keys, which independently confirms
  the warning already written into `timeline/effects.js`: matching components by display name is
  fragile, match name is the stable identifier. **Both stacks require the Phase 0 probe.**
- **Neither stack has rendered bounds.** There is no Premiere equivalent of After Effects'
  `Layer.sourceRectAtTime()` in ExtendScript either. Easify's Premiere align faces exactly the
  geometry problem Part 1 identified. Its AE align can be genuinely content-aware; its Premiere
  align cannot be, by the same constraint.

**Where ExtendScript is genuinely ahead:**

- **Writes are trivial.** `param.setValue(value, updateUI)` — synchronous, a plain value, no
  keyframe object, no `Action`, no transaction. UXP needs
  `createKeyframe` → `createSetValueAction` → `executeTransaction` → `lockedAccess`. UXP's version
  is more ceremony but buys proper undo grouping, so this is a wash, not a gap.
- **Keyframes and interpolation are far richer**, and this is the real gap:
  `setValueAtKey(time, value, updateUI)`, `getKeys()`, `addKey`, `removeKeyRange`, and above all
  `setInterpolationTypeAtKey(time, type)` with a documented nine-value enum including
  `KF_Interp_Mode_Bezier`. UXP's `Keyframe` exposes only `getTemporalInterpolationMode()` /
  `setTemporalInterpolationMode(number)` against no documented enum.

That last point explains Easify rather than threatening this plan. **Easify is fundamentally an
easing and graph-editor product** — Bézier curves, speed graph, bounce/elastic, stagger. That core
is built directly on the interpolation API UXP has barely exposed, and would be hard to rebuild on
UXP today. **Align & Distribute is a Pro-tier side feature**, and it is the one part of Easify that
needs none of that advantage. CEP is not why they can align. They align with the same arithmetic
Part 2 plans, on an API of comparable poverty.

### The correction this turned up

Chasing how a CEP align tool gets source dimensions found the answer, and it applies to **UXP too**:

```ts
Metadata.getProjectColumnsMetadata(projectItem: ProjectItem): Promise<string>
```

ExtendScript's identically-named `projectItem.getProjectColumnsMetadata()` is documented as
returning "a JSON string ... all the metadata from the current project view layout", parsed into
one object per Project-panel column with `ColumnName`, `ColumnValue`, `ColumnID`, `ColumnPath` —
`ColumnID` values look like `"Column.Intrinsic.Name"`. The Project panel's **Video Info** column
carries the source resolution. This is the standard route Premiere CEP tools use for source
dimensions, and **UXP exposes the same method** (alongside `getProjectMetadata` and
`getXMPMetadata`).

Confidence, stated honestly: the **method** is documented in both stacks (proven). The **presence
of a resolution column in its output** is documented in neither — it is inference from the
ExtendScript column model (suspected). So this does not make source dimensions solved; it moves
them from "no read path exists" to **one more Phase 0 probe question**, which is a large downgrade
in risk for Phase 5.

Two caveats to test, not assume:

1. ExtendScript's wording is "the current project **view layout**" — the output may contain only
   columns the user currently has visible in the Project panel. A tool that silently depends on a
   user-configurable panel setting is a support burden. The probe must check with the Video Info
   column both shown and hidden.
2. `ColumnValue` is display text (e.g. `"1920 x 1080"`), so it needs parsing and locale-tolerant
   handling, and it describes the **source media**, not the clip's rendered extent after scale,
   crop or masks. It feeds the geometry adapter; it is not a bounds API.

**Phase 0 gains one question:** dump `Metadata.getProjectColumnsMetadata()` for each probed clip's
project item verbatim, and record whether any column carries source resolution and under what
`ColumnID`.

### Two notes for the record

- Adobe's own [ExtendScript migration guide](https://developer.adobe.com/premiere-pro/uxp/resources/migration-guides/extendscript/)
  for Premiere UXP is, as of this date, an unwritten stub whose body reads "Stuff goes here...".
  There is no official CEP→UXP mapping table to lean on.
- This is a crowded niche. The same author sells **Anchor Pro 2** ($29, "solves all your Anchor
  Point needs in Premiere Pro & After Effects"), and C2 Plugins' **Sniper** ($59.90) bundles an
  anchor point tool. If the goal is the daily recut workflow rather than owning the code, buying is
  a legitimate option and cheaper than Phases 0–6. If the goal is CutDeck doing it natively,
  alongside its own AL and quick-effect gestures, the plan stands — none of these integrate with
  that.
