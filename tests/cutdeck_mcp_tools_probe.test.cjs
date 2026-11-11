const test = require("node:test");
const assert = require("node:assert/strict");
const { probeMcpTools, formatMcpToolsReport } = require("../uxp/cutdeck/mcpToolsProbe.js");

const TOOLS = {
  assistant: [
    { name: "getSequenceStructure", annotations: { readOnlyHint: true } },
    { name: "razorTrackItems", annotations: { destructiveHint: true } },
    { name: "importFiles", _meta: { requiresSensitiveApproval: true } },
  ],
  user: [{ name: "getSequenceStructure", annotations: { readOnlyHint: true } }],
};

function fakeUxp({ mcp, written }) {
  const folder = {
    createFile: async (name) => ({
      nativePath: `C:\\data\\${name}`,
      write: async (text) => { written[name] = text; },
    }),
  };
  return {
    hSLScripting: mcp === undefined ? undefined : { MCP: mcp },
    storage: { localFileSystem: { getDataFolder: async () => folder } },
  };
}

test("mcp tools probe: lists each endpoint, writes the full dump, flags each tool", async () => {
  const written = {};
  const calls = [];
  const mcp = {
    // Premiere's docstring says it resolves with a JSON array; accept a JSON string too.
    listMCPTools: async (ep) => { calls.push(ep); return ep === "user" ? JSON.stringify(TOOLS.user) : TOOLS[ep]; },
  };
  const report = await probeMcpTools({}, { uxp: fakeUxp({ mcp, written }) });

  assert.deepEqual(calls, ["assistant", "user"]);
  assert.equal(report.available, true);
  assert.equal(report.endpoints.assistant.count, 3);
  assert.equal(report.endpoints.user.count, 1);
  assert.equal(report.file, "C:\\data\\mcp-tools.json");
  assert.deepEqual(JSON.parse(written["mcp-tools.json"]).endpoints.assistant, TOOLS.assistant);

  const text = formatMcpToolsReport(report);
  assert.match(text, /assistant: 3 tools/);
  assert.match(text, /getSequenceStructure \[read-only\]/);
  assert.match(text, /razorTrackItems \[destructive\]/);
  assert.match(text, /importFiles \[sensitive\]/);
  assert.match(text, /C:\\data\\mcp-tools\.json/);
});

test("mcp tools probe: one endpoint failing does not hide the other", async () => {
  const written = {};
  const mcp = {
    listMCPTools: async (ep) => { if (ep === "user") throw new Error("server off"); return TOOLS.assistant; },
  };
  const report = await probeMcpTools({}, { uxp: fakeUxp({ mcp, written }) });
  assert.equal(report.endpoints.assistant.count, 3);
  assert.match(report.endpoints.user.error, /server off/);
  assert.match(formatMcpToolsReport(report), /user: FAILED .*server off/);
});

test("mcp tools probe: says so when Premiere does not expose the MCP object to this plugin", async () => {
  const written = {};
  const report = await probeMcpTools({}, { uxp: fakeUxp({ mcp: undefined, written }) });
  assert.equal(report.available, false);
  assert.deepEqual(written, {});
  const text = formatMcpToolsReport(report);
  assert.match(text, /not exposed/);
  // Says which link of uxp.hSLScripting.MCP.listMCPTools is missing.
  assert.match(text, /hSLScripting: undefined/);
  // require("uxp") hides its members from Object.keys, so list own property names too.
  assert.match(text, /storage/);
});

test("mcp tools probe: names the missing link when MCP exists without listMCPTools", async () => {
  const report = await probeMcpTools({}, { uxp: fakeUxp({ mcp: {}, written: {} }) });
  const text = formatMcpToolsReport(report);
  assert.match(text, /hSLScripting: object/);
  assert.match(text, /hSLScripting\.MCP: object/);
  assert.match(text, /hSLScripting\.MCP\.listMCPTools: undefined/);
});
