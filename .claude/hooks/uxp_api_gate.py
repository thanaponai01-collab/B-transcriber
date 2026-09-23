"""PreToolUse gate for UXP / Premiere code (CLAUDE.md rule 2).

The first UXP-code edit in a session is denied with the verification checklist,
so the API lookup happens before anything is written. Later UXP edits in the
same session are allowed, with the rule re-injected as context.
"""
import json
import os
import re
import sys
import tempfile

CODE_EXT = (".js", ".mjs", ".cjs", ".ts", ".html")
API_RE = re.compile(r"""require\(\s*["'](premierepro|uxp)["']\s*\)|\bppro\.""")

CHECKLIST = (
    "CLAUDE.md rule 2 (UXP API gate): before writing UXP/Premiere code, prove every "
    "Adobe API you are about to use exists.\n"
    "1. Premiere UXP: `npm pack @adobe/premierepro@26.2.1` into the scratchpad and "
    "read package/src/premierepro.d.ts.\n"
    "2. UXP platform APIs: github.com/AdobeDocs/uxp (src/pages/uxp-api/reference-js/).\n"
    "3. Enum numeric values / runtime semantics are not in the typings: live-probe them.\n"
    "4. State which source confirmed each API.\n"
    "5. If UXP lacks the feature, do NOT fake it in the panel: build it in the CutDeck "
    "helper (cutdeck/xml_bridge.py, ws://127.0.0.1:7891, MCP: cutdeck/mcp_server.py) "
    "and call it from the panel via core/rpc.js."
)


def new_text(tool_input):
    parts = [tool_input.get("content", ""), tool_input.get("new_string", "")]
    parts += [e.get("new_string", "") for e in tool_input.get("edits", []) or []]
    return "\n".join(p for p in parts if p)


def is_uxp(path, text):
    p = path.replace("\\", "/").lower()
    if not p.endswith(CODE_EXT):
        return False
    return "/uxp/" in p or p.startswith("uxp/") or bool(API_RE.search(text))


def main():
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path", "")
    if not is_uxp(path, new_text(tool_input)):
        return

    session = re.sub(r"[^A-Za-z0-9_-]", "", data.get("session_id", "nosession"))
    marker = os.path.join(tempfile.gettempdir(), f"claude-uxp-gate-{session}")
    if not os.path.exists(marker):
        open(marker, "w").close()
        decision, reason = "deny", (
            CHECKLIST + "\n\nFirst UXP edit this session was blocked. Do the lookup, "
            "then retry the edit.")
    else:
        decision, reason = "allow", CHECKLIST

    out = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}
    if decision == "allow":
        out["hookSpecificOutput"]["additionalContext"] = CHECKLIST
        del out["hookSpecificOutput"]["permissionDecision"]
        del out["hookSpecificOutput"]["permissionDecisionReason"]
    print(json.dumps(out))


if __name__ == "__main__":
    main()
