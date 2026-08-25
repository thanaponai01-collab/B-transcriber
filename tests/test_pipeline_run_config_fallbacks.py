"""Pin pipeline/run.py's config.get(...) fallbacks to config.yaml's values.

Issue #16: run.py:113/115 fell back to vad_threshold=0.5 and
vad_min_silence_ms=300 while config.yaml documents 0.35 and 500 (the values
that avoid clipping Thai sentence-final particles). The fallback only fires
when a caller passes a config dict missing that key — a trimmed test config,
a programmatic caller — so the drift was latent, not visible in normal runs.

This test parses run.py's AST for every top-level `config.get("key", default)`
call with a literal default and asserts it equals config.yaml's value for
that key, so a future edit can't silently reintroduce the same drift.
"""

import ast
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
RUN_PY = REPO_ROOT / "transcribe" / "pipeline" / "run.py"
CONFIG_YAML = REPO_ROOT / "transcribe" / "config.yaml"


def _literal_config_get_defaults(source: str) -> dict:
    """Extract {key: default} for every `config.get("key", <literal>)` call."""
    tree = ast.parse(source)
    defaults = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "config"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and isinstance(node.args[1], ast.Constant)
        ):
            defaults[node.args[0].value] = node.args[1].value
    return defaults


def test_run_py_config_get_fallbacks_match_config_yaml():
    defaults = _literal_config_get_defaults(RUN_PY.read_text(encoding="utf-8"))
    cfg = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))

    # Every config.get(key, default) found in run.py must be a key
    # config.yaml documents at its top level, with the same value — a
    # missing key here means either config.yaml's key moved (update this
    # test) or run.py is guessing at a default nothing backs (a bug).
    for key, fallback in defaults.items():
        assert key in cfg, (
            f"run.py's config.get({key!r}, {fallback!r}) has no matching "
            f"top-level key in config.yaml"
        )
        assert fallback == cfg[key], (
            f"run.py's config.get({key!r}, {fallback!r}) fallback disagrees "
            f"with config.yaml's {key}={cfg[key]!r}"
        )

    # Guard against the extraction silently matching nothing (e.g. run.py's
    # config.get call shape changes and the AST walk stops finding them).
    assert len(defaults) >= 5


def test_vad_fallbacks_specifically_match_config_yaml():
    # The two values from issue #16, pinned explicitly and independent of the
    # AST walk above, since these are the ones that actually drifted.
    defaults = _literal_config_get_defaults(RUN_PY.read_text(encoding="utf-8"))
    cfg = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))

    assert defaults["vad_threshold"] == cfg["vad_threshold"] == 0.35
    assert defaults["vad_min_silence_ms"] == cfg["vad_min_silence_ms"] == 500
