"""Absolute-path launcher for MCP clients, independent of their working directory.

The MCP server is a client of the CutDeck helper: start `python -m cutdeck.xml_bridge`
first (the tools report a clear error if it is not running).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cutdeck.mcp_server import main

if __name__ == "__main__":
    main()
