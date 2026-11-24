"""`cdv.py call` is one fresh process per Premiere command, so its imports are paid on every call.
It talks to the helper through cutdeck.helper_protocol's standard-library client; asyncio,
websockets, the helper and its command table (premiere_ui, numpy, PIL) must stay unloaded, and the
client must answer exactly as Backend does over websockets."""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from websockets.asyncio.server import serve as ws_serve

from cutdeck import ai_backend, helper_protocol
from cutdeck.ai_backend import Backend
from cutdeck.helper import Jobs, serve

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ["asyncio", "websockets", "cutdeck.ai_backend", "cutdeck.helper", "cutdeck.driver_commands",
         "cutdeck.live_check", "cutdeck.premiere_ui", "numpy", "PIL"]


def _loaded_after(code: str) -> list[str]:
    probe = f"import json, sys; {code}; print(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))"
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


async def _helper(body, jobs_dir):
    server = await serve(Jobs(jobs_dir), 0)
    try:
        return await body(server.sockets[0].getsockname()[1])
    finally:
        server.close()
        await server.wait_closed()


def test_a_cdv_round_trip_leaves_heavy_modules_unloaded(tmp_path):
    async def body(port):
        code = ("sys.path.insert(0, '.claude/skills/verify-cutdeck/scripts'); import cdv; "
                f"assert cdv.ask({{'type': 'premiere_status'}}, {port})['ok']")
        return await asyncio.to_thread(_loaded_after, code)
    assert asyncio.run(_helper(body, tmp_path)) == []


def test_helper_protocol_is_what_the_helper_speaks():
    from cutdeck import helper
    assert (helper.PORT, helper.VERSION) == (helper_protocol.PORT, helper_protocol.VERSION)


def _outcome(call):
    try:
        return "reply", call()
    except Exception as exc:
        return type(exc).__name__, str(exc)


async def _async_outcome(coro):
    try:
        return "reply", await coro
    except Exception as exc:
        return type(exc).__name__, str(exc)


@pytest.mark.parametrize("request_", [
    {"type": "premiere_status"},
    {"type": "premiere", "command": "read_sequence", "args": {}},  # no panel connected
    {"type": "premiere", "command": "no_such_command", "args": {}},
    {"type": "no_such_type"},
])
def test_client_answers_as_backend_does(request_, tmp_path):
    async def body(port):
        sync = await asyncio.to_thread(_outcome, lambda: helper_protocol.ask(request_, port))
        return sync, await _async_outcome(Backend(port)._ask(request_))
    sync, websockets_ = asyncio.run(_helper(body, tmp_path))
    assert sync == websockets_


def test_client_version_mismatch_matches_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(helper_protocol, "VERSION", "cutdeck-0")
    monkeypatch.setattr(ai_backend, "VERSION", "cutdeck-0")
    test_client_answers_as_backend_does({"type": "premiere_status"}, tmp_path)


def test_client_nothing_listening_matches_backend():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    sync = _outcome(lambda: helper_protocol.ask({"type": "premiere_status"}, port))
    assert sync == asyncio.run(_async_outcome(Backend(port)._ask({"type": "premiere_status"})))
    assert sync[0] == "RuntimeError" and str(port) in sync[1]


async def _echo_server(body, delay=0.0, fragments=1, **options):
    async def handler(ws):
        async for message in ws:
            await asyncio.sleep(delay)
            reply = json.dumps({"ok": True, "echo": json.loads(message)})
            step = -(-len(reply) // fragments)
            await ws.send([reply[i:i + step] for i in range(0, len(reply), step)] if fragments > 1 else reply)
    async with ws_serve(handler, "127.0.0.1", 0, max_size=1 << 24, **options) as server:
        return await body(server.sockets[0].getsockname()[1])


def _ask_in_thread(request, **server):
    async def body(port):
        return await asyncio.to_thread(helper_protocol.ask, request, port)
    return asyncio.run(_echo_server(body, **server))


def test_client_answers_pings_during_a_long_command():
    # The helper pings every 20 s; a client that never pongs is dropped mid-command.
    reply = _ask_in_thread({"type": "slow"}, delay=1.5, ping_interval=0.1, ping_timeout=0.5)
    assert reply["echo"] == {"type": "slow", "caller": helper_protocol.caller()}


@pytest.mark.parametrize("size", [0, 3, 125, 126, 65535, 65536, 300_000])
def test_client_round_trips_every_frame_length(size):
    request = {"type": "x", "text": "ก" * size}  # Thai: 3 bytes each in UTF-8
    assert _ask_in_thread(request)["echo"] == {"caller": helper_protocol.caller(), **request}


def test_client_joins_a_fragmented_reply():
    assert _ask_in_thread({"type": "x", "text": "abc" * 1000}, fragments=7)["echo"]["text"] == "abc" * 1000
