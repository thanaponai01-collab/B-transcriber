"""export_mode.py — cutdeck.mode config selection (Phase 4,
docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md; ``mark`` added by issue #17/#19).

Distinguishes the exporters CutDeck can hand a CutPlan to:

  * ``new_sequence`` -- ``cutdeck.xml_export.to_xml``, "build a fresh FCP7
    sequence for the editor to import".
  * ``mark``         -- ``cutdeck.mark_export.to_mark_plan``, "split + disable
    CUT regions on the editor's own live sequence via the UXP Mark/Apply
    plugin" (issue #17). Supersedes the retired ExtendScript ``in_place`` mode.
    **Parked** — the split primitive it depends on was abandoned on evidence
    (see ``mark_export.py``'s docstring and ``assemble_export.py``'s).
  * ``assemble``     -- ``cutdeck.assemble_export.to_assemble_plan``, "place
    every span into a new sequence and disable the CUT ones". The route that
    replaced ``mark`` after issue #24, needing no split primitive at all.

They stay separate modules with different risk profiles (see each module's
docstring) — this file only picks between them so callers don't have to guess
from context.
"""

from __future__ import annotations

from typing import Callable

MODE_NEW_SEQUENCE = "new_sequence"
MODE_MARK = "mark"
MODE_ASSEMBLE = "assemble"
VALID_MODES = (MODE_NEW_SEQUENCE, MODE_MARK, MODE_ASSEMBLE)


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
    if mode == MODE_ASSEMBLE:
        from cutdeck.assemble_export import to_assemble_plan
        return to_assemble_plan
    raise ValueError(f"unrecognized cutdeck.mode {mode!r} — must be one of {VALID_MODES}")


def mode_from_config(cfg: dict) -> str:
    """Read ``cutdeck.mode`` from a parsed ``config.yaml`` dict.

    Defaults to ``new_sequence`` — the existing, already-proven export path —
    on a missing key, so an unconfigured project never silently switches to
    mark-and-apply on a live sequence unasked.
    """
    return str(((cfg or {}).get("cutdeck", {}) or {}).get("mode", MODE_NEW_SEQUENCE))
