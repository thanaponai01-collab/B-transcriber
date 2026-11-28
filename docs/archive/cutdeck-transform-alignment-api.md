# CutDeck: Transform, anchor point, and alignment feasibility

Research date: 2026-09-22. Scope: Adobe Premiere UXP documentation and Adobe-owned samples. This is planning research; no Premiere runtime experiment was performed and no application code was changed.

## Recommendation

Add a compact **Transform & Align** section within the existing **Adj & FX** tab, with a possible dedicated tab later. Start with whole selected timeline clips: numeric position/scale/rotation, a nine-point anchor picker with an optional preserve-position behavior, and six alignment buttons relative to the sequence frame. Add selection-relative alignment and distribution only after source dimensions and coordinate conversions have been verified.

This is feasible through the documented component-parameter API plus CutDeck's own geometry calculations. Adobe does not document a turnkey timeline-clip `align`, `distribute`, or rendered-bounds method on the classes inspected. That is a finding about the reviewed public API surface, not proof that no other Adobe API can ever provide it. [VideoClipTrackItem](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocliptrackitem), [Component](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/component).

Premiere already has native alignment controls for text and shapes within graphics. The proposed value is consistent controls for whole timeline clips, not duplicating that narrower graphics workflow. [Adobe: Align objects](https://helpx.adobe.com/premiere/desktop/add-text-images/align-and-distribute-objects/align-objects.html).

## What Adobe documents

| Need | Documented API | Implication |
| --- | --- | --- |
| Selected clips | `Sequence.getSelection()` and `TrackItemSelection.getTrackItems()` | Read selected video/audio items, then restrict operations to eligible video clips. [Sequence](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequence), [selection](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/trackitemselection) |
| Effects and built-in parameters | `VideoClipTrackItem.getComponentChain()`, chain enumeration, `Component.getMatchName()`, `getParamCount()`, `getParam(index)` | Discover actual components and parameters. Parameter indexes are component-defined; the reference does not specify a universal Motion/Transform parameter map. [Clip](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocliptrackitem), [chain](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocomponentchain), [component](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/component) |
| Set values | `ComponentParam.createKeyframe(value)` accepts numbers and `PointF`, among other types; `createSetValueAction(keyframe, safeForPlayback)` changes a non-time-varying parameter | Scalar and point-valued transforms have a documented write path. [ComponentParam](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/componentparam) |
| Animation | `isTimeVarying()`, `getValueAtTime()`, keyframe enumeration/addition/interpolation actions | Animated parameters require an explicit policy; do not silently disable animation to implement alignment. [ComponentParam](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/componentparam) |
| Point values | `PointF(x,y)` and its x/y properties; `PointKeyframe.value` has a `{value: PointF}` shape | Use typed values, then validate actual host behavior. These references do not define Motion or Transform coordinate units. [PointF](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/pointf), [PointKeyframe](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/pointkeyframe) |
| Add an effect | `VideoFilterFactory.getMatchNames()`, `createComponent(matchName)`, then append/insert component actions | Discover the installed Transform effect instead of treating a guessed match name as a documented guarantee. [Factory](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videofilterfactory), [chain](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocomponentchain) |
| Frame target | `Sequence.getFrameSize()` returns `RectF`; `getPlayerPosition()` returns `TickTime` | Sequence frame and current playhead are available. They do not themselves provide a clip's visible bounds. [Sequence](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequence) |
| Source information | `ClipProjectItem.getFootageInterpretation()` exposes pixel aspect information; `Metadata` can read project/XMP metadata | Potential inputs to a geometry adapter, but the reviewed docs do not promise a universal source-width/source-height field for every item type. [ClipProjectItem](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/clipprojectitem), [FootageInterpretation](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/footageinterpretation), [Metadata](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/metadata) |

The key operations above are documented from Premiere 25.6. Actual installed-host support still needs testing. Adobe's sample performs parameter actions within `lockedAccess` and `executeTransaction`; use that pattern for coherent undoable edits. [Adobe sample: keyframe.ts](https://github.com/AdobeDocs/uxp-premiere-pro-samples/blob/main/sample-panels/premiere-api/src/keyframe.ts), [Project reference](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/project).

## Feasibility and boundaries

**Strong candidate after a small probe:** numeric transform controls, batch position changes, resets using verified defaults, and a nine-point anchor picker. This is an engineering inference from the read/write APIs, not a guarantee that every Motion/Transform parameter behaves identically across clips and versions.

**Feasible with a geometry adapter:** align left/center/right/top/middle/bottom against the sequence or selected clip bounds; distribute centers or equal gaps. Calculate transformed source-rectangle corners and an axis-aligned enclosing rectangle, then write position deltas. Equal-gap distribution and equal-center distribution must be distinct options. Require at least three clips for useful distribution.

**Do not promise in the first version:** alignment to the visible opaque artwork of transparent images, glyph bounds inside graphics, arbitrary MOGRT internals, or exact final bounds after masks, crop, nested effect stacks, skew, or perspective. No general rendered-alpha/content-bounds API was found in the reviewed classes. The documented `Media` API concerns timing, not image bounds. [Media](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/media), [VideoClipTrackItem](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocliptrackitem).

For ordinary 2D transforms, preserving the on-screen picture when moving an anchor requires a compensating position delta. In a validated common coordinate space, the mathematical relation is `P_new = P_old + R*S*(A_new - A_old)`. This is geometry reasoning, not an Adobe-documented conversion formula; pixel aspect, normalization, effect order, and additional transforms can change the required adapter.

## Runtime gates before implementation

1. Enumerate Motion and Transform on an ordinary clip and adjustment layer; capture component match names, parameter indexes, display names, types, values, animation state, and installed Premiere version.
2. Read/write a point with the documented `PointF` path, read it back, verify the Effect Controls UI and Program Monitor, and undo. Repeat for position and anchor independently; do not assume pixel units or that `[0.5,0.5]` means the same thing in both effects.
3. Verify coordinate mappings for matching/mismatched source and sequence sizes, non-square pixels, and fit/scale-to-frame workflows. Establish a reliable dimension source for each supported media type; fail clearly when unknown.
4. Verify nine anchor targets at 100% and nonuniform scale, and at 0/90/arbitrary rotation, with preserve-position on/off.
5. Decide how animated clips behave: initially skip with explanation, or explicitly set a current-time keyframe after verifying the parameter time domain. Do not infer that sequence playhead time can be passed unchanged.
6. Verify frame and selection alignment with multiple differently sized clips, then center distribution and equal gaps. Check undo restores every affected parameter.

## CutDeck integration observations

Repository inspection by the coordinating agent found one manifest panel with **Cut & Sync** and **Adj & FX** internal tabs. Existing `effects.js` handles effect parameter capture/restoration, including point-value wrappers, and refetches parameters after effect insertion. `capabilityProbe.js` already probes Motion. Reuse these foundations, but treat comments about observed normalized values as host observations, not universal Adobe contracts. Keep geometry and host parameter discovery separate from UI event handlers.

The documented clip selection getter is `getIsSelected()`. Any existing fallback using `isSelected` should be checked against the installed host before reuse; this research did not modify it. [VideoClipTrackItem](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocliptrackitem).
