"""Layer contract, from the import graph measured in .cleanup/2026-11-28.md.

transcribe sits at the bottom. cutdeck's control modules sit on it, the hks_* modules on both, and
subtitle_desk on top. Every import counts, a lazy one inside a function included.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("transcribe", "cutdeck", "subtitle_desk")

# Which layers each layer may import, besides itself.
MAY_IMPORT = {
    "transcribe": set(),
    "cutdeck": {"transcribe"},
    "hks": {"cutdeck", "transcribe"},
    "subtitle_desk": {"cutdeck", "transcribe"},
}
# The one place control reaches into hks_*: the premiere_hks_* commands run hks_enforce.
EXCEPTIONS = {("cutdeck/driver_commands.py", "cutdeck.hks_enforce")}


def layer(module: str) -> str:
    parts = module.split(".")
    if parts[0] == "cutdeck" and len(parts) > 1 and (parts[1].startswith("hks_") or parts[1] == "honekasae_export"):
        return "hks"
    return parts[0]


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if "." in node.module:
                yield node.module
            else:  # `from cutdeck import hks_enforce` imports the module cutdeck.hks_enforce
                yield from (f"{node.module}.{alias.name}" for alias in node.names)


def violations():
    found = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            source = layer(rel[:-3].replace("/", "."))
            for module in set(imports(ast.parse(path.read_text(encoding="utf-8"), filename=rel))):
                target = layer(module)
                if (target in PACKAGES or target == "hks") and target != source \
                        and target not in MAY_IMPORT[source] and (rel, module) not in EXCEPTIONS:
                    found.append(f"{rel} ({source}) imports {module} ({target})")
    return sorted(found)


def test_layers_import_only_downward():
    assert violations() == []


def test_the_exception_is_still_needed():
    # When the hks commands stop importing hks_enforce, drop the exception.
    for rel, module in EXCEPTIONS:
        assert module in set(imports(ast.parse((ROOT / rel).read_text(encoding="utf-8")))), (rel, module)
