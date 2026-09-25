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
    "Adobe API you are about to use exists. Everything is local, no download needed:\n"
    "1. docs/PREMIERE_FACTS.md: what each API really does live (catches, BROKEN, ABSENT).\n"
    "2. reference/adobe/api/premierepro.txt and api/uxp.txt: every declared member, one "
    "line each (grep '^ClassName\\.'); 'NOT IN 26.2.1' = needs Premiere 26.3+.\n"
    "3. reference/adobe/docs/ (Adobe's docs) and reference/adobe/samples/ (Adobe's panels).\n"
    "4. Enum numeric values / runtime semantics are not in the typings: live-probe them, "
    "then add the result to docs/PREMIERE_FACTS.md.\n"
    "5. State which source confirmed each API. `node tools/adobe/check-api.mjs` must pass.\n"
    "6. If UXP lacks the feature, do NOT fake it in the panel: build it in the CutDeck "
    "helper (cutdeck/xml_bridge.py, ws://127.0.0.1:7891, MCP: cutdeck/mcp_server.py) "
    "and call it from the panel via core/rpc.js."
)
# Tooling that reads Adobe's API (the reference itself, its generators and checks) is not panel code.
NOT_PANEL = ("tools/adobe/", "reference/adobe/")


def new_text(tool_input):
    parts = [tool_input.get("content", ""), tool_input.get("new_string", "")]
    parts += [e.get("new_string", "") for e in tool_input.get("edits", []) or []]
    return "\n".join(p for p in parts if p)


def is_uxp(path, text):
    p = path.replace("\\", "/").lower()
    if not p.endswith(CODE_EXT) or any(d in p for d in NOT_PANEL):
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
