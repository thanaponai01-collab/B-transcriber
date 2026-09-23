/* Exact tick arithmetic and conversion for Premiere Pro time values.
   Owns tick parsing and failure behaviour, TICKS_PER_SECOND, and the TickTime factory.
   Must never know features or UI state. */

const TICKS_PER_SECOND = 254016000000n;

/* Accepts what the host, storage and probes hand us — a decimal string, a safe integer,
   a BigInt, or a TickTime object — and rejects everything that would carry drift in. */
function toTicks(value, what) {
  const label = what || "tick value";
  if (typeof value === "bigint") return value;
  if (typeof value === "number") {
    if (!Number.isInteger(value)) throw new Error(`${label} is not a whole number of ticks: ${value}`);
    if (!Number.isSafeInteger(value)) throw new Error(`${label} exceeds exact Number range; pass it as a string: ${value}`);
    return BigInt(value);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (/^-?\d+$/.test(trimmed)) return BigInt(trimmed);
    throw new Error(`${label} is not an exact tick value: ${JSON.stringify(value)}`);
  }
  if (typeof value === "object" && value !== null) {
    if (value.ticks !== undefined) {
      const raw = value.ticks;
      if (typeof raw === "bigint") return raw;
      if (typeof raw === "number") {
        if (!Number.isInteger(raw)) throw new Error(`${label} is not a whole number of ticks: ${raw}`);
        if (!Number.isSafeInteger(raw)) throw new Error(`${label} exceeds exact Number range; pass it as a string: ${raw}`);
        return BigInt(raw);
      }
      if (typeof raw === "string") {
        const trimmed = raw.trim();
        if (/^-?\d+$/.test(trimmed)) return BigInt(trimmed);
        if (/^-?\d+\.0+$/.test(trimmed)) return BigInt(trimmed.split(".")[0]);
      }
    } else {
      if (typeof value.getSeconds === "function") {
        const sec = value.getSeconds();
        if (typeof sec === "number" && !isNaN(sec)) {
          return BigInt(Math.round(sec * Number(TICKS_PER_SECOND)));
        }
      }
      if (typeof value.seconds === "number" && !isNaN(value.seconds)) {
        return BigInt(Math.round(value.seconds * Number(TICKS_PER_SECOND)));
      }
    }
  }
  throw new Error(`${label} is not an exact tick value: ${JSON.stringify(value)}`);
}

/* Explicit tolerant variant for call sites that rely on fallback (such as 0n). */
function toTicksOr(value, fallback = 0n) {
  try {
    return toTicks(value);
  } catch (_) {
    return fallback;
  }
}

/* Exact TickTime maker for Premiere Pro API */
function makeTickTime(ppro) {
  const TickTime = ppro && ppro.TickTime;
  if (!TickTime) return null;
  const names = ["createWithTicks", "createWithTickcount", "createWithTickCount"];
  for (const n of names) {
    if (typeof TickTime[n] === "function") {
      return (val) => TickTime[n](val.toString());
    }
  }
  if (typeof TickTime.createWithSeconds === "function") {
    return (val) => TickTime.createWithSeconds(Number(val) / Number(TICKS_PER_SECOND));
  }
  return (val) => new TickTime(Number(val) / Number(TICKS_PER_SECOND));
}

module.exports = {
  TICKS_PER_SECOND,
  toTicks,
  ticks: toTicks,
  toTicksOr,
  makeTickTime,
};
