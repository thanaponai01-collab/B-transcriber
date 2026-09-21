const test = require("node:test");
const assert = require("node:assert/strict");
const { ensureHelperRunning, findHelperScript } = require("../uxp/cutdeck/helperStart.js");

function fakeClock() {
  let t = 0;
  return {
    now: () => t,
    sleep: async (ms) => { t += ms; },
  };
}

test("helper already running: no shell launch, no prompt", async () => {
  const rpc = async () => ({ version: "cutdeck-xml-1" });
  let openPathCalls = 0;
  const shell = { openPath: async () => { openPathCalls++; return ""; } };

  const result = await ensureHelperRunning({ rpc, shell, version: "cutdeck-xml-1" });

  assert.deepEqual(result, { started: false, alreadyRunning: true });
  assert.equal(openPathCalls, 0);
});

test("helper starts within the poll window", async () => {
  let pingCount = 0;
  const rpc = async () => {
    pingCount++;
    if (pingCount <= 3) throw new Error("Cannot reach CutDeck helper.");
    return { version: "cutdeck-xml-1" };
  };
  let openPathCalls = 0;
  const shell = { openPath: async () => { openPathCalls++; return ""; } };
  const { now, sleep } = fakeClock();

  const result = await ensureHelperRunning({ rpc, shell, now, sleep, version: "cutdeck-xml-1" });

  assert.deepEqual(result, { started: true, alreadyRunning: false });
  assert.equal(openPathCalls, 1);
});

test("openPath failure is surfaced, not swallowed", async () => {
  const rpc = async () => { throw new Error("Cannot reach CutDeck helper."); };
  const shell = { openPath: async () => "Access denied" };

  await assert.rejects(
    ensureHelperRunning({ rpc, shell, version: "cutdeck-xml-1" }),
    /Could not launch Start CutDeck\.cmd: Access denied/
  );
});

test("timeout names Start CutDeck.cmd so a human knows what to do", async () => {
  const rpc = async () => { throw new Error("Cannot reach CutDeck helper."); };
  const shell = { openPath: async () => "" };
  const { now, sleep } = fakeClock();

  await assert.rejects(
    ensureHelperRunning({ rpc, shell, now, sleep, version: "cutdeck-xml-1", timeoutMs: 2000, pollMs: 500 }),
    /Start CutDeck\.cmd/
  );
});

test("a shell without openPath fails clearly instead of crashing", async () => {
  const rpc = async () => { throw new Error("Cannot reach CutDeck helper."); };

  await assert.rejects(
    ensureHelperRunning({ rpc, shell: {}, version: "cutdeck-xml-1" }),
    /Start CutDeck\.cmd/
  );
});

test("findHelperScript resolves to the repo root's Start CutDeck.cmd", () => {
  const script = findHelperScript();
  assert.ok(script.endsWith("Start CutDeck.cmd"));
  assert.ok(!script.includes("uxp"));
});
