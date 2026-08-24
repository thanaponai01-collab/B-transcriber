"""export_mode.py — cutdeck.mode config selection (Phase 4,
docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md).

Distinguishes the two exporters CutDeck can hand a CutPlan to:

  * ``new_sequence`` -- ``cutdeck.xml_export.to_xml``, the existing "build a
    fresh FCP7 sequence for the editor to import" path.
  * ``in_place``     -- ``cutdeck.jsx_export.to_jsx``, this handoff's "razor +
    ripple-delete an already-assembled live sequence" path.

They stay two separate modules with different risk profiles (see both modules'
docstrings) — this file only picks between them so callers don't have to guess
from context.
"""

from __future__ import annotations

from typing import Callable

MODE_NEW_SEQUENCE = "new_sequence"
MODE_IN_PLACE = "in_place"
VALID_MODES = (MODE_NEW_SEQUENCE, MODE_IN_PLACE)


def exporter_for_mode(mode: str) -> Callable:
    """Return the exporter callable for a ``cutdeck.mode`` value.

    Raises ``ValueError`` on any value other than ``VALID_MODES`` — an
    unrecognized mode must fail loudly, never silently fall back to one
    exporter or the other.
    """
    if mode == MODE_NEW_SEQUENCE:
        from cutdeck.xml_export import to_xml
        return to_xml
    if mode == MODE_IN_PLACE:
        from cutdeck.jsx_export import to_jsx
        return to_jsx
    raise ValueError(f"unrecognized cutdeck.mode {mode!r} — must be one of {VALID_MODES}")


def mode_from_config(cfg: dict) -> str:
    """Read ``cutdeck.mode`` from a parsed ``config.yaml`` dict.

    Defaults to ``new_sequence`` — the existing, already-proven export path —
    on a missing key, so an unconfigured project never silently switches to
    the riskier in-place mode.
    """
    return str(((cfg or {}).get("cutdeck", {}) or {}).get("mode", MODE_NEW_SEQUENCE))
