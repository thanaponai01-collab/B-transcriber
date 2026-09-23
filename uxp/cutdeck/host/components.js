// Shared low-level Premiere component-chain access and keyframe value unwrap.
// Moved to host/components.js as part of Move 5 (issue #53, docs/arch-design-cutdeck-panel.md).

// Every plain video clip and Adjustment Layer carries these fixed effects in Premiere's own
// Effect Controls panel — never something a user added. Matched by display name because this
// build's real matchNames were not confirmed when effects.js was written (Adobe's own sample
// only shows a NEW effect landing at chain index 2 on a plain clip, which implies but does not
// document two fixed entries before it). Run the "Check Effect Chain" probe (capabilityProbe.js)
// against a plain, effect-free Adjustment Layer to get the real matchNames for this build, then
// prefer matching on matchName here instead — it's stable across UI language, display name isn't.
const FIXED_EFFECT_DISPLAY_NAMES = new Set(["motion", "opacity", "time remapping"]);

function isFixedComponent(displayName) {
  return FIXED_EFFECT_DISPLAY_NAMES.has(String(displayName || "").trim().toLowerCase());
}

// Confirmed at runtime (transform-panel-plan.md Part 1 item 3, and independently by
// effects.js's capture path): a resolved Keyframe's `.value` is itself a generic
// `{value: <actual>}` holder for every param type (PointF, boolean, number) — logged output was
// `{"value": {"value": [0.5, 0.5]}}` instead of the raw `[0.5, 0.5]`. This is documented in
// Adobe's own types (`Keyframe.value: { value: ... }`), so the unwrap is a contract, not a guess.
function unwrapKeyframeValue(keyframe) {
  if (keyframe === null || keyframe === undefined) return null;
  const raw = keyframe.value !== undefined ? keyframe.value : null;
  return (raw && typeof raw === "object" && !Array.isArray(raw) && "value" in raw) ? raw.value : raw;
}

module.exports = {
  FIXED_EFFECT_DISPLAY_NAMES,
  isFixedComponent,
  unwrapKeyframeValue,
};
