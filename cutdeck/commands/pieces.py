"""The pieces commands: paste_from, paste_pieces and arrange copy ranges of one sequence into another
and reorder them. cutdeck/driver_commands.py lists them in the one table."""
from __future__ import annotations

import sys

from cutdeck.commands.core import Command, PIECE_SUFFIX, Premiere, _range_arguments, _ticks
from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND


PARK_GAP_TICKS = 30 * PPRO_TICKS_PER_SECOND  # PREMIERE_FACTS "Edit > Paste at a parking spot": end + 30 s


def _paste_from_arguments(args: dict, jobs) -> dict:
    result = {}
    for key in ("source", "target"):
        if not isinstance(args.get(key), str) or not args[key].strip():
            raise ValueError(f"{key} must be a sequence name")
        result[key] = args[key]
    v_offset = args.get("v_offset", 0)
    if not isinstance(v_offset, int) or isinstance(v_offset, bool) or v_offset < 0:
        raise ValueError("v_offset must be a whole number of tracks, 0 or more")
    keep_piece = args.get("keep_piece", False)
    if not isinstance(keep_piece, bool):
        raise ValueError("keep_piece must be true or false")
    reason = args.get("per_piece_reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError("per_piece_reason must say why this build goes piece by piece")
    return {**result, **_range_arguments(args), "at_ticks": _ticks(args.get("at_ticks"), "at_ticks"),
            "v_offset": v_offset, "keep_piece": keep_piece, **({"per_piece_reason": reason} if reason else {})}


def _clips(timeline: dict, since: int = 0) -> list[tuple[str, int, int, int]]:
    """(V|A, track number, start, end) of every clip starting at `since` or later."""
    return sorted((t["id"][0], int(t["id"][1:]), int(c["start_ticks"]), int(c["end_ticks"]))
                  for t in timeline["tracks"] for c in t["clips"] if int(c["start_ticks"]) >= since)


def _piece_name(source: str, a: int, b: int) -> str:
    return f"{source} {a / PPRO_TICKS_PER_SECOND:.3f}-{b / PPRO_TICKS_PER_SECOND:.3f}s{PIECE_SUFFIX}"


async def _paste_from(args: dict, premiere: Premiere) -> dict:
    """make_subsequence of the source range → Edit > Copy → Edit > Paste parked past the target's
    end → build_sequence into: clone to at_ticks, lift the park → read back → remove the piece."""
    source, target, at = args["source"], args["target"], int(args["at_ticks"])
    a, b = int(args["in_ticks"]), int(args["out_ticks"])
    if source == target:
        raise ValueError("source and target must be different sequences")
    piece = _piece_name(source, a, b)
    # Make Subsequence drops a range's empty lead-in (live 2026-11-24: 0.5-3 s with the first clip
    # at 1 s gave a piece starting at 0), so measure it here and add it back when placing.
    starts = [max(s, a) for _, _, s, e in _clips(await premiere("read_timeline", {"sequence": source})) if s < b and e > a]
    if not starts:
        raise ValueError(f"{source} has no clips in that range")
    offset = min(starts) - a
    project = await premiere("list_project", {"depth": 1})
    if any(s["name"] == piece for s in project["sequences"]):
        await premiere("remove_piece", {"name": piece})  # kept by an earlier failed run of this paste
    await premiere("make_subsequence", {"sequence": source, "in_ticks": str(a), "out_ticks": str(b), "result_name": piece})
    timeline = await premiere("read_timeline", {"sequence": piece})
    want = _clips(timeline)
    before = await premiere("read_timeline", {"sequence": target})
    length = b - a
    park = max(int(before["end_ticks"]), at + length) + PARK_GAP_TICKS
    await premiere("select_clips", {"sequence": piece, "clips": [c["id"] for t in timeline["tracks"] for c in t["clips"]]})
    await premiere("menu_command", {"path": "Edit > Copy", "sequence": piece})
    await premiere("set_playhead", {"sequence": target, "ticks": str(park)})
    await premiere("menu_command", {"path": "Edit > Paste", "sequence": target})
    pasted = _clips(await premiere("read_timeline", {"sequence": target}), park)
    # Paste lands at the playhead on the lowest targeted tracks (PREMIERE_FACTS "Edit > Copy in one
    # sequence"), assumed to put the earliest copied clip there (`lead`, 0 while subsequences start
    # on a clip). Find how far each kind landed from the piece's tracks, then put video where asked.
    lead = min(s for _, _, s, _ in want)
    shift = {}
    for kind in ("V", "A"):
        got = [p for p in pasted if p[0] == kind]
        exp = [w for w in want if w[0] == kind]
        if got and exp:
            shift[kind] = min(g[1] for g in got) - min(e[1] for e in exp)
    landed = sorted((k, n + shift.get(k, 0), s - lead + park, e - lead + park) for k, n, s, e in want)
    left = f"The pasted copy is left at {park} ticks on {target!r} and piece {piece!r} is kept, for you to see."
    if shift.get("A", 0) != 0:
        raise ValueError(f"the audio landed {-shift['A']} track(s) lower than in the source (Paste uses the lowest "
                         f"targeted tracks and paste_from cannot move audio between tracks). {left}")
    if pasted != landed:
        raise ValueError(f"the paste did not land as the piece reads: expected {landed}, got {pasted}. {left}")
    v_up = args["v_offset"] - shift.get("V", 0)
    steps = [{"op": "clone", "from_ticks": str(park), "to_ticks": str(park + length), "dt_ticks": str(at + offset + lead - park), "v_offset": v_up},
             {"op": "lift", "from_ticks": str(park), "to_ticks": str(park + length)}]
    try:
        await premiere("build_sequence", {"project": project["path"], "base": target, "name": target, "items": [],
                                          "options": {"into": True, "steps": steps}})
    except Exception as e:
        raise ValueError(f"moving the paste into place failed: {e}. {left}") from e
    after = await premiere("read_timeline", {"sequence": target})
    placed = [c for c in _clips(after) if at + offset <= c[2] < at + length]
    expected = sorted((k, n + (args["v_offset"] if k == "V" else 0), s + at + offset, e + at + offset) for k, n, s, e in want)
    missing = sorted(set(expected) - set(placed))
    left_at_park = _clips(after, park)
    if not args["keep_piece"]:
        await premiere("remove_piece", {"name": piece})
    return {"target": target, "at_ticks": str(at), "clips": len(want), "missing": missing,
            "left_at_park": left_at_park, "end_ticks": after["end_ticks"],
            "piece": piece if args["keep_piece"] else None}


def _arrange_arguments(args: dict, jobs) -> dict:
    for key in ("sequence", "result_name"):
        if not isinstance(args.get(key), str) or not args[key].strip():
            raise ValueError(f"{key} must be a sequence name")
    if args["sequence"] == args["result_name"]:
        raise ValueError("result_name must differ from sequence (the source is never edited)")
    blocks = args.get("blocks")
    if not isinstance(blocks, list) or len(blocks) < 2:
        raise ValueError("blocks must list 2 or more {from_ticks, to_ticks} in the order they should play")
    spans = [(int(_ticks(b.get("from_ticks"), "from_ticks")), int(_ticks(b.get("to_ticks"), "to_ticks")))
             if isinstance(b, dict) else (0, 0) for b in blocks]
    tiled = sorted(spans)
    if any(t <= f for f, t in spans) or any(a[1] != b[0] for a, b in zip(tiled, tiled[1:])):
        raise ValueError("blocks must cover one stretch exactly, each once, with no gap or overlap "
                         "(drop pieces first with premiere_keep_words or premiere_cut_copy)")
    return {"sequence": args["sequence"], "result_name": args["result_name"], "blocks": spans}


CLONE_BATCH = 40  # blocks per clone transaction: a 40-piece Short reordered in one (live 2026-11-26)


def arrange_steps(blocks: list[tuple[int, int]], park: int) -> list[dict]:
    """build_sequence `into` steps that play `blocks` back to back, in this order, from the start of
    the stretch they tile: clone every block to the park in its new order (one transaction per CLONE_BATCH blocks), lift
    the stretch, clone the park back, lift the park: four steps up to CLONE_BATCH blocks, one more per CLONE_BATCH after that. Clone,
    never move (PREMIERE_FACTS "createMoveAction of a block backward")."""
    start = min(f for f, _ in blocks)
    end = max(t for _, t in blocks)
    ranges, at = [], park
    for f, t in blocks:
        ranges.append({"from_ticks": str(f), "to_ticks": str(t), "dt_ticks": str(at - f)})
        at += t - f
    # Handles can go stale partway through a big transaction (PREMIERE_FACTS "mid-batch"), so past
    # CLONE_BATCH blocks the park clone is split, each step from a fresh read; 40 blocks were live-proven.
    clones = [{"op": "clone", **chunk[0], "ranges": chunk[1:]}
              for chunk in (ranges[i:i + CLONE_BATCH] for i in range(0, len(ranges), CLONE_BATCH))]
    return [*clones,
            {"op": "lift", "from_ticks": str(start), "to_ticks": str(end)},
            {"op": "clone", "from_ticks": str(park), "to_ticks": str(at), "dt_ticks": str(start - park)},
            {"op": "lift", "from_ticks": str(park), "to_ticks": str(at)}]


def _arranged(clips: list[tuple], blocks: list[tuple[int, int]]) -> list[tuple]:
    """Where every clip should sit once the blocks play in their new order."""
    shift, at = {}, min(f for f, _ in blocks)
    for f, t in blocks:
        shift[(f, t)] = at - f
        at += t - f
    def moved(c):
        k, n, s, e = c
        block = next((b for b in blocks if b[0] <= s < b[1]), None)
        return (k, n, s + shift[block], e + shift[block]) if block else c
    return sorted(moved(c) for c in clips)


async def _arrange(args: dict, premiere: Premiere) -> dict:
    blocks = args["blocks"]
    source = await premiere("read_timeline", {"sequence": args["sequence"]})
    start, end = min(f for f, _ in blocks), max(t for _, t in blocks)
    crossing = [c for c in _clips(source) if (c[2] < start < c[3]) or (c[2] < end < c[3])
                or any(f <= c[2] < t < c[3] for f, t in blocks)]
    if crossing:
        raise ValueError(f"these clips cross a block edge; cut there first (Add Edit) or move the edge: {crossing[:10]}")
    expected = _arranged(_clips(source), blocks)
    await premiere("duplicate_sequence", {"sequence_name": args["sequence"], "result_name": args["result_name"]})
    park = max(int(source["end_ticks"]), end) + PARK_GAP_TICKS
    project = (await premiere("list_project", {"depth": 1}))["path"]
    await premiere("build_sequence", {"project": project, "base": args["result_name"], "name": args["result_name"],
                                      "items": [], "options": {"into": True, "steps": arrange_steps(blocks, park)}})
    after = _clips(await premiere("read_timeline", {"sequence": args["result_name"]}))
    return {"sequence": args["result_name"], "blocks": [[str(f), str(t)] for f, t in blocks],
            "missing": sorted(set(expected) - set(after)), "unexpected": sorted(set(after) - set(expected))}


MAX_PIECES = 500
# paste_from calls into each target in this helper's life. A Short built piece by piece crashed
# Premiere about every 20 pastes (PREMIERE_FACTS "Short built piece by piece"); past
# PER_PIECE_FREE pastes into one target, paste_from wants a reason, and returns it as `fallback`.
_PASTES_INTO: dict[str, int] = {}
PER_PIECE_FREE = 2


def _paste_pieces_arguments(args: dict, jobs) -> dict:
    result = {}
    for key in ("source", "target"):
        if not isinstance(args.get(key), str) or not args[key].strip():
            raise ValueError(f"{key} must be a sequence name")
        result[key] = args[key]
    template = args.get("template") or ""
    if not isinstance(template, str):
        raise ValueError("template must be a sequence name, or left out to paste into target as it is")
    if result["target"] in (result["source"], template):
        raise ValueError("target must differ from source and template (those are never edited)")
    pieces = args.get("pieces")
    if not isinstance(pieces, list) or not 1 <= len(pieces) <= MAX_PIECES:
        raise ValueError(f"pieces must list 1 to {MAX_PIECES} {{from_ticks, to_ticks}} of the source, in play order")
    spans = [(int(_ticks(p.get("from_ticks"), "from_ticks")), int(_ticks(p.get("to_ticks"), "to_ticks")))
             if isinstance(p, dict) else (0, 0) for p in pieces]
    ordered = sorted(spans)
    if any(t <= f for f, t in spans) or any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("pieces must not overlap, and each must end after it starts")
    return {**result, "template": template, "pieces": spans, "at_ticks": _ticks(args.get("at_ticks", "0"), "at_ticks")}


# Premiere keeps what each cut used until it quits (PREMIERE_FACTS "memory held after the cut"):
# a 40-piece paste_pieces took up to 3.1 GB, and 17 in one session left 0.6 GB of commit (live
# 2026-11-26). Below this much free commit a build is refused instead of crashing Premiere.
MIN_COMMIT_FREE_GB = 8.0


def _commit_free_gb() -> float | None:
    """Commit memory Windows can still hand out (GlobalMemoryStatusEx ullAvailPageFile); None off Windows."""
    if sys.platform != "win32":
        return None
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ("phys", "phys_free", "commit", "commit_free", "virtual", "virtual_free", "ext")]

    status = Status(length=ctypes.sizeof(Status))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.commit_free / 2**30


def _with_in(timeline: dict) -> list[tuple[str, int, int, int, int]]:
    """(V|A, track number, start, end, source in) of every clip."""
    return sorted((t["id"][0], int(t["id"][1:]), int(c["start_ticks"]), int(c["end_ticks"]), int(c.get("in_ticks", 0)))
                  for t in timeline["tracks"] for c in t["clips"])


async def _remove_temporaries(premiere: Premiere, show: str, temps: list[str]) -> list[str]:
    """Remove this run's temporaries and the pieces paste_from cut from them; return what is left.
    Premiere won't remove the active sequence (a failed paste leaves a piece active), so `show` is
    opened first."""
    try:
        await premiere("open_sequence", {"sequence": show})
        made = [s["name"] for s in (await premiere("list_project", {"depth": 1}))["sequences"]
                if s["name"].endswith(PIECE_SUFFIX) and any(s["name"].startswith(f"{t} ") for t in temps)]
    except Exception:  # noqa: BLE001 - the build's own error is the one to report
        made = []
    left = []
    for temp in dict.fromkeys(temps + made):
        try:
            await premiere("remove_piece", {"name": temp})
        except Exception:  # noqa: BLE001 - reported as left, below the build's own result
            left.append(temp)
    return left


async def _paste_pieces(args: dict, premiere: Premiere) -> dict:
    """Fixed cost whatever the piece count: make_subsequence of the span, cut_copy to the pieces,
    arrange into play order (four steps up to CLONE_BATCH pieces), one paste_from of the whole into the target (a new copy
    of the template when one is given); every temporary sequence removed. Never falls back to a
    piece-by-piece route."""
    parent, template, name, pieces = args["source"], args["template"], args["target"], args["pieces"]
    at = int(args["at_ticks"])
    free = _commit_free_gb()
    if free is not None and free < MIN_COMMIT_FREE_GB:
        raise ValueError(f"only {free:.1f} GB of memory left to commit; Premiere keeps what every cut used until it "
                         "quits, and a build now could crash it. Save, restart Premiere, then run again.")
    names = {s["name"] for s in (await premiere("list_project", {"depth": 1}))["sequences"]}
    exists = name in names
    if template and template not in names:
        raise ValueError(f"no template sequence {template!r}")
    if template and exists:
        raise ValueError(f"{name!r} already exists; with a template, paste_pieces makes target as a new copy of it")
    if not template and not exists:
        raise ValueError(f"no sequence {name!r}; name an existing target, or give a template to copy")
    a, b = min(f for f, _ in pieces), max(t for _, t in pieces)
    source = await premiere("read_timeline", {"sequence": parent, "from_ticks": str(a), "to_ticks": str(b)})
    tpf = int(source["ticks_per_frame"])
    if any(x % tpf for p in pieces for x in p):
        raise ValueError(f"every piece edge must sit on a frame of {parent!r} ({tpf} ticks)")
    inside = [c for c in _clips(source) if c[2] < b and c[3] > a]
    if not inside or min(c[2] for c in inside) > a:
        raise ValueError(f"the first piece must start on a clip of {parent!r} (Make Subsequence drops a leading gap)")
    # cut_copy splits clips only where it cuts, so a clip across an edge two pieces share stays whole,
    # and arrange can't reorder across it. Pieces that still follow each other play as one.
    runs: list[tuple[int, int]] = []
    for f, t in pieces:
        if runs and runs[-1][1] == f:
            runs[-1] = (runs[-1][0], t)
        else:
            runs.append((f, t))
    across = sorted(x for x in {t for _, t in runs} & {f for f, _ in runs} if any(c[2] < x < c[3] for c in inside))
    if across:
        raise ValueError(f"two pieces meet at {across[0]} ticks, inside a clip of {parent!r}, and play in a new order: "
                         "leave a frame between them, or cut the clip there first (Add Edit)")
    await premiere("save_project", {})
    temps: list[str] = []
    made_target = False
    try:
        span = f"{name} span{PIECE_SUFFIX}"
        await premiere("make_subsequence", {"sequence": parent, "in_ticks": str(a), "out_ticks": str(b), "result_name": span})
        temps.append(span)
        kept = sorted((f - a, t - a) for f, t in runs)
        edges = [0] + [x for k in kept for x in k] + [b - a]
        cuts = [[f // tpf, t // tpf] for f, t in zip(edges[::2], edges[1::2]) if t > f]
        cut = span
        if cuts:
            cut = f"{name} cut{PIECE_SUFFIX}"
            await premiere("cut_copy", {"sequence_name": span, "result_name": cut,
                                        "cuts": {"ticks_per_frame": str(tpf), "cuts_frames": cuts}})
            temps.append(cut)
        where, end = {}, 0
        for f, t in kept:
            where[(f, t)] = (end, end + t - f)
            end += t - f
        blocks = [where[(f - a, t - a)] for f, t in runs]
        whole = cut
        if blocks != sorted(blocks):
            whole = f"{name} order{PIECE_SUFFIX}"
            temps.append(whole)
            arranged = await _arrange({"sequence": cut, "result_name": whole, "blocks": blocks}, premiere)
            if arranged["missing"] or arranged["unexpected"]:
                raise ValueError(f"the reorder did not land: missing {arranged['missing'][:5]}, unexpected {arranged['unexpected'][:5]}")
        if template:
            await premiere("duplicate_sequence", {"sequence_name": template, "result_name": name})
            made_target = True
        own = _with_in(await premiere("read_timeline", {"sequence": name}))
        temps.append(_piece_name(whole, 0, end))  # paste_from keeps it; removed below with the rest
        pasted = await _paste_from({"source": whole, "target": name, "in_ticks": "0", "out_ticks": str(end),
                                    "at_ticks": str(at), "v_offset": 0, "keep_piece": True}, premiere)
        if pasted["missing"] or pasted["left_at_park"]:
            raise ValueError(f"the paste into {name!r} did not land: missing {pasted['missing'][:5]}, "
                             f"left at the park {pasted['left_at_park'][:5]}")
    except Exception as exc:
        left = await _remove_temporaries(premiere, parent, temps)
        note = f" ({name!r} was made from the template and is only partly built: delete it before running again)" if made_target else ""
        if left:
            note += f" (left in the project, remove by hand: {left})"
        raise ValueError(f"{exc}{note}") from exc
    left = await _remove_temporaries(premiere, name, temps)
    plan, shift = [], at
    for f, t in runs:
        plan += [(k, n, max(s, f) - f + shift, min(e, t) - f + shift) for k, n, s, e in inside if s < t and e > f]
        shift += t - f
    # What is left of a target clip the paste overwrote is the target's own, not a pasted one.
    built = [c[:4] for c in _with_in(await premiere("read_timeline", {"sequence": name}))
             if not any(o[:2] == c[:2] and o[2] <= c[2] and c[3] <= o[3] and c[4] - o[4] == c[2] - o[2] for o in own)]
    await premiere("save_project", {})
    return {"sequence": name, "pieces": len(pieces), "length_ticks": str(end),
            "missing": sorted(set(plan) - set(built))[:50], "unexpected": sorted(set(built) - set(plan))[:50],
            "temporaries_removed": [t for t in temps if t not in left], "temporaries_left": left}


async def _paste_from_guarded(args: dict, premiere: Premiere) -> dict:
    target = args["target"]
    done = _PASTES_INTO.get(target, 0)
    reason = args.get("per_piece_reason")
    if done >= PER_PIECE_FREE and not reason:
        raise ValueError(f"paste_from has already put {done} pieces into {target!r}. Several pieces go in with "
                         "premiere_paste_pieces (a fixed number of edits whatever the piece count); piece by piece "
                         "crashed Premiere about every 20 pastes. To go on piece by piece anyway, pass "
                         "per_piece_reason: it is logged and returned as `fallback`.")
    result = await _paste_from(args, premiere)
    _PASTES_INTO[target] = done + 1  # only a paste that went in counts
    return {**result, "fallback": reason} if reason else result


COMMANDS: dict[str, Command] = {
    "paste_from": Command(
        900, _paste_from_arguments, "write",
        """
        Take the range [in_ticks, out_ticks) of sequence `source` (a split, the backup pool, a
        finished YT cut) and put it into sequence `target` at at_ticks as real clips: every
        track, effect, mask and Lumetri kept, as the user would copy and paste. It OVERWRITES what
        is under it on those tracks. v_offset puts the video that many tracks higher than in the
        source (audio stays on its own tracks). The source is never edited. Route: Make
        Subsequence of the range, Edit > Copy, Edit > Paste parked 30 s past the target's end,
        then clone into place and lift the park; the temporary piece sequence is deleted unless
        keep_piece. Returns `missing` (expected clips not found at the place; empty = landed
        frame-exact) and `left_at_park` (should be empty). Needs the CutDeck panel open; takes
        Premiere's focus briefly. For one insert: several pieces go in with
        premiere_paste_pieces. A third paste into the same target is refused unless
        per_piece_reason says why; the reason comes back as `fallback`.
        """,
        (("source", str), ("in_ticks", str), ("out_ticks", str), ("target", str), ("at_ticks", str),
         ("v_offset", int, 0), ("keep_piece", bool, False), ("per_piece_reason", str | None, None)),
        run=_paste_from_guarded, routes=("uxp", "menu")),
    "paste_pieces": Command(
        1800, _paste_pieces_arguments, "write",
        """
        The default way to copy several pieces of one sequence into another (a Short from yt, hook
        pieces into a draft, a pool from a split): the `source` pieces [{from_ticks, to_ticks}]
        (source ticks, on frames, no overlap) play back to back in the order given in `target`
        from at_ticks (default 0), overwriting what is there. With `template` (a Short's 9:16
        sequence) target is made as a NEW copy of it; without, target must exist and is edited in
        place. Every track, effect, keyframe and Graphic of the source is kept as real clips (no
        nest). Fixed cost whatever the piece count: Make Subsequence of the span, cut_copy to the
        pieces, one reorder, one paste; the temporary sequences are removed and the project is
        saved before and after. Returns `missing` and `unexpected` clips against the plan (both
        empty = frame-exact). It never falls back to pasting piece by piece: on any failure it
        stops and says where. For one piece, premiere_paste_from.
        """,
        (("source", str), ("target", str), ("pieces", list[dict]), ("template", str, ""),
         ("at_ticks", str, "0")),
        run=_paste_pieces, routes=("uxp", "menu")),
    "arrange": Command(
        900, _arrange_arguments, "write",
        """
        Reorder pieces of a sequence on a COPY named result_name (the source is never edited):
        `blocks` [{from_ticks, to_ticks}] in the order they should play. Together they must cover
        one stretch exactly (drop pieces first with premiere_keep_words or premiere_cut_copy), and
        every clip must start and end inside one block (cut at the edges first). Every track,
        effect and hand fix moves with its block; what lies outside the stretch stays put. Returns
        `missing` and `unexpected` clips against the planned layout (both empty = exact).
        """,
        (("sequence", str), ("result_name", str), ("blocks", list[dict])),
        run=_arrange),
}
