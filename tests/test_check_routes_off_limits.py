import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_routes", Path(__file__).resolve().parents[1] / "tools" / "adobe" / "check_routes.py")
check_routes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_routes)


@pytest.mark.parametrize("code", ['ws("localhost:3111")', "http://127.0.0.1:3111/mcp", "[::1]:3111",
                                  "hSLScripting.run()", "EnableMCPServer = 1"])
def test_first_party_routes_are_caught(code):
    assert check_routes.OFF_LIMITS_CODE.search(code)


@pytest.mark.parametrize("code", ["localhost:31110", "127.0.0.1:7891", "port = 3111"])
def test_other_ports_pass(code):
    assert not check_routes.OFF_LIMITS_CODE.search(code)
