"""No two modules in cutdeck/ or transcribe/ import each other, directly or around a loop.

Every import counts, a lazy one inside a function included: a cycle hidden in a function body is
still a cycle (.cleanup/2026-11-28.md found two, keys <-> menu and hks_enforce <-> hks_handover).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("cutdeck", "transcribe")


def modules() -> dict[str, Path]:
    found = {}
    for package in PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            name = path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
            found[name.removesuffix(".__init__")] = path
    return found


def resolve(name: str, known) -> str | None:
    """The module an import name lands in: itself, else its nearest parent we know."""
    while name and name not in known:
        name = name.rpartition(".")[0]
    return name or None


def graph() -> dict[str, set[str]]:
    known = modules()
    edges = {}
    for name, path in known.items():
        targets = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Import):
                targets |= {resolve(alias.name, known) for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                # `from cutdeck import menu` and `from cutdeck.menu import invoke` both land in cutdeck.menu
                targets |= {resolve(f"{node.module}.{alias.name}", known) for alias in node.names}
        edges[name] = targets - {None, name}
    return edges


def cycles() -> list[list[str]]:
    edges = graph()
    reach = {}
    for start in edges:
        seen, todo = set(), [start]
        while todo:
            for nxt in edges.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        reach[start] = seen
    loops = {tuple(sorted(n for n in reach[m] if m in reach[n])) for m in edges if m in reach[m]}
    return sorted(list(loop) for loop in loops)


def test_no_import_cycles():
    assert cycles() == []
