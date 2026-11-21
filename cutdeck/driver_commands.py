"""The one table of commands the CutDeck panel drives in live Premiere.

The rule every command keeps: it runs as one Premiere transaction, or on a copy of the
sequence, and returns what it changed. Nothing here edits the user's original in steps.

A new command is: one entry in COMMANDS, its handler in `uxp/cutdeck/features/driver.js`
(with its name in that file's COMMANDS array) and one `premiere_<name>` MCP tool in
`cutdeck/mcp_server.py`. The helper's dispatch, `premiere_cli` and `ai_backend.capabilities`
read this table; `tests/test_cutdeck_driver_commands.py` fails if the pieces drift apart.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from cutdeck import assistant, keys, menu, screenshot
from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND

MAX_MARKERS = 5000


# Runs one command through the helper and returns its result: the helper's own dispatch, or
# `Backend().premiere` in a script.
Premiere = Callable[[str, dict], Awaitable]


@dataclass(frozen=True)
class Command:
    timeout_s: int
    # (args the caller sent, job lookup) -> the arguments the command receives
    prepare: Callable[[dict, Callable[[str], dict]], dict]
    doc: str
    # None: takes no CLI argument. Else (usage word, text from the CLI -> args for the command)
    cli_target: tuple[str, Callable[[str], dict]] | None = None
    # None: the CutDeck panel runs it. Else the helper runs it (Win32 routes: menu, keys, window
    # pixels, Adobe's AI Assistant), with `premiere` for any panel command it needs on the way.
    run: Callable[[dict, Premiere], Awaitable] | None = None


def _seconds_to_ticks(value, name: str) -> str:
    if type(value) not in (int, float) or not 0 <= value < 1e6:
        raise ValueError(f"{name} must be a number of seconds from 0")
    return str(round(value * PPRO_TICKS_PER_SECOND))


def _no_arguments(args: dict, jobs) -> dict:
    return {}


def _apply_cuts_arguments(args: dict, jobs) -> dict:
    job = jobs(args.get("job_id"))
    if job.get("job_type") != "cut" or job["state"] != "ready" or not job.get("cuts"):
        raise ValueError("apply_cuts needs a finished rough cut job with cuts")
    context = job.get("context") or {}
    return {"cuts": job["cuts"], "sequence_id": context.get("sequence_id"),
            "sequence_name": context.get("sequence_name"),
            "result_name": job.get("result_name") or f"CutDeck rough cut {job['job_id'][:8]}"}


def _marker_arguments(args: dict, jobs) -> dict:
    """Validate `add_markers`; the panel gets exact ticks, never float seconds."""
    markers = args.get("markers")
    if not isinstance(markers, list) or not 0 < len(markers) <= MAX_MARKERS:
        raise ValueError(f"markers must be a list of 1 to {MAX_MARKERS} markers")
    result = []
    for marker in markers:
        if not isinstance(marker, dict):
            raise ValueError("Each marker must be an object")
        name, comment = marker.get("name", ""), marker.get("comment", "")
        if not isinstance(name, str) or len(name) > 200 or not isinstance(comment, str) or len(comment) > 2000:
            raise ValueError("Marker name (max 200) and comment (max 2000) must be text")
        result.append({"start_ticks": _seconds_to_ticks(marker.get("start_s"), "start_s"),
                       "duration_ticks": _seconds_to_ticks(marker.get("duration_s", 0), "duration_s"),
                       "name": name, "comment": comment})
    return {"markers": result}


def _run_probe_arguments(args: dict, jobs) -> dict:
    probe = args.get("probe")
    valid = {"timing", "motion", "effect", "transform", "keyframe", "alcreate", "syncmoves", "nativecut", "mutestate", "textcanvas", "captiontiming",
             "hks1a", "hks1b", "hks1c", "hks1d", "hks1e"}  # HKS build plan Phase 1 spike (hksSpikeProbe.js)
    if not isinstance(probe, str) or probe not in valid:
        raise ValueError(f"probe must be one of: {', '.join(sorted(valid))}")
    return {"probe": probe}


MAX_BUILD_ITEMS = 5000


def _build_arguments(args: dict, jobs) -> dict:
    """Validate `build_sequence`: the open project, a base sequence to copy, a new name, the items
    to place, and `save` (opt-in: save the project after the build)."""
    project, base, name, items = args.get("project"), args.get("base"), args.get("name"), args.get("items")
    if not isinstance(project, str) or not project.lower().endswith(".prproj") or not Path(project).is_absolute():
        raise ValueError("project must be the absolute path of the open .prproj (the panel refuses any other)")
    save = args.get("save", False)
    if not isinstance(save, bool):
        raise ValueError("save must be true or false")
    if not isinstance(base, str) or not base.strip() or not isinstance(name, str) or not name.strip():
        raise ValueError("base and name must be sequence names")
    if not isinstance(items, list) or not 0 < len(items) <= MAX_BUILD_ITEMS:
        raise ValueError(f"items must be a list of 1 to {MAX_BUILD_ITEMS} items")
    for it in items:
        if not isinstance(it, dict) or not (isinstance(it.get("media"), str) or isinstance(it.get("like"), dict)):
            raise ValueError("Each item needs media (a file path) or like ({kind, track, start_ticks})")
        for key in ("in_ticks", "out_ticks", "at_ticks"):
            if not isinstance(it.get(key), str) or not it[key].isdigit():
                raise ValueError(f"{key} must be a tick count as a string")
        if int(it["out_ticks"]) <= int(it["in_ticks"]):
            raise ValueError("out_ticks must be after in_ticks")
        if it.get("v") is None and it.get("a") is None:
            raise ValueError("Each item needs a video track v or an audio track a")
    result = {"project": project, "base": base, "name": name, "items": items, "save": save}
    off = args.get("disable_tracks")
    if off is not None:
        if not isinstance(off, dict) or set(off) - {"video", "audio"} or not all(
                isinstance(v, list) and all(isinstance(i, int) and i >= 0 for i in v) for v in off.values()):
            raise ValueError("disable_tracks must be {video: [track index], audio: [track index]}")
        result["disable_tracks"] = off
    into = args.get("into", False)
    if not isinstance(into, bool):
        raise ValueError("into must be true or false")
    if into:
        if name != base:
            raise ValueError("into edits the base sequence itself: name must equal base")
        result["into"] = True
        settings_from = args.get("settings_from")
        if settings_from is not None:
            if not isinstance(settings_from, str) or not settings_from.strip():
                raise ValueError("settings_from must be a sequence name")
            result["settings_from"] = settings_from
        steps = args.get("steps", [])
        if not isinstance(steps, list) or not all(isinstance(st, dict) and st.get("op") in ("lift", "clone", "move", "trim")
                and all(isinstance(st.get(k), str) and st[k].isdigit() for k in ("from_ticks", "to_ticks"))
                and int(st["to_ticks"]) > int(st["from_ticks"])
                and (st["op"] == "lift"
                     or (st["op"] == "trim" and isinstance(st.get("end_ticks"), str) and st["end_ticks"].isdigit())
                     or (isinstance(st.get("dt_ticks"), str) and st["dt_ticks"].lstrip("-").isdigit()))
                and (st.get("tracks") is None or (isinstance(st["tracks"], dict) and not set(st["tracks"]) - {"video", "audio"}
                     and all(isinstance(v, list) and all(isinstance(i, int) and i >= 0 for i in v) for v in st["tracks"].values())))
                for st in steps):
            raise ValueError("steps must be [{op: lift|clone|move|trim, from_ticks, to_ticks, dt_ticks (clone/move), end_ticks (trim), "
                             "tracks? {video: [index], audio: [index]}}]")
        result["steps"] = steps
        restyle = args.get("restyle", [])
        if not isinstance(restyle, list) or not all(isinstance(r, dict) and r.get("kind") in ("video", "audio")
                and isinstance(r.get("track"), int) and r["track"] >= 0
                and all(isinstance(r.get(k), str) and r[k].isdigit() for k in ("from_ticks", "to_ticks"))
                and isinstance(r.get("enabled", True), bool) and isinstance(r.get("motion", {}), dict) for r in restyle):
            raise ValueError("restyle must be [{kind, track, from_ticks, to_ticks, enabled?, motion?}]")
        result["restyle"] = restyle
    elif any(k in args for k in ("settings_from", "steps", "restyle")):
        raise ValueError("settings_from, steps and restyle need into: true")
    media_from = args.get("media_from", [])
    if not isinstance(media_from, list) or not all(isinstance(n, str) and n.strip() for n in media_from):
        raise ValueError("media_from must be a list of sequence names")
    if media_from:
        result["media_from"] = media_from
    mark_whole = args.get("mark_whole", False)
    if not isinstance(mark_whole, bool):
        raise ValueError("mark_whole must be true or false")
    if mark_whole:
        result["mark_whole"] = True
    return result


def _cut_copy_arguments(args: dict, jobs) -> dict:
    """Validate `cut_copy`: a source sequence name, a new name, and frame cuts at the source's rate."""
    source, result_name, cuts = args.get("sequence_name"), args.get("result_name"), args.get("cuts")
    if not isinstance(source, str) or not source.strip() or not isinstance(result_name, str) or not result_name.strip():
        raise ValueError("sequence_name and result_name must be sequence names")
    if source == result_name:
        raise ValueError("result_name must differ from sequence_name (the source is never edited)")
    if not isinstance(cuts, dict) or not str(cuts.get("ticks_per_frame", "")).isdigit():
        raise ValueError("cuts must be {ticks_per_frame, cuts_frames}")
    frames = cuts.get("cuts_frames")
    if not isinstance(frames, list) or not frames or not all(
            isinstance(c, list) and len(c) == 2 and all(isinstance(x, int) for x in c) and 0 <= c[0] < c[1] for c in frames):
        raise ValueError("cuts_frames must be [[start, end], ...] whole frames, end after start")
    if any(b[0] < a[1] for a, b in zip(frames, frames[1:])):
        raise ValueError("cuts_frames must be sorted and must not overlap")
    return {"sequence_name": source, "result_name": result_name,
            "cuts": {"ticks_per_frame": str(cuts["ticks_per_frame"]), "cuts_frames": frames}}


def _create_sequence_arguments(args: dict, jobs) -> dict:
    """Validate `create_sequence`: a new sequence name and an existing .sqpreset file."""
    name, preset = args.get("name"), args.get("preset_path")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a sequence name")
    if not isinstance(preset, str) or not preset.lower().endswith(".sqpreset") or not Path(preset).is_file():
        raise ValueError("preset_path must be an existing .sqpreset file")
    return {"name": name, "preset_path": preset}


def _export_sequence_arguments(args: dict, jobs) -> dict:
    """Export the active sequence with a Media Encoder preset to a new file (never overwrites)."""
    output, preset = args.get("output_file"), args.get("preset_file")
    if not isinstance(output, str) or not Path(output).is_absolute():
        raise ValueError("output_file must be an absolute path")
    if not isinstance(preset, str) or not preset.lower().endswith(".epr") or not Path(preset).is_file():
        raise ValueError("preset_file must be an existing .epr file")
    if not Path(output).parent.is_dir():
        raise ValueError(f"output folder does not exist: {Path(output).parent}")
    if Path(output).exists():
        raise ValueError(f"output_file already exists: {output}")
    queue = args.get("queue", "premiere")
    if queue not in ("premiere", "ame"):
        raise ValueError("queue must be 'premiere' (render now in Premiere) or 'ame' (add to Media Encoder's queue)")
    start = args.get("start", True)
    if not isinstance(start, bool):
        raise ValueError("start must be true or false")
    # start: with queue "ame", also start Media Encoder's queue (false = only add the job)
    result = {"output_file": output, "preset_file": preset, "queue": queue, "start": start}
    name = args.get("sequence_name")
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("sequence_name must be a sequence name")
        result["sequence_name"] = name
    return result


VALID_TRANSFORM_FIELDS ={"position-x", "position-y", "scale", "rotation", "anchor-x", "anchor-y"}
VALID_ANCHOR_TARGETS = {"top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"}
VALID_ALIGN_EDGES = {"left", "hcenter", "right", "top", "vcenter", "bottom"}
VALID_ALIGN_TO = {"frame", "selection"}
VALID_DISTRIBUTE_KINDS = {"h-centers", "v-centers", "h-gaps", "v-gaps"}
VALID_DISTRIBUTE_TO = {"frame", "selection"}


def _set_transform_field_arguments(args: dict, jobs) -> dict:
    field = args.get("field")
    if not isinstance(field, str) or field not in VALID_TRANSFORM_FIELDS:
        raise ValueError(f"field must be one of: {', '.join(sorted(VALID_TRANSFORM_FIELDS))}")
    value = args.get("value")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("value must be specified")
    try:
        val_num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"value must be a number, got {value!r}")
    return {"field": field, "value": val_num}


def _parse_field_target(target: str) -> dict:
    if "=" not in target:
        raise ValueError("target must be in field=value format (e.g. scale=120 or position-x=960)")
    k, v = target.split("=", 1)
    return {"field": k.strip(), "value": float(v.strip())}


def _layer_argument(args: dict) -> dict:
    """Optional text layer (0-based) of a multi-text Graphic; absent = the whole Graphic."""
    layer = args.get("layer")
    if layer is None:
        return {}
    if isinstance(layer, bool) or not isinstance(layer, int) or layer < 0:
        raise ValueError(f"layer must be a text layer index (0, 1, ...), got {layer!r}")
    return {"layer": layer}


def _set_anchor_arguments(args: dict, jobs) -> dict:
    target = args.get("target")
    if not isinstance(target, str) or target not in VALID_ANCHOR_TARGETS:
        raise ValueError(f"target must be one of: {', '.join(sorted(VALID_ANCHOR_TARGETS))}")
    return {"target": target, **_layer_argument(args)}


def _parse_anchor_target(target: str) -> dict:
    parts = target.strip().split()
    return {"target": parts[0], **({"layer": int(parts[1])} if len(parts) > 1 else {})}


def _align_clips_arguments(args: dict, jobs) -> dict:
    edge = args.get("edge")
    if not isinstance(edge, str) or edge not in VALID_ALIGN_EDGES:
        raise ValueError(f"edge must be one of: {', '.join(sorted(VALID_ALIGN_EDGES))}")
    to = args.get("to", "frame")
    if not isinstance(to, str) or to not in VALID_ALIGN_TO:
        raise ValueError(f"to must be one of: {', '.join(sorted(VALID_ALIGN_TO))}")
    return {"edge": edge, "to": to, **_layer_argument(args)}


def _parse_align_target(target: str) -> dict:
    parts = target.strip().split()
    edge = parts[0]
    to = parts[1] if len(parts) > 1 else "frame"
    return {"edge": edge, "to": to, **({"layer": int(parts[2])} if len(parts) > 2 else {})}


def _distribute_clips_arguments(args: dict, jobs) -> dict:
    kind = args.get("kind")
    if not isinstance(kind, str) or kind not in VALID_DISTRIBUTE_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(VALID_DISTRIBUTE_KINDS))}")
    to = args.get("to", "frame")
    if not isinstance(to, str) or to not in VALID_DISTRIBUTE_TO:
        raise ValueError(f"to must be one of: {', '.join(sorted(VALID_DISTRIBUTE_TO))}")
    return {"kind": kind, "to": to}


def _parse_distribute_target(target: str) -> dict:
    parts = target.strip().split()
    kind = parts[0]
    to = parts[1] if len(parts) > 1 else "frame"
    return {"kind": kind, "to": to}


# apply_cuts edits a copy of a long sequence: 1735 cuts took minutes live (ledger 09-24).
COMMANDS: dict[str, Command] = {
    "read_sequence": Command(60, _no_arguments, "Read the active sequence."),
    "read_audio_range": Command(60, _no_arguments, "Read marked range and source audio clips without editing Premiere."),
    "apply_cuts": Command(1800, _apply_cuts_arguments,
                          "Apply a finished rough cut job to a copy of the active sequence.",
                          ("job_id", lambda target: {"job_id": target})),
    "add_markers": Command(120, _marker_arguments, "Add markers to the active sequence.",
                           ("JSON file", lambda target: {
                               "markers": json.loads(Path(target).read_text(encoding="utf-8"))})),
    "run_probe": Command(300, _run_probe_arguments, "Run one diagnostic probe in live Premiere.",
                         ("probe_name", lambda target: {"probe": target})),
    "inspect_selection": Command(30, _no_arguments,
                                 "Inspect the selected track item(s) on the active sequence in live Premiere."),
    "set_transform_field": Command(30, _set_transform_field_arguments,
                                   "Set a transform field (position-x, position-y, scale, rotation, anchor-x, anchor-y) on selected clips.",
                                   ("field=value", _parse_field_target)),
    "set_anchor": Command(30, _set_anchor_arguments,
                          "Set 9-point anchor target on selected clips while preserving picture position.",
                          ("target [layer]", _parse_anchor_target)),
    "align_clips": Command(30, _align_clips_arguments,
                           "Align selected clips to sequence frame or selection bounding box.",
                           ("edge [to] [layer]", _parse_align_target)),
    "distribute_clips": Command(30, _distribute_clips_arguments,
                                "Distribute 3+ selected clips across frame or within selection.",
                                ("kind [to]", _parse_distribute_target)),
    # Builds a new sequence on a cleared copy of `base` (never edits it); minutes for hundreds of items.
    "build_sequence": Command(3600, _build_arguments,
                              "Build a new sequence from an item list on a cleared copy of a base sequence.",
                              ("JSON file", lambda target: json.loads(Path(target).read_text(encoding="utf-8")))),
    "reload_panel": Command(30, _no_arguments,
                            "Reload the CutDeck panel so it loads changed code; it reconnects by itself."),
    # Renders inside Premiere (ExportType.IMMEDIATELY); a long form can take many minutes.
    "cut_copy": Command(1800, _cut_copy_arguments,
                        "Copy a named sequence and cut frame ranges out of the copy (Rough Cut engine)."),
    "create_sequence": Command(30, _create_sequence_arguments,
                               "Create a new empty sequence from a sequence preset (.sqpreset)."),
    "export_sequence": Command(3600, _export_sequence_arguments,
                               "Export the active sequence with a Media Encoder preset (.epr) to a new file.",
                               ("JSON file", lambda target: json.loads(Path(target).read_text(encoding="utf-8")))),
}


# General control (uxp/cutdeck/timeline/control.js; route map docs/PREMIERE_CONTROL_MAP.md).
# Times are tick strings; a clip is "V<n>@<start_ticks>" / "A<n>@<start_ticks>" as read_timeline
# prints it; a track is "V<n>" / "A<n>" (1-based, as Premiere shows them).
_CLIP_ID = re.compile(r"[VA][1-9]\d*@\d+")
_TRACK_ID = re.compile(r"[VA][1-9]\d*")
EDIT_OPS = {"move": "dt_ticks", "trim_in": "in_ticks", "trim_out": "out_ticks", "rename": "name",
            "enable": None, "disable": None, "remove": None}
MAX_CONTROL_ITEMS = 5000


def _ticks(value, name: str, signed: bool = False) -> str:
    if not (isinstance(value, str) and re.fullmatch(r"-?\d+" if signed else r"\d+", value)):
        raise ValueError(f"{name} must be a tick string{' (may be negative)' if signed else ''}")
    return value


def _sequence(args: dict) -> dict:
    name = args.get("sequence")
    if name is None:
        return {}
    if not isinstance(name, str) or not name.strip():
        raise ValueError("sequence must be a sequence name (omit it for the active sequence)")
    return {"sequence": name}


def _clip_ids(value, name: str = "clips", allow_empty: bool = False) -> list:
    if not isinstance(value, list) or not (allow_empty or value) or len(value) > MAX_CONTROL_ITEMS \
            or not all(isinstance(c, str) and _CLIP_ID.fullmatch(c) for c in value):
        raise ValueError(f"{name} must be a list of clip ids like V1@0 (from premiere_read_timeline)")
    return value


def _read_timeline_arguments(args: dict, jobs) -> dict:
    effects = args.get("effects", False)
    if effects not in (False, "names", "params"):
        raise ValueError('effects must be false, "names" or "params"')
    result = {**_sequence(args), "effects": effects}
    tracks = args.get("tracks")
    if tracks is not None:
        if not isinstance(tracks, list) or not tracks or not all(isinstance(t, str) and _TRACK_ID.fullmatch(t) for t in tracks):
            raise ValueError('tracks must be a list like ["V1", "A2"]')
        result["tracks"] = tracks
    for key in ("from_ticks", "to_ticks"):
        if args.get(key) is not None:
            result[key] = _ticks(args[key], key)
    if "from_ticks" in result and "to_ticks" in result and int(result["to_ticks"]) <= int(result["from_ticks"]):
        raise ValueError("to_ticks must be after from_ticks")
    return result


def _list_project_arguments(args: dict, jobs) -> dict:
    depth = args.get("depth", 8)
    if type(depth) is not int or not 1 <= depth <= 32:
        raise ValueError("depth must be 1 to 32")
    return {"depth": depth}


def _open_sequence_arguments(args: dict, jobs) -> dict:
    if not isinstance(args.get("sequence"), str) or not args["sequence"].strip():
        raise ValueError("sequence must be a sequence name")
    return {"sequence": args["sequence"]}


def _set_playhead_arguments(args: dict, jobs) -> dict:
    return {**_sequence(args), "ticks": _ticks(args.get("ticks"), "ticks")}


def _set_in_out_arguments(args: dict, jobs) -> dict:
    result = _sequence(args)
    for key in ("in_ticks", "out_ticks"):
        if args.get(key) is not None:
            result[key] = _ticks(args[key], key)
    if "in_ticks" not in result and "out_ticks" not in result:
        raise ValueError("give in_ticks, out_ticks or both")
    if "in_ticks" in result and "out_ticks" in result and int(result["out_ticks"]) <= int(result["in_ticks"]):
        raise ValueError("out_ticks must be after in_ticks")
    return result


def _select_clips_arguments(args: dict, jobs) -> dict:
    return {**_sequence(args), "clips": _clip_ids(args.get("clips"), allow_empty=True)}


def _edit_clips_arguments(args: dict, jobs) -> dict:
    edits = args.get("edits")
    if not isinstance(edits, list) or not 0 < len(edits) <= MAX_CONTROL_ITEMS:
        raise ValueError(f"edits must be a list of 1 to {MAX_CONTROL_ITEMS} edits")
    out = []
    for e in edits:
        if not isinstance(e, dict) or e.get("op") not in EDIT_OPS:
            raise ValueError(f"each edit is {{clip, op}} with op one of: {', '.join(EDIT_OPS)}")
        _clip_ids([e.get("clip")], "clip")
        edit = {"clip": e["clip"], "op": e["op"]}
        field = EDIT_OPS[e["op"]]
        if field == "name":
            if not isinstance(e.get("name"), str) or not e["name"]:
                raise ValueError("rename needs a name")
            edit["name"] = e["name"]
        elif field:
            edit[field] = _ticks(e.get(field), field, signed=field == "dt_ticks")
        if e["op"] == "remove":
            if not isinstance(e.get("ripple", False), bool):
                raise ValueError("ripple must be true or false")
            edit["ripple"] = e.get("ripple", False)
        out.append(edit)
    if len({e["clip"] for e in out}) != len(out):
        raise ValueError("each clip may appear once per edit_clips call")
    return {**_sequence(args), "edits": out}


def _place_media_arguments(args: dict, jobs) -> dict:
    media, nest = args.get("media"), args.get("nest")
    if (media is None) == (nest is None):
        raise ValueError("give exactly one of media (a file path) or nest (a sequence name)")
    if media is not None and (not isinstance(media, str) or not Path(media).is_absolute() or not Path(media).is_file()):
        raise ValueError("media must be an existing file, absolute path")
    if nest is not None and (not isinstance(nest, str) or not nest.strip()):
        raise ValueError("nest must be a sequence name")
    for key in ("v", "a"):
        if type(args.get(key)) is not int or args[key] < 0:
            raise ValueError(f"{key} must be a 0-based track index (the track count creates a new track)")
    mode = args.get("mode", "overwrite")
    if mode not in ("overwrite", "insert"):
        raise ValueError("mode must be overwrite or insert")
    return {**_sequence(args), **({"media": media} if media is not None else {"nest": nest}),
            "at_ticks": _ticks(args.get("at_ticks"), "at_ticks"), "v": args["v"], "a": args["a"], "mode": mode}


def _add_effect_arguments(args: dict, jobs) -> dict:
    if not isinstance(args.get("effect"), str) or not args["effect"].strip():
        raise ValueError("effect must be a video match name or audio display name (premiere_list_effects)")
    return {**_sequence(args), "clips": _clip_ids(args.get("clips")), "effect": args["effect"]}


def _param_value(value):
    if type(value) in (int, float, bool, str):
        return value
    if isinstance(value, list) and len(value) == 2 and all(type(v) in (int, float) for v in value):
        return value
    raise ValueError("value must be a number, boolean, string or [x, y]")


def _set_param_arguments(args: dict, jobs) -> dict:
    component = args.get("component")
    if not ((type(component) is int and component >= 0) or (isinstance(component, str) and component.strip())):
        raise ValueError("component must be a chain index (0 Opacity, 1 Motion) or a match name")
    if type(args.get("param")) is not int or args["param"] < 0:
        raise ValueError("param must be a 0-based parameter index")
    _clip_ids([args.get("clip")], "clip")
    result = {**_sequence(args), "clip": args["clip"], "component": component, "param": args["param"],
              "value": _param_value(args.get("value"))}
    if args.get("at_ticks") is not None:
        result["at_ticks"] = _ticks(args["at_ticks"], "at_ticks")
    return result


def _add_transition_arguments(args: dict, jobs) -> dict:
    if not isinstance(args.get("transition"), str) or not args["transition"].strip():
        raise ValueError("transition must be a video transition match name (premiere_list_effects)")
    if not isinstance(args.get("at_start", False), bool):
        raise ValueError("at_start must be true or false")
    result = {**_sequence(args), "clips": _clip_ids(args.get("clips")), "transition": args["transition"],
              "at_start": args.get("at_start", False)}
    if args.get("duration_ticks") is not None:
        result["duration_ticks"] = _ticks(args["duration_ticks"], "duration_ticks")
    return result


def _set_track_mute_arguments(args: dict, jobs) -> dict:
    if not isinstance(args.get("track"), str) or not _TRACK_ID.fullmatch(args["track"]):
        raise ValueError("track must be like V1 or A2")
    if not isinstance(args.get("muted"), bool):
        raise ValueError("muted must be true or false")
    return {**_sequence(args), "track": args["track"], "muted": args["muted"]}


def _remove_markers_arguments(args: dict, jobs) -> dict:
    starts = args.get("starts_ticks")
    if not isinstance(starts, list) or not 0 < len(starts) <= MAX_MARKERS:
        raise ValueError("starts_ticks must be a list of marker start tick strings")
    return {**_sequence(args), "starts_ticks": [_ticks(t, "starts_ticks") for t in starts]}


def _import_files_arguments(args: dict, jobs) -> dict:
    paths = args.get("paths")
    if not isinstance(paths, list) or not 0 < len(paths) <= 500 or not all(
            isinstance(p, str) and Path(p).is_absolute() and Path(p).is_file() for p in paths):
        raise ValueError("paths must be 1 to 500 existing files, absolute paths")
    return {"paths": paths}


def _export_frame_arguments(args: dict, jobs) -> dict:
    result = _sequence(args)
    if args.get("ticks") is not None:
        result["ticks"] = _ticks(args["ticks"], "ticks")
    return result


CONTROL_COMMANDS: dict[str, Command] = {
    "read_timeline": Command(300, _read_timeline_arguments, "Read every track, clip, mark and marker of a sequence."),
    "list_project": Command(120, _list_project_arguments, "List the project's sequences and bin tree."),
    "open_sequence": Command(60, _open_sequence_arguments, "Open a sequence by name and make it active.",
                             ("sequence name", lambda target: {"sequence": target})),
    "set_playhead": Command(30, _set_playhead_arguments, "Move a sequence's playhead to a tick time.",
                            ("ticks", lambda target: {"ticks": target})),
    "set_in_out": Command(30, _set_in_out_arguments, "Set a sequence's In and/or Out marks."),
    "select_clips": Command(60, _select_clips_arguments, "Replace the timeline selection with these clips."),
    "edit_clips": Command(600, _edit_clips_arguments, "Move, trim, enable/disable, rename or remove clips in one undo step."),
    "place_media": Command(300, _place_media_arguments, "Overwrite or insert a media file, or nest a sequence, at a time."),
    "list_effects": Command(60, _no_arguments, "List video effect, audio effect and transition names."),
    "add_effect": Command(120, _add_effect_arguments, "Append an effect to clips."),
    "set_param": Command(60, _set_param_arguments, "Set an effect parameter, or add a keyframe, on a clip."),
    "add_transition": Command(120, _add_transition_arguments, "Add a video transition to clips."),
    "set_track_mute": Command(30, _set_track_mute_arguments, "Mute or unmute a track."),
    "remove_markers": Command(60, _remove_markers_arguments, "Remove sequence markers by start time."),
    "import_files": Command(600, _import_files_arguments, "Import files into the project root."),
    "save_project": Command(120, _no_arguments, "Save the open project."),
    "export_frame": Command(60, _export_frame_arguments, "Save a PNG of a sequence frame."),
}
COMMANDS.update(CONTROL_COMMANDS)


# Routes the UXP panel cannot take (docs/PREMIERE_CONTROL_MAP.md), run by the helper itself.
def _query_arguments(args: dict, jobs) -> dict:
    query = args.get("query", "")
    if not isinstance(query, str):
        raise ValueError("query must be text")
    return {"query": query}


def _focus_arguments(args: dict) -> dict:
    focus = args.get("focus", "timeline")
    if focus is not None and focus not in keys.FOCUS:
        raise ValueError(f"focus must be one of {', '.join(keys.FOCUS)}, or null")
    return {"focus": focus, "sequence": _sequence(args).get("sequence")}


def _key_command_arguments(args: dict, jobs) -> dict:
    if not isinstance(args.get("command"), str) or not args["command"].strip():
        raise ValueError("command must be a shortcut command name (premiere_list_key_commands)")
    return {"command": args["command"], **_focus_arguments(args)}


def _menu_command_arguments(args: dict, jobs) -> dict:
    if not isinstance(args.get("path"), str) or not args["path"].strip():
        raise ValueError('path must be a menu path like "Edit > Undo" (premiere_list_menu)')
    return {"path": args["path"], **_focus_arguments(args)}


def _assistant_arguments(args: dict, jobs) -> dict:
    prompt, timeout_s = args.get("prompt"), args.get("timeout_s", 120)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be text")
    if type(timeout_s) not in (int, float) or not 1 <= timeout_s <= 600:
        raise ValueError("timeout_s must be 1 to 600 seconds")
    return {"prompt": prompt, "timeout_s": timeout_s}


async def _list_key_commands(args: dict, premiere: Premiere) -> dict:
    found = await asyncio.to_thread(keys.list_commands, args["query"])
    return {"shortcuts_file": str(keys.active_kys()), "count": len(found), "commands": found[:300]}


async def _list_menu(args: dict, premiere: Premiere) -> dict:
    found = await asyncio.to_thread(menu.list_items, args["query"])
    return {"count": len(found), "items": found[:400]}


HELPER_COMMANDS: dict[str, Command] = {
    "screenshot": Command(30, _no_arguments, "Capture Premiere's main window to a PNG.",
                          run=lambda args, premiere: asyncio.to_thread(screenshot.capture)),
    "list_key_commands": Command(30, _query_arguments, "List Premiere commands that have a keyboard shortcut.",
                                 ("query", lambda target: {"query": target}), run=_list_key_commands),
    "key_command": Command(60, _key_command_arguments, "Run a Premiere command by pressing its shortcut.",
                           ("command", lambda target: {"command": target}),
                           run=lambda args, premiere: keys.run_command(premiere, args["command"], args["focus"], args["sequence"])),
    "list_menu": Command(30, _query_arguments, "List Premiere's menu bar items.",
                         ("query", lambda target: {"query": target}), run=_list_menu),
    "menu_command": Command(60, _menu_command_arguments, "Run a Premiere menu item as a click would.",
                            ("menu path", lambda target: {"path": target}),
                            run=lambda args, premiere: keys.run_focused(premiere, args["focus"], args["sequence"],
                                                                        lambda: menu.invoke(args["path"]))),
    # Waits for Adobe's reply up to timeout_s (at most 600).
    "assistant_ask": Command(660, _assistant_arguments, "Ask Premiere's own AI Assistant and return its reply.",
                             ("prompt", lambda target: {"prompt": target}),
                             run=lambda args, premiere: asyncio.to_thread(assistant.ask, args["prompt"], args["timeout_s"])),
}
COMMANDS.update(HELPER_COMMANDS)
PANEL_COMMANDS = [name for name, command in COMMANDS.items() if command.run is None]
