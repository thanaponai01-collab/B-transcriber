"""Ask Premiere's built-in AI Assistant (beta) a question, by driving its chat panel.

The panel is a WebView2 inside Premiere, the only part of Premiere's UI that Windows UI
Automation can see (docs/PREMIERE_FACTS.md, "Driving the AI Assistant (beta) chat").
`assistant_panel.ps1` does the UI Automation; this module decides when a reply is finished
and pulls its text out. The panel must already be open: its toolbar button is not reachable.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import subprocess
import time

SCRIPT = Path(__file__).with_name("assistant_panel.ps1")
_FAILURES = {
    2: "Premiere is not running",
    3: ("The AI Assistant panel is closed; open it with the 'Open AI Assistant (beta)' "
        "button at the top right of Premiere"),
}


def _panel(prompt: str | None = None) -> list[dict]:
    """The panel's elements in tree order, each with its depth; sends `prompt` first when given."""
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)]
    if prompt is not None:
        command += ["-PromptBase64", base64.b64encode(prompt.encode("utf-8")).decode("ascii")]
    run = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=60)
    if run.returncode:
        raise RuntimeError(_FAILURES.get(run.returncode) or run.stderr.strip() or "Could not read the AI Assistant panel")
    return json.loads(run.stdout)


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def parse_reply(elements: list[dict], prompt: str, seen: int = 0) -> dict:
    """The reply to the last `prompt` in the chat. `done` once its Like button is drawn.
    `seen` is how many times `prompt` was already in the chat before this asking, so an
    older identical message is never taken for the new one.

    A message is a run of siblings: a group each for the prompt, its timestamp, "Reasoning"
    and the reply, then the buttons Like / Dislike / Report content / "Used N credits".
    Inside the reply, each list item and each child container is its own line.
    """
    asked = [i for i, e in enumerate(elements) if e["type"] == "Text" and _same(e["name"], prompt)]
    if len(asked) <= seen:
        return {"done": False, "text": "", "credits": None, "buttons": []}
    top = elements[asked[-1]]["depth"] - 1  # depth of the message's sibling groups
    groups: list[list[str]] = []  # per sibling group after the prompt, its lines
    buttons, done = [], False
    for e in elements[asked[-1] + 1:]:
        if e["depth"] < top or (done and e["type"] != "Button"):  # left the message
            break
        if e["type"] == "Button":
            done = done or (e["name"] == "Like" and e["depth"] == top)
            buttons.append(e["name"])
        elif e["depth"] == top:
            groups.append([""])
        elif groups and (e["type"] == "ListItem" or (e["depth"] == top + 1 and e["type"] != "Text")):
            groups[-1].append("")
        elif groups and e["type"] == "Text" and e["leaf"]:
            groups[-1][-1] += e["name"]
    lines = [line.strip() for group in groups[1:] for line in group  # [0] is the timestamp
             if line.strip() and group != ["Reasoning"]]
    used = [m for m in (re.fullmatch(r"Used ([\d.]+) credits", name) for name in buttons) if m]
    return {"done": done, "text": "\n".join(lines), "credits": float(used[0].group(1)) if used else None,
            "buttons": [] if done else buttons}


def ask(prompt: str, timeout_s: float = 120) -> dict:
    """Send `prompt` to the AI Assistant and wait for its reply.

    Returns {done, text, credits, buttons}. `done` False means the wait ran out: `text` is
    what was on screen, and `buttons` are the buttons under it (an approval the assistant is
    waiting for shows up here).
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be non-empty text")
    prompt = " ".join(prompt.split())  # one line, so the chat draws it as one text to find again
    deadline = time.monotonic() + timeout_s
    seen = sum(e["type"] == "Text" and _same(e["name"], prompt) for e in _panel())
    reply = parse_reply(_panel(prompt), prompt, seen)
    while not reply["done"] and time.monotonic() < deadline:
        time.sleep(2)
        reply = parse_reply(_panel(), prompt, seen)
    return reply
