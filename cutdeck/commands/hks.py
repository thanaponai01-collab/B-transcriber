"""The HKS commands: hks_handover and hks_status run the HKS gates (cutdeck/hks_enforce.py) on the
saved project. hks_enforce is imported inside each run, so loading the table never loads it.
cutdeck/driver_commands.py lists them in the one table."""
from __future__ import annotations

import asyncio
from pathlib import Path

from cutdeck.commands.core import Command, Premiere


def _hks_handover_arguments(args: dict, jobs) -> dict:
    if not isinstance(args.get("sequence"), str) or not args["sequence"].strip():
        raise ValueError("sequence must name the draft (its sequence_id, or a unique name)")
    for key in ("answers", "overrides"):
        value = args.get(key) or {}
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ValueError(f"{key} must map ids to text")
    if any(not v.strip() for v in (args.get("overrides") or {}).values()):
        raise ValueError("every override needs a written reason")
    return {"sequence": args["sequence"], "body_from": float(args.get("body_from") or 0.0),
            "show_end": args.get("show_end"), "answers": args.get("answers") or {},
            "overrides": args.get("overrides") or {}, "by": str(args.get("by") or "agent")}


async def _hks_handover(args: dict, premiere: Premiere) -> dict:
    from cutdeck import hks_enforce
    saved = await premiere("save_project", {})
    return await asyncio.to_thread(hks_enforce.handover, Path(saved["path"]), args["sequence"], args["body_from"],
                                   args["show_end"], args["answers"], args["overrides"], args["by"])


def _hks_status_arguments(args: dict, jobs) -> dict:
    return {"mark_baseline": args.get("mark_baseline") is True}


async def _hks_status(args: dict, premiere: Premiere) -> dict:
    from cutdeck import hks_enforce
    project = await premiere("list_project", {"depth": 1})
    rows = await asyncio.to_thread(hks_enforce.status, Path(project["path"]), project["sequences"],
                                   mark_baseline=args["mark_baseline"])
    return {"project": project["path"], "sequences": rows}


COMMANDS: dict[str, Command] = {
    "hks_handover": Command(
        600, _hks_handover_arguments, "write",
        """
        Hand over an HKS draft: the helper saves the project, reads the save, runs every HKS gate on
        the sequence (by sequence_id, or a name no other sequence has), checks that every active
        do-confirm rule in projects/hks/registry/rules/ has a written answer in `answers`
        ({rule_id: answer}), copies the save into CutDeck/Drafts and stores the result keyed by the
        sequence and its saved cut. Returns status pass or fail with each failed gate's id and value
        and the rule ids still unanswered. `body_from` is the body start in seconds (after the hook
        and sting); the record keeps it. `overrides` ({gate: reason}) waives a failed control, each
        with a written reason; `by` says who. The panel shows the stored status; an edit after this
        call makes the draft ungated until it is called again. Needs the CutDeck panel open.
        """,
        (("sequence", str), ("body_from", float, 0.0), ("show_end", float | None, None),
         ("answers", dict | None, None), ("overrides", dict | None, None), ("by", str, "agent")),
        run=_hks_handover),
    "hks_status": Command(
        120, _hks_status_arguments, "write",
        """
        Every sequence of the open project with its HKS gate status from the helper's records
        (never from an agent): pass, fail (gate id and value), or ungated (never gated, changed
        after its last gate run, or not saved yet). Reads the last save; does not save.
        `mark_baseline: true` (once, at day set-up) records the sequences there now as the day's
        start; each row then says `new` for any sequence made later, by any route.
        Needs the CutDeck panel open.
        """,
        (("mark_baseline", bool, False),),
        run=_hks_status),
}
