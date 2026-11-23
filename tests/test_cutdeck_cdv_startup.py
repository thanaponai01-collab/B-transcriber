"""`cdv.py call` is one fresh process per Premiere command, so its imports are paid on every call.
It needs only the helper's port and protocol version; the helper and its command table (which pull
premiere_ui, numpy and PIL) must stay unloaded."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ["cutdeck.helper", "cutdeck.driver_commands", "cutdeck.live_check", "cutdeck.premiere_ui", "numpy", "PIL"]


def _loaded_after(code: str) -> list[str]:
    probe = f"import json, sys; {code}; print(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))"
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_cdv_import_leaves_helper_modules_unloaded():
    assert _loaded_after("sys.path.insert(0, '.claude/skills/verify-cutdeck/scripts'); import cdv") == []


def test_ai_backend_import_leaves_helper_modules_unloaded():
    assert _loaded_after("import cutdeck.ai_backend") == []


def test_helper_protocol_is_what_the_helper_speaks():
    from cutdeck import helper, helper_protocol
    assert (helper.PORT, helper.VERSION) == (helper_protocol.PORT, helper_protocol.VERSION)
