"""bridge.py — CutDeck <-> UXP plugin bridge (issue #17/#21).

Two things, deliberately separated so the interesting one needs no socket:

  * :func:`handle_message` — pure, no socket, no Premiere, no GPU. A clip
    descriptor goes in, a mark plan (or a structured refusal) comes out. This
    is the primary test seam for the whole live-sequence-cutting feature —
    the entire Python side (clip descriptor -> ``ingest()`` ->
    ``build_cut_spans()`` -> ``CutPlan`` -> mark plan) is exercised through
    this one function.
  * The socket transport is not here: ``cutdeck.xml_bridge`` (ws://127.0.0.1:7891,
    ``Start CutDeck.cmd``) is the single helper server and routes ``plan`` requests to
    this function. Python is the server, the UXP plugin is the client — UXP exposes no
    listen API.

**No LLM anywhere on this path** — same select-only discipline as the
reconciler (``pipeline/reconcile.py``) and the takes classifier (``takes.py``).

**Refusals are responses, not exceptions on the wire.** A VFR source, a
speed-changed or reversed clip, a missing/unreadable media path, or a missing
timebase all come back as ``{"type": "error", "reason": ..., "message": ...}``
— never a dropped connection or an unhandled traceback. ``reason`` is
machine-readable for the plugin's own branching; ``message`` is meant to be
shown to the editor directly.

**Never fabricate a timebase.** A ``plan`` message with no ``timebase`` is
refused outright — ``transcribe.timebase.probe()`` is never called on this
path, since a mixdown/media-only probe silently falls back to a fabricated
25fps timebase (the exact hazard ``sequence_mixdown.py`` already documents).
"""

from __future__ import annotations

from typing import Optional

from cutdeck.contracts import CutConfig, Timebase
from cutdeck.live_clip import ClipDescriptor, LiveClipRefused, plan_from_live_clip
from cutdeck.mark_export import to_mark_plan

BRIDGE_VERSION = "1.0"


def handle_message(req: dict, *, cfg: Optional[CutConfig] = None, **ingest_kwargs) -> dict:
    """Dispatch one protocol message. Never raises on a bad/refused request —
    every failure mode is a structured ``{"type": "error", ...}`` response.

    "Pure" in the sense issue #21 means it: no socket, no Premiere, no GPU —
    the primary test seam. A ``plan`` message does read the clip's media file
    from disk via ``ingest()``, same as ``plan_from_mixdown``/``propose_for_job``
    already do; it just needs no live connection to do it.

    ``cfg`` defaults to ``CutConfig()`` (the deterministic defaults tests
    exercise) rather than reading ``transcribe/config.yaml`` off disk here —
    ``cutdeck.xml_bridge`` loads the real config when it serves a ``plan`` request.
    """
    msg_type = req.get("type")
    if msg_type == "hello":
        return _handle_hello(req)
    if msg_type == "plan":
        return _handle_plan(req, cfg if cfg is not None else CutConfig(), **ingest_kwargs)
    return _error(
        "unknown_message_type",
        f"unrecognized message type {msg_type!r} — expected 'hello' or 'plan'.",
    )


def _handle_hello(req: dict) -> dict:
    client_version = req.get("version")
    if client_version != BRIDGE_VERSION:
        return _error(
            "version_mismatch",
            f"CutDeck bridge is protocol v{BRIDGE_VERSION}; plugin announced "
            f"v{client_version!r}. Refusing to continue with a mismatched "
            "protocol — update the plugin or the bridge before retrying.",
        )
    return {"type": "hello", "version": BRIDGE_VERSION}


def _handle_plan(req: dict, cfg: CutConfig, **ingest_kwargs) -> dict:
    media_path = req.get("media_path")
    if not media_path:
        return _error("missing_field", "missing required field 'media_path'.")

    tb_data = req.get("timebase")
    if not tb_data:
        return _error(
            "missing_timebase",
            "no sequence timebase provided — refusing to guess one. Send the "
            "live sequence's own timebase (never probed from the media file).",
        )
    try:
        timebase = Timebase(
            fps_num=int(tb_data["fps_num"]),
            fps_den=int(tb_data["fps_den"]),
            is_vfr=bool(tb_data.get("is_vfr", False)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return _error("invalid_timebase", f"malformed timebase: {e}")

    try:
        clip = ClipDescriptor(
            media_path=media_path,
            clip_start_ms=int(req.get("clip_start_ms", 0)),
            in_point_ms=int(req.get("in_point_ms", 0)),
            out_point_ms=int(req["out_point_ms"]),
            timebase=timebase,
            speed=float(req.get("speed", 1.0)),
            reversed=bool(req.get("reversed", False)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return _error("invalid_descriptor", f"malformed clip descriptor: {e}")

    job_id = int(req.get("job_id", 0))

    try:
        plan = plan_from_live_clip(clip, job_id, cfg, **ingest_kwargs)
    except LiveClipRefused as e:
        return _error(e.reason, str(e))
    except Exception as e:  # noqa: BLE001 — any read/decode failure is a refusal, not a crash
        return _error("unreadable_media", f"could not read/process {media_path!r}: {e}")

    # Checked directly against plan.timebase rather than pattern-matching
    # to_mark_plan's ValueError message — a wording change there must not be
    # able to silently degrade this into a generic 'invalid_plan' reason.
    if plan.timebase.is_vfr:
        return _error(
            "vfr",
            "refusing to generate a mark plan for VFR source: no single frame "
            "grid for frame-accurate cuts (GAP-2). Conform a CFR proxy first.",
        )

    return {"type": "mark_plan", "mark_plan": to_mark_plan(plan)}


def _error(reason: str, message: str) -> dict:
    return {"type": "error", "reason": reason, "message": message}
