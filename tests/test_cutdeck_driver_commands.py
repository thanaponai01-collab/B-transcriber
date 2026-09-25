"""One table owns the Premiere driver commands (docs/arch-design-helper-v3.md move 1)."""
import asyncio
from pathlib import Path
import re

from cutdeck import driver_commands
from cutdeck.ai_backend import Backend
from cutdeck.mcp_server import create_server

DRIVER_JS = Path(__file__).resolve().parent.parent / "uxp" / "cutdeck" / "features" / "driver.js"


def test_panel_driver_offers_exactly_the_tabled_commands():
    array = re.search(r"const COMMANDS = \[([^\]]*)\]", DRIVER_JS.read_text(encoding="utf-8")).group(1)
    assert sorted(re.findall(r'"(\w+)"', array)) == sorted(driver_commands.COMMANDS)


def test_every_command_is_an_agent_tool():
    listed = {f"premiere_{name}" for name in driver_commands.COMMANDS}
    assert listed <= set(Backend().capabilities()["tools"])
    tools = asyncio.run(create_server(Backend()).list_tools())
    assert listed <= {tool.name for tool in tools}
