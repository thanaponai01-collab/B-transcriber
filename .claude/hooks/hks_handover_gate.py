"""Stop hook: an HKS draft can't reach the user without a passing (or labelled) hks_handover.

Reads only the session transcript (stdin gives its path). It blocks the stop when:
1. the session changed a draft through CutDeck after its last ``hks_handover`` run, or
2. the last ``hks_handover`` printed neither HANDOVER OK nor BLOCKED (it didn't finish), or
3. it failed and the policy is "block", or a gate failed or was overridden and the final message
   doesn't name it (policy "label").
The policy is ``late_draft_policy`` in projects/hks/gates/registry.json. After three blocks in a
row it lets the stop through and logs it, so a gate it can't satisfy never loops forever.

Register (project or local settings, not the shared checkout):
  {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python .claude/hooks/hks_handover_gate.py"}]}]}}
"""
import json
import re
import sys
from pathlib import Path

MUTATES = re.compile(r"build_sequence|apply_cuts|cut_copy|edit_clips|remove_piece|keep_words|paste_from"
                     r"|premiere_arrange|place_media|duplicate_sequence")
RUNS = re.compile(r"(?<![\w./-])(python3?|py)(\.exe)?\s")  # Python run as a command: CutDeck is reached from it
READ_ONLY = re.compile(r"\s*(cat|head|tail|sed|grep|rg|ls|git|less|type|Get-Content|Select-String)\b")
REPO = Path(__file__).resolve().parents[2]
LOG = REPO / "output" / "hks_gates" / "stop_hook.log"


def events(transcript: Path):
    """(kind, text) in order: 'mutate', 'handover' (its result text), 'say' (assistant text)."""
    pending = {}
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        content = (o.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for x in content:
            if x.get("type") == "tool_use":
                name = x.get("name", "")
                cmd = (x.get("input") or {}).get("command", "") if name in ("Bash", "PowerShell") else ""
                # A draft change is a CutDeck tool, or Python run with a CutDeck build command in the
                # call; reading or grepping a file that names one is not.
                if (name.startswith("mcp__") and MUTATES.search(name)) or (
                        cmd and MUTATES.search(cmd) and RUNS.search(cmd) and not READ_ONLY.match(cmd)):
                    yield "mutate", (name + " " + cmd)[:200]
                if "hks_handover" in cmd and not READ_ONLY.match(cmd):
                    pending[x["id"]] = "handover"  # after the build when both share one command
            elif x.get("type") == "tool_result" and pending.get(x.get("tool_use_id")) == "handover":
                c = x.get("content")
                yield "handover", c if isinstance(c, str) else " ".join(y.get("text", "") for y in c or [] if isinstance(y, dict))
            elif x.get("type") == "text" and o.get("type") == "assistant":
                yield "say", x["text"]


def verdict(evs: list[tuple[str, str]], policy: str) -> str | None:
    last = {k: max((i for i, (kind, _) in enumerate(evs) if kind == k), default=-1) for k in ("mutate", "handover", "say")}
    if last["mutate"] < 0:
        return None  # no draft touched in this session
    if last["mutate"] > last["handover"]:
        return ("You changed an HKS draft after the last hks_handover. Save the project, then run "
                f"`cd \"{REPO}\" && python -m cutdeck.hks_handover --prproj <saved .prproj> --sequence <draft> "
                "--from <body start s>` and open your handover with its header.")
    result = evs[last["handover"]][1]
    if "HANDOVER OK" not in result and "HANDOVER BLOCKED" not in result:
        return "hks_handover did not finish (no HANDOVER OK or BLOCKED in its output). Run it again on the saved project."
    failed = re.findall(r"FAILED (\w+)", result)
    overridden = re.findall(r"OVERRIDDEN (\w+)", result)
    if failed and policy == "block":
        return f"hks_handover failed {failed}. Fix each one and run hks_handover again before handing over."
    said = evs[last["say"]][1] if last["say"] > last["handover"] else ""
    missing = [g for g in failed + overridden if g not in said]
    if missing:
        return (f"hks_handover failed or overrode {failed + overridden}, and your last message doesn't name "
                f"{missing}. Fix them, or open the handover with each one's id and value.")
    return None


def main() -> int:
    hook = json.load(sys.stdin)
    reg = json.loads((REPO / "projects" / "hks" / "gates" / "registry.json").read_text(encoding="utf-8"))
    policy = reg.get("late_draft_policy", "label")
    evs = list(events(Path(hook["transcript_path"])))
    reason = verdict(evs, policy)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    prior = [l for l in LOG.read_text(encoding="utf-8").splitlines()] if LOG.exists() else []
    streak = 0
    for l in reversed(prior):
        e = json.loads(l)
        if e["session"] != hook.get("session_id") or e["decision"] != "block":
            break
        streak += 1
    decision = "block" if reason and streak < 3 else ("gave_up" if reason else "allow")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"session": hook.get("session_id"), "decision": decision, "reason": reason,
                            "stop_hook_active": hook.get("stop_hook_active"), "policy": policy}, ensure_ascii=False) + "\n")
    if decision == "block":
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
