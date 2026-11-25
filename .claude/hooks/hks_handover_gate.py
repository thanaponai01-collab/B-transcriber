"""Stop hook: an HKS draft can't reach the user without a passing (or labelled) hks_handover.

Reads only the session transcript (stdin gives its path). It blocks the stop when:
1. the session changed a draft through CutDeck after its last ``hks_handover`` run, or
2. the last ``hks_handover`` printed HANDOVER BLOCKED and the policy is "block", or the policy is
   "label" and the final message does not name every failed gate.
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
                s = json.dumps(x.get("input"), ensure_ascii=False)
                if "hks_handover" in s:
                    pending[x["id"]] = "handover"
                elif MUTATES.search(s) or MUTATES.search(x.get("name", "")):
                    yield "mutate", s[:200]
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
    if "HANDOVER BLOCKED" not in result:
        return None
    failed = re.findall(r"FAILED (\w+)", result)
    if policy == "block":
        return f"hks_handover failed {failed}. Fix each one and run hks_handover again before handing over."
    said = evs[last["say"]][1] if last["say"] > last["handover"] else ""
    missing = [g for g in failed if g not in said]
    if missing:
        return (f"hks_handover failed {failed}, and your last message doesn't name {missing}. Fix them, or open "
                "the handover with each failed gate's id and value.")
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
