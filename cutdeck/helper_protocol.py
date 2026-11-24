"""Where the helper listens, which protocol it speaks, and a standard-library client for it.

cdv.py is one fresh process per Premiere command, so it talks to the helper through `ask` below
(socket + json: a whole `cdv call` measured ~100 ms) instead of asyncio + websockets (~280 ms).
The client speaks plain RFC 6455: no extensions, so the helper never compresses its replies to it.
"""
import base64
import json
import os
import socket
import struct
import sys

PORT = 7891
VERSION = "cutdeck-7"  # premiere_transcript: clip transcript JSON for Premiere
MAX_REPLY = 1 << 24  # the helper's MAX_MESSAGE, and Backend's max_size
NOT_RUNNING = "CutDeck helper is not running on 127.0.0.1:{port}; start it with: python -m cutdeck.helper"


def caller() -> str:
    """Who is asking, for the helper's command log: the program, and the Claude Code session that
    ran it (its transcript is ~/.claude/projects/<project>/<session>.jsonl)."""
    program = os.path.basename(sys.argv[0]) or "python"
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    return f"{program} {session}" if session else program


def checked(reply: dict) -> dict:
    if not reply.get("ok"):
        raise ValueError(reply.get("message", "Helper refused the request"))
    return reply


def exchange(messages: list[dict], port: int = PORT, open_timeout: float = 10, check: bool = True) -> dict:
    """Send each message on one connection, wait for its reply, and return the last reply.
    With `check`, a refused message raises ValueError and the rest are not sent."""
    try:
        sock = socket.create_connection((b"127.0.0.1", port), timeout=open_timeout)  # bytes: no idna codec import
    except OSError as exc:
        raise RuntimeError(NOT_RUNNING.format(port=port)) from exc
    with sock:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        stream = sock.makefile("rb")
        status = stream.readline()
        if b" 101 " not in status:
            raise ConnectionError(f"helper refused the websocket upgrade: {status.decode(errors='replace').strip()}")
        while stream.readline() not in (b"\r\n", b""):
            pass
        sock.settimeout(None)  # a command may run for minutes; only the connect is bounded
        for message in messages:
            _send(sock, 0x1, json.dumps(message).encode())
            reply = json.loads(_receive(sock, stream))
            if check:
                checked(reply)
        _send(sock, 0x8, struct.pack(">H", 1000))
        return reply


def ask(request: dict, port: int = PORT) -> dict:
    """One request after the version hello, as Backend._ask does over websockets."""
    return exchange([{"type": "hello", "version": VERSION}, {"caller": caller(), **request}], port)


def _send(sock: socket.socket, opcode: int, data: bytes) -> None:
    n = len(data)
    head = struct.pack(">BB", 0x80 | opcode, 0x80 | n) if n < 126 else (
        struct.pack(">BBH", 0x80 | opcode, 0xFE, n) if n < 65536 else struct.pack(">BBQ", 0x80 | opcode, 0xFF, n))
    mask = os.urandom(4)
    masked = (int.from_bytes(data, "big") ^ int.from_bytes(mask * -(-n // 4), "big") >> (8 * (-n % 4))).to_bytes(n, "big")
    sock.sendall(head + mask + masked)


def _read(stream, n: int) -> bytes:
    data = stream.read(n)
    if len(data) < n:
        raise ConnectionError("the helper closed the connection before replying")
    return data


def _receive(sock: socket.socket, stream) -> bytes:
    """One whole text message; answers pings and joins continuation frames on the way."""
    parts = []
    while True:
        b0, b1 = _read(stream, 2)
        n = b1 & 0x7F
        if n == 126:
            n, = struct.unpack(">H", _read(stream, 2))
        elif n == 127:
            n, = struct.unpack(">Q", _read(stream, 8))
        if sum(map(len, parts)) + n > MAX_REPLY:
            raise ConnectionError(f"the helper's reply is over {MAX_REPLY} bytes")
        payload = _read(stream, n)
        opcode = b0 & 0x0F
        if opcode == 0x9:
            _send(sock, 0xA, payload)
        elif opcode == 0x8:
            raise ConnectionError("the helper closed the connection before replying")
        elif opcode in (0x0, 0x1):
            parts.append(payload)
            if b0 & 0x80:
                return b"".join(parts)
