/* "List Premiere MCP Tools": read-only dump of the tools Premiere's built-in MCP servers expose
   (the ones the AI Assistant (beta) panel calls). Runs no tool and edits nothing.

   API: `require("uxp").hSLScripting.MCP.listMCPTools(endpoint)` is in NO Adobe typings or docs.
   Its only source is the docstring inside Adobe Premiere Pro.exe 27.0.0: "Returns a Promise that
   resolves with a JSON array of all registered MCP tool definitions ... Optional `endpoint`
   ("user" or "assistant") restricts the list to tools exposed by that MCP server". Premiere's own
   AI Assistant plugin (UXP/plugins/com.adobe.dva.creative-copilot) reads `hSLScripting.MCP` the
   same way. Whether a third-party plugin can see it is what this probe finds out.
   File write: uxp.storage FileSystemProvider.getDataFolder, Folder.createFile, File.write,
   Entry.nativePath (reference/adobe/api/uxp.txt). */

const ENDPOINTS = ["assistant", "user"];
const FILE_NAME = "mcp-tools.json";

const parseList = (v) => (typeof v === "string" ? JSON.parse(v) : v);

function flagsOf(tool) {
  const a = tool.annotations || {};
  const m = tool._meta || {};
  const flags = [];
  if (a.readOnlyHint === true) flags.push("read-only");
  if (a.destructiveHint === true) flags.push("destructive");
  if (m.requiresSensitiveApproval === true) flags.push("sensitive");
  if (m.alwaysAvailable === true) flags.push("always");
  return flags;
}

async function probeMcpTools(_ppro, deps = {}) {
  const uxp = deps.uxp || require("uxp");
  const mcp = uxp.hSLScripting && uxp.hSLScripting.MCP;
  if (!mcp || typeof mcp.listMCPTools !== "function") {
    return { available: false, uxpKeys: Object.keys(uxp).sort() };
  }

  const endpoints = {};
  const full = {};
  for (const ep of ENDPOINTS) {
    try {
      const tools = parseList(await mcp.listMCPTools(ep));
      full[ep] = tools;
      endpoints[ep] = { count: tools.length, tools: tools.map((t) => ({ name: t.name, flags: flagsOf(t) })) };
    } catch (e) {
      endpoints[ep] = { error: String((e && e.message) || e) };
    }
  }

  const folder = await uxp.storage.localFileSystem.getDataFolder();
  const file = await folder.createFile(FILE_NAME, { overwrite: true });
  await file.write(JSON.stringify({ capturedAt: new Date().toISOString(), endpoints: full }, null, 2));
  return { available: true, endpoints, file: file.nativePath };
}

function formatMcpToolsReport(r) {
  if (!r.available) {
    return "Premiere's MCP object (hSLScripting.MCP) is not exposed to CutDeck.\n" +
      `require("uxp") keys: ${r.uxpKeys.join(", ")}`;
  }
  const lines = [];
  for (const ep of ENDPOINTS) {
    const e = r.endpoints[ep];
    if (e.error) { lines.push(`${ep}: FAILED (${e.error})`); continue; }
    lines.push(`${ep}: ${e.count} tools`);
    for (const t of e.tools) lines.push(`  ${t.name}${t.flags.length ? ` [${t.flags.join(", ")}]` : ""}`);
  }
  lines.push("", `Full schemas: ${r.file}`);
  return lines.join("\n");
}

module.exports = { probeMcpTools, formatMcpToolsReport };
