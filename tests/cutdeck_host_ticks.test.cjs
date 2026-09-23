const test = require("node:test");
const assert = require("node:assert/strict");

const {
  TICKS_PER_SECOND,
  toTicks,
  ticks,
  toTicksOr,
  makeTickTime,
} = require("../uxp/cutdeck/host/ticks.js");

test("TICKS_PER_SECOND equals 254016000000n", () => {
  assert.equal(TICKS_PER_SECOND, 254016000000n);
  assert.equal(typeof TICKS_PER_SECOND, "bigint");
});

test("toTicks preserves BigInt values", () => {
  assert.equal(toTicks(0n), 0n);
  assert.equal(toTicks(42n), 42n);
  assert.equal(toTicks(254016000000n), 254016000000n);
  assert.equal(toTicks(-10594584000n), -10594584000n);
});

test("toTicks converts safe integer numbers to BigInt", () => {
  assert.equal(toTicks(0), 0n);
  assert.equal(toTicks(42), 42n);
  assert.equal(toTicks(-100), -100n);
});

test("toTicks refuses inexact and unsafe numbers", () => {
  assert.throws(() => toTicks(1.5, "In point"), /not a whole number of ticks: 1.5/);
  assert.throws(() => toTicks(-0.1), /not a whole number of ticks: -0.1/);
  assert.throws(() => toTicks(Number.MAX_SAFE_INTEGER + 2, "In point"), /exceeds exact Number range/);
});

test("toTicks parses exact integer strings", () => {
  assert.equal(toTicks("0"), 0n);
  assert.equal(toTicks("42"), 42n);
  assert.equal(toTicks("  42  "), 42n);
  assert.equal(toTicks("-10594584000"), -10594584000n);
});

test("toTicks refuses decimal strings and unparsable garbage", () => {
  assert.throws(() => toTicks("12.0", "In point"), /not an exact tick value: "12.0"/);
  assert.throws(() => toTicks("254016000000.0"), /not an exact tick value/);
  assert.throws(() => toTicks("12.5"), /not an exact tick value/);
  assert.throws(() => toTicks("garbage"), /not an exact tick value: "garbage"/);
  assert.throws(() => toTicks(""), /not an exact tick value/);
  assert.throws(() => toTicks(null, "In point"), /not an exact tick value: null/);
  assert.throws(() => toTicks(undefined), /not an exact tick value: undefined/);
  assert.throws(() => toTicks({}), /not an exact tick value: {}/);
});

test("toTicks unwraps TickTime objects", () => {
  // TickTime object with BigInt ticks
  assert.equal(toTicks({ ticks: 254016000000n }), 254016000000n);
  // TickTime object with integer number
  assert.equal(toTicks({ ticks: 42 }), 42n);
  // TickTime object with integer string
  assert.equal(toTicks({ ticks: "254016000000" }), 254016000000n);
  assert.equal(toTicks({ ticks: "  100  " }), 100n);
  // TickTime object with Premiere's decimal string ending in .0
  assert.equal(toTicks({ ticks: "254016000000.0" }), 254016000000n);
  assert.equal(toTicks({ ticks: "0.00" }), 0n);
  // TickTime object with seconds
  assert.equal(toTicks({ seconds: 1 }), 254016000000n);
  assert.equal(toTicks({ seconds: 0.5 }), 127008000000n);
  // TickTime object with getSeconds()
  assert.equal(toTicks({ getSeconds: () => 2 }), 508032000000n);

  // Inexact TickTime objects throw
  assert.throws(() => toTicks({ ticks: 1.5 }), /not a whole number of ticks/);
  assert.throws(() => toTicks({ ticks: "12.5" }), /not an exact tick value/);
  assert.throws(() => toTicks({ ticks: "bad" }), /not an exact tick value/);
});

test("toTicksOr returns converted value when valid, fallback on failure", () => {
  // Valid inputs return BigInt
  assert.equal(toTicksOr(42n), 42n);
  assert.equal(toTicksOr(42), 42n);
  assert.equal(toTicksOr("42"), 42n);
  assert.equal(toTicksOr({ ticks: "42" }), 42n);
  assert.equal(toTicksOr({ ticks: "42.0" }), 42n);

  // Default fallback is 0n
  assert.equal(toTicksOr("12.0"), 0n);
  assert.equal(toTicksOr("garbage"), 0n);
  assert.equal(toTicksOr(null), 0n);
  assert.equal(toTicksOr(undefined), 0n);
  assert.equal(toTicksOr(1.5), 0n);
  assert.equal(toTicksOr({}), 0n);

  // Custom fallback
  assert.equal(toTicksOr("12.0", 100n), 100n);
  assert.equal(toTicksOr("garbage", 99n), 99n);
  assert.equal(toTicksOr(null, null), null);
  assert.equal(toTicksOr(undefined, 10594584000n), 10594584000n);
});

test("ticks alias matches toTicks", () => {
  assert.equal(ticks, toTicks);
  assert.equal(ticks(42), 42n);
  assert.throws(() => ticks("12.0", "In point"), /not an exact tick value/);
});

test("makeTickTime creates TickTime factory from host ppro", () => {
  assert.equal(makeTickTime(null), null);
  assert.equal(makeTickTime({}), null);

  // createWithTicks priority
  const mockWithTicks = {
    TickTime: {
      createWithTicks: (str) => ({ type: "withTicks", val: str }),
    },
  };
  const fnTicks = makeTickTime(mockWithTicks);
  assert.deepEqual(fnTicks(254016000000n), { type: "withTicks", val: "254016000000" });

  // createWithSeconds fallback
  const mockWithSeconds = {
    TickTime: {
      createWithSeconds: (sec) => ({ type: "withSeconds", val: sec }),
    },
  };
  const fnSec = makeTickTime(mockWithSeconds);
  assert.deepEqual(fnSec(254016000000n), { type: "withSeconds", val: 1 });

  // constructor fallback
  class MockTickTime {
    constructor(sec) {
      this.sec = sec;
    }
  }
  const mockCtor = { TickTime: MockTickTime };
  const fnCtor = makeTickTime(mockCtor);
  const created = fnCtor(254016000000n);
  assert.ok(created instanceof MockTickTime);
  assert.equal(created.sec, 1);
});
