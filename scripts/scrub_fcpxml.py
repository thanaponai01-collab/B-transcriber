"""scrub_fcpxml.py — sanitize a real Premiere FCP7 XML export so it can be
committed as a test fixture (docs/HANDOFF_CUTDECK_XML_RECUT.md Phase 1).

A real export carries absolute paths to the editor's footage
(``file://localhost/E:/Clients/.../angle1.mp4``) and often a client or project
name in ``<sequence><name>``. This repo is public, so the raw export stays
local and only a scrubbed copy is committed.

**What is scrubbed:** ``<pathurl>``, ``<sequence><name>``, ``<file><name>``.
**What is never touched:** every numeric element — ``<start> <end> <in> <out>
<duration> <rate> <timebase>``, element ids, track counts, link groups. Those
*are* the fixture's value: the whole point is to capture what Premiere really
emits, structurally, so ``cutdeck/xml_recut.py`` is written against real
structure rather than an imagined one.

``<clipitem><name>`` is deliberately left alone — it carries CutDeck's
round-trip key (``cd###_p###_s####``, see ``xml_export.name_key``), which the
recut tests need to read.

This module makes **no assumptions about sequence structure**: it walks every
element by tag, whatever the nesting. That is why it can be written before a
real export exists (the fixture it prepares is what unblocks everything else).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

# Every distinct real path maps to one dummy under this root, so `<file>` id
# de-duplication (two clipitems sharing one source) stays observable in the
# scrubbed fixture exactly as it was in the original.
_FIXTURE_ROOT = "file://localhost/C:/fixtures"

_SEQUENCE_NAME = "fixture sequence"
_FILE_NAME_STEM = "angle"


def _ext_of(pathurl: str) -> str:
    """Suffix of the file a ``<pathurl>`` points at ('.mp4'), '' if none.

    Percent-decoded first: Premiere writes Windows drive letters encoded
    (``C%3A``), and a query-less URL path is otherwise a plain path.
    """
    try:
        name = Path(unquote(urlparse(pathurl).path)).name
    except Exception:
        return ""
    return Path(name).suffix


def scrub(xml_text: str) -> tuple[str, dict[str, str], int]:
    """Return (scrubbed_xml, {real_pathurl: dummy_pathurl}, names_changed).

    Pure: no file IO, no side effects. The mapping is returned rather than
    logged so the CLI can print a review summary — a scrub nobody reads is a
    rubber stamp, not a review.
    """
    root = ET.fromstring(xml_text)

    # ── pathurls: one stable dummy per distinct real path ──────────────────
    mapping: dict[str, str] = {}
    for el in root.iter("pathurl"):
        real = (el.text or "").strip()
        if not real:
            continue
        if real not in mapping:
            mapping[real] = f"{_FIXTURE_ROOT}/{_FILE_NAME_STEM}{len(mapping) + 1}{_ext_of(real)}"
        el.text = mapping[real]

    # ── names: <sequence> and <file> only, never <clipitem> ────────────────
    # A <name> is scrubbed by its *parent's* tag, so the CutDeck round-trip key
    # on a clipitem survives untouched.
    names_changed = 0
    seq_n = file_n = 0
    for parent in root.iter():
        if parent.tag not in ("sequence", "file"):
            continue
        for child in parent:
            if child.tag != "name":
                continue
            if parent.tag == "sequence":
                seq_n += 1
                child.text = _SEQUENCE_NAME if seq_n == 1 else f"{_SEQUENCE_NAME} {seq_n}"
            else:
                # A <file> stub (a later ref by id) carries no <name>; only the
                # one full listing per source does, so this numbering tracks
                # distinct sources the same way the pathurl mapping does.
                file_n += 1
                child.text = f"{_FILE_NAME_STEM}{file_n}"
            names_changed += 1

    body = ET.tostring(root, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n",
        mapping,
        names_changed,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sanitize a Premiere FCP7 XML export for committing as a test fixture."
    )
    ap.add_argument("xml_path", help="the raw export (kept local, never committed)")
    ap.add_argument("--out", default=None,
                    help="output path (default: <input>_scrubbed.xml beside the input)")
    args = ap.parse_args(argv)

    src = Path(args.xml_path)
    scrubbed, mapping, names_changed = scrub(src.read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else src.with_name(src.stem + "_scrubbed.xml")
    out.write_text(scrubbed, encoding="utf-8")

    print(f"wrote {out}")
    print(f"{len(mapping)} distinct source path(s) rewritten, {names_changed} name(s) neutralized:")
    for real, dummy in mapping.items():
        print(f"  {real}\n    -> {dummy}")
    if not mapping:
        print("  (none — check this is really a Premiere export)", file=sys.stderr)
    print("\nReview the output before committing. Numeric elements (start/end/in/out/"
          "rate/duration/ids) are untouched by design — they are the fixture's value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
