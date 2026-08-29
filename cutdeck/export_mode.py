"""export_mode.py — cutdeck.mode config selection (Phase 4,
docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md; ``mark`` added by issue #17/#19;
``recut_sequence`` added by docs/HANDOFF_CUTDECK_XML_RECUT.md Phase 4).

Distinguishes the exporters CutDeck can hand a CutPlan to:

  * ``new_sequence``   -- ``cutdeck.xml_export.to_xml``, "build a fresh FCP7
    sequence for the editor to import".
  * ``mark``           -- ``cutdeck.mark_export.to_mark_plan``, "split +
    disable CUT regions on the editor's own live sequence via the UXP
    Mark/Apply plugin" (issue #17). Supersedes the retired ExtendScript
    ``in_place`` mode. Currently blocked on a UXP panel-compositing bug
    (host renders nothing; see `uxp/spike18_split_probe/README.md`) — not a
    capability gap, so ``recut_sequence`` below exists as an independent
    path that keeps working regardless of that bug's status.
  * ``recut_sequence`` -- ``cutdeck.xml_recut.recut``, "rewrite the editor's
    own exported FCP7 XML with the plan's cuts applied, sync-preserving,
    entirely offline". Signature is ``(source_xml: str, plan: CutPlan) ->
    tuple[str, RecutReport]`` — **not interchangeable** with the other two
    exporters, which take ``(plan, media_path, ...)``. Callers must not infer
    the call shape from ``new_sequence``/``mark``; this dispatcher exists so
    they never have to guess it from context either way.

They stay separate modules with different risk profiles (see each module's
docstring) — this file only picks between them so callers don't have to guess
from context.
"""

from __future__ import annotations

from typing import Callable

MODE_NEW_SEQUENCE = "new_sequence"
MODE_MARK = "mark"
MODE_RECUT_SEQUENCE = "recut_sequence"
VALID_MODES = (MODE_NEW_SEQUENCE, MODE_MARK, MODE_RECUT_SEQUENCE)


def exporter_for_mode(mode: str) -> Callable:
    """Return the exporter callable for a ``cutdeck.mode`` value.

    Raises ``ValueError`` on any value other than ``VALID_MODES`` — an
    unrecognized mode must fail loudly, never silently fall back to one
    exporter or the other.
    """
    if mode == MODE_NEW_SEQUENCE:
        from cutdeck.xml_export import to_xml
        return to_xml
    if mode == MODE_MARK:
        from cutdeck.mark_export import to_mark_plan
        return to_mark_plan
    if mode == MODE_RECUT_SEQUENCE:
        from cutdeck.xml_recut import recut
        return recut
    raise ValueError(f"unrecognized cutdeck.mode {mode!r} — must be one of {VALID_MODES}")


def mode_from_config(cfg: dict) -> str:
    """Read ``cutdeck.mode`` from a parsed ``config.yaml`` dict.

    Defaults to ``new_sequence`` — the existing, already-proven export path —
    on a missing key, so an unconfigured project never silently switches to
    mark-and-apply on a live sequence unasked.
    """
    return str(((cfg or {}).get("cutdeck", {}) or {}).get("mode", MODE_NEW_SEQUENCE))
