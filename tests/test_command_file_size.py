"""The command table only shrinks: each family that moves out of cutdeck/driver_commands.py lowers
its limit to the new line count plus about 40, and no family module grows past 500."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {"cutdeck/driver_commands.py": 1690}
FAMILY_LIMIT = 500
FILES = ["cutdeck/driver_commands.py"] + sorted(p.relative_to(ROOT).as_posix()
                                               for p in (ROOT / "cutdeck" / "commands").glob("*.py"))


@pytest.mark.parametrize("rel", FILES)
def test_command_file_stays_under_its_limit(rel):
    lines = len((ROOT / rel).read_text(encoding="utf-8").splitlines())
    limit = LIMITS.get(rel, FAMILY_LIMIT)
    assert lines <= limit, f"{rel} has {lines} lines, over its limit of {limit}: move code into cutdeck/commands/"
