// transform/apply.js — WRITES Motion values for the Transform & Align panel (Phases 2–5 of
// docs/research/cutdeck-transform-panel-plan.md). No geometry, no DOM: callers pass values
// already in Premiere's own units (Position/Anchor Point normalized, Scale %, Rotation °).
//
// APIs (reference/adobe/api/premierepro.txt): Component.getParam, ComponentParam.createKeyframe,
// ComponentParam.createSetValueAction, PointF. The write path is the one timeline/effects.js
// already runs live for captured presets (point values as `new ppro.PointF`, PREMIERE_FACTS
// "createKeyframe for point params"). NOT yet proven: that it takes on Motion, a fixed effect —
// the plan's gate 2 (write, read back, compare with Effect Controls, undo). Params are fetched
// before the transaction; every Action and Keyframe is created inside the callback
// (PREMIERE_FACTS "executeTransaction + CompoundAction").

const { findMotionComponent, PARAM_INDEX } = require("./params.js");
const { runTransaction } = require("../host/project.js");

// `writes` = [{ item, name, values: { position?: {x,y}, anchorPoint?: {x,y}, scale?, rotation? } }].
// `paramWrites` = [{ param, field, value, name }]: params the caller already holds (a Graphic's
// text layer Position). Everything lands in ONE transaction, so one Ctrl+Z undoes the whole
// batch. Throws before touching anything if a clip's Motion or a param can't be found.
async function applyMotionValues(ppro, project, label, writes, paramWrites = []) {
  const prepared = [];
  for (const w of writes) {
    const component = await findMotionComponent(w.item);
    if (!component) throw new Error(`"${w.name}" has no Motion effect to write to.`);
    for (const [field, value] of Object.entries(w.values)) {
      let param = null;
      try { param = component.getParam(PARAM_INDEX[field]); } catch (_) { param = null; }
      if (!param) throw new Error(`Could not reach ${field} on "${w.name}".`);
      prepared.push({ param, field, value, name: w.name });
    }
  }

  for (const w of paramWrites) {
    if (!w.param) throw new Error(`Could not reach ${w.field} on "${w.name}".`);
    prepared.push(w);
  }

  runTransaction(project, label, (compound) => {
    for (const { param, field, value, name } of prepared) {
      const v = typeof value === "number" ? value : new ppro.PointF(value.x, value.y);
      const setAction = param.createSetValueAction(param.createKeyframe(v), true);
      if (!setAction || !compound.addAction(setAction)) {
        throw new Error(`Premiere refused to set ${field} on "${name}".`);
      }
    }
  });
}

module.exports = { applyMotionValues };
