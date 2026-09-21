const test = require("node:test");
const assert = require("node:assert/strict");
const { ensureHelperRunning, deriveHelperScriptPath } = require("../uxp/cutdeck/helperStart.js");

const FAKE_SCRIPT_PATH = "D:\\repo\\Start CutDeck.cmd";

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

  const result = await ensureHelperRunning({
    rpc, shell, now, sleep, version: "cutdeck-xml-1", scriptPath: FAKE_SCRIPT_PATH,
  });

  assert.deepEqual(result, { started: true, alreadyRunning: false });
  assert.equal(openPathCalls, 1);
});

test("openPath is called with a plain string path, never something else", async () => {
  const rpc = async () => ({ version: "cutdeck-xml-1" });
  let seenPath = null;
  let pingCount = 0;
  const helperNotYetUp = async () => {
    pingCount++;
    if (pingCount === 1) throw new Error("Cannot reach CutDeck helper.");
    return { version: "cutdeck-xml-1" };
  };
  const shell = { openPath: async (p) => { seenPath = p; return ""; } };
  const { now, sleep } = fakeClock();

  await ensureHelperRunning({
    rpc: helperNotYetUp, shell, now, sleep, version: "cutdeck-xml-1", scriptPath: FAKE_SCRIPT_PATH,
  });

  assert.equal(typeof seenPath, "string");
  assert.equal(seenPath, FAKE_SCRIPT_PATH);
});

test("openPath failure is surfaced, not swallowed", async () => {
  const rpc = async () => { throw new Error("Cannot reach CutDeck helper."); };
  const shell = { openPath: async () => "Access denied" };

  await assert.rejects(
    ensureHelperRunning({ rpc, shell, version: "cutdeck-xml-1", scriptPath: FAKE_SCRIPT_PATH }),
    /Could not launch Start CutDeck\.cmd: Access denied/
  );
});

test("timeout names Start CutDeck.cmd so a human knows what to do", async () => {
  const rpc = async () => { throw new Error("Cannot reach CutDeck helper."); };
  const shell = { openPath: async () => "" };
  const { now, sleep } = fakeClock();

  await assert.rejects(
    ensureHelperRunning({
      rpc, shell, now, sleep, version: "cutdeck-xml-1", scriptPath: FAKE_SCRIPT_PATH,
      timeoutMs: 2000, pollMs: 500,
    }),
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

test("deriveHelperScriptPath finds the repo root from the plugin's own folder (Windows)", () => {
  const script = deriveHelperScriptPath("D:\\repo\\uxp\\cutdeck");
  assert.equal(script, "D:\\repo\\Start CutDeck.cmd");
});

test("deriveHelperScriptPath finds the repo root from the plugin's own folder (posix)", () => {
  const script = deriveHelperScriptPath("/Users/thana/repo/uxp/cutdeck");
  assert.equal(script, "/Users/thana/repo/Start CutDeck.cmd");
});

test("deriveHelperScriptPath tolerates a trailing slash", () => {
  const script = deriveHelperScriptPath("D:\\repo\\uxp\\cutdeck\\");
  assert.equal(script, "D:\\repo\\Start CutDeck.cmd");
});

test("deriveHelperScriptPath rejects a path that isn't the plugin's own folder", () => {
  assert.throws(() => deriveHelperScriptPath("D:\\repo\\somewhere\\else"), /repo root/);
});
