/* The shared fake Premiere (tests/fakes/premiere.cjs) may only model members Premiere declares:
   each is checked against reference/adobe/api/premierepro.txt (generated from Adobe's typings).
   Also pins the proven rules the fake enforces (docs/PREMIERE_FACTS.md). */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const fake = require("./fakes/premiere.cjs");

const index = fs.readFileSync(path.join(__dirname, "..", "reference", "adobe", "api", "premierepro.txt"), "utf8")
  .split(/\r?\n/).filter((l) => l && !l.startsWith("#"));
// "Owner.member(...)  [static, ...]  -- doc" -> { key: "Owner.member", isStatic }
const declared = new Map(index.map((l) => {
  const key = l.match(/^[\w.]+/)[0];
  return [key, /\[[^\]]*\bstatic\b/.test(l)];
}));

const ownKeys = (o) => {
  const keys = new Set(Object.keys(o));
  const proto = Object.getPrototypeOf(o);
  if (proto && proto !== Object.prototype) for (const k of Object.getOwnPropertyNames(proto)) if (k !== "constructor") keys.add(k);
  return [...keys];
};

for (const { adobe, side, fake: obj } of fake.FAKE_SHAPE) {
  test(`fake ${adobe} (${side}) models only declared members`, () => {
    const missing = [];
    if (side === "enums") {
      for (const [enumName, members] of Object.entries(obj)) {
        for (const m of Object.keys(members)) if (!declared.has(`${adobe}.${enumName}.${m}`)) missing.push(`${enumName}.${m}`);
      }
    } else {
      for (const k of ownKeys(obj)) {
        const isStatic = declared.get(`${adobe}.${k}`);
        if (isStatic === undefined || isStatic !== (side === "static")) missing.push(k);
      }
    }
    assert.deepEqual(missing, [], `not declared on ${adobe} (${side}) in the typings: ${missing.join(", ")}`);
  });
}

test("the typings check itself catches an invented member", () => {
  assert.equal(declared.has("TickTime.createWithTicks"), true);
  assert.equal(declared.get("TickTime.createWithTicks"), true, "createWithTicks is static");
  assert.equal(declared.has("TickTime.createWithFrames"), false);
});

test("an Action created outside the transaction callback throws when added", () => {
  const { project, action } = createFake();
  const early = action(() => {});
  assert.throws(() => project.executeTransaction((c) => c.addAction(early), "x"), { message: fake.SCRIPT_OBJECT_INVALID });
});

test("actions apply only at commit, one undo step per transaction", () => {
  const { project, action, undoSteps } = createFake();
  const state = { n: 0 };
  let seenInside = null;
  project.executeTransaction((c) => {
    c.addAction(action(() => { state.n += 1; }));
    seenInside = state.n;
  }, "step");
  assert.equal(seenInside, 0, "a read inside the callback does not see the compound's changes");
  assert.equal(state.n, 1);
  assert.deepEqual(undoSteps, ["step"]);
});

test("a selection is only valid inside its callback", async () => {
  let kept = null;
  fake.TrackItemSelection.createEmptySelection((sel) => { sel.addItem("clip"); kept = sel; });
  assert.throws(() => kept.addItem("late"), { message: fake.SCRIPT_OBJECT_INVALID });
});

test("point keyframe values must be PointF, not arrays", () => {
  assert.throws(() => fake.assertPointValue([0.5, 0.5]), { message: "Illegal Parameter type" });
  assert.ok(fake.assertPointValue(new fake.PointF(0.5, 0.5)));
});

test("interpolation values are the live ones, not the typings' alphabetical order", () => {
  assert.deepEqual([fake.Constants.InterpolationMode.LINEAR, fake.Constants.InterpolationMode.HOLD,
    fake.Constants.InterpolationMode.BEZIER], [0, 4, 5]);
});

function createFake() { return { ...fake.createProject(), action: fake.action }; }
