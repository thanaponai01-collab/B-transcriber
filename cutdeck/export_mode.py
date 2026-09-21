"""export_mode.py — cutdeck.mode config selection (Phase 4,
docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md;
``recut_sequence`` added by docs/HANDOFF_CUTDECK_XML_RECUT.md Phase 4).

Distinguishes the exporters CutDeck can hand a CutPlan to:

  * ``new_sequence``   -- ``cutdeck.xml_export.to_xml``, "build a fresh FCP7
    sequence for the editor to import".
  * ``recut_sequence`` -- ``cutdeck.xml_recut.recut``, "rewrite the editor's
    own exported FCP7 XML with the plan's cuts applied, sync-preserving,
    entirely offline". Signature is ``(source_xml: str, plan: CutPlan) ->
    tuple[str, RecutReport]`` -- **not interchangeable** with the other
    exporters, which take ``(plan, media_path, ...)``. Callers must not infer
    the call shape from ``new_sequence``; this dispatcher exists so
    they never have to guess it from context either way.

They stay separate modules with different risk profiles (see each module's
docstring) — this file only picks between them so callers don't have to guess
from context.
"""

from __future__ import annotations

from typing import Callable

MODE_NEW_SEQUENCE = "new_sequence"
MODE_RECUT_SEQUENCE = "recut_sequence"
VALID_MODES = (MODE_NEW_SEQUENCE, MODE_RECUT_SEQUENCE)


def exporter_for_mode(mode: str) -> Callable:
    """Return the exporter callable for a ``cutdeck.mode`` value.

    Raises ``ValueError`` on any value other than ``VALID_MODES`` — an
    unrecognized mode must fail loudly, never silently fall back to one
    exporter or the other.
    """
    if mode == MODE_NEW_SEQUENCE:
        from cutdeck.xml_export import to_xml
        return to_xml
    if mode == MODE_RECUT_SEQUENCE:
        from cutdeck.xml_recut import recut
        return recut
    raise ValueError(f"unrecognized cutdeck.mode {mode!r} — must be one of {VALID_MODES}")


def mode_from_config(cfg: dict) -> str:
    """Read ``cutdeck.mode`` from a parsed ``config.yaml`` dict.

    Defaults to ``new_sequence`` on a missing key, so an unconfigured project
    never silently touches the editor's live sequence unasked. That is the only
    claim being made for the default: ``new_sequence`` is the *safest* mode, not
    a proven one. Its real acceptance — a clean import into Premiere on real
    footage — has been open since 2026-06-19 (TODO_LEDGER, "CutDeck
    real-Premiere XML import acceptance"); an earlier version of this docstring
    called it "already-proven", which the ledger contradicts.
    """
    return str(((cfg or {}).get("cutdeck", {}) or {}).get("mode", MODE_NEW_SEQUENCE))
