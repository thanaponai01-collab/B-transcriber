"""The Engine Contract, read in the direction CLAUDE.md states it: no module
under `transcribe/engines/` may import `transcribe.pipeline` — the pipeline
consumes the Engine Contract, so an engine reaching back into it inverts the
boundary. Before issue #13, `engines/faster_whisper.py` did exactly this with
a lazy `from transcribe.pipeline import stitch` because seam-dedup (`stitch`)
lived on the wrong side of the boundary from the thing that creates the seams
it dedupes (`transcribe/audio/windows.py`'s overlap). Moving `stitch` into
`transcribe/audio/` closed the leak; this test is the mechanical check that it
stays closed.

Source-text grep, not AST: a lazy import inside a function body (exactly how
the original leak was written) would not show up as a module-level import, so
this must catch import statements anywhere in the file, not just the top.

Run: python -m pytest tests/test_engine_contract_import_direction.py -v
"""

import re
from pathlib import Path

_ENGINES_DIR = Path(__file__).resolve().parent.parent / "transcribe" / "engines"

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+transcribe\.pipeline\b", re.MULTILINE)


def test_no_engine_adapter_imports_transcribe_pipeline():
    offenders = []
    for path in sorted(_ENGINES_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if _IMPORT_RE.search(text):
            offenders.append(path.name)
    assert offenders == [], (
        f"transcribe/engines/ files importing transcribe.pipeline: {offenders} "
        "-- an engine adapter must not import the pipeline that consumes it "
        "(see CLAUDE.md's Engine Contract)."
    )
