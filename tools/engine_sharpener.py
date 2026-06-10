"""
engine_sharpener.py
===================

Keep the story-pipeline harness sharp.

This tool checks every dependency the engine relies on and tells you
what's new out there — without touching your install. Think of it as a
"checkup" you run weekly or before a big project, NOT an auto-updater.

What it checks
--------------
1. PyPI packages   — openai-whisper, faster-whisper, anthropic, etc.
2. Whisper models  — new model checkpoints from OpenAI (large-v3, v4…)
3. ffmpeg          — system version vs latest release
4. GitHub repos    — upstream tags for tools you care about
5. Anthropic API   — current available models (so your Director/Editor
                     agents can be pointed at the latest Claude)
6. Local repos     — your own engine clone(s) vs their git origin
                     (unpulled commits + uncommitted working-tree changes)

Output is a single Markdown report with three buckets:
  ✅ up to date
  🔶 minor update available
  🔴 major update / new tool / breaking change worth investigating

Usage
-----
    python tools/engine_sharpener.py                 # full check, print report
    python tools/engine_sharpener.py --json out.json # machine-readable
    python tools/engine_sharpener.py --quiet         # only show items needing action
    python tools/engine_sharpener.py --section pypi  # check one section only
    python tools/engine_sharpener.py --repo ~/code/story-pipeline
    python tools/engine_sharpener.py --repo ~/engine --repo ~/harness   # multiple

Design notes
------------
- Read-only. Never installs or upgrades anything. You decide.
- Network failures are non-fatal — a check that times out is reported as
  "unknown" rather than crashing the report.
- Cache responses for 6 hours in ~/.cache/engine_sharpener so repeated
  runs in the same session are instant.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger("sharpener")

CACHE_DIR = Path.home() / ".cache" / "engine_sharpener"
CACHE_TTL_SECONDS = 6 * 3600
HTTP_TIMEOUT = 8

# ---------------------------------------------------------------------------
# What to watch.
# ---------------------------------------------------------------------------
# Edit this section to add/remove things. Keep names matching the PyPI
# distribution name (not the import name).

PYPI_PACKAGES = [
    "openai-whisper",
    "faster-whisper",
    "anthropic",
    "openai",
    "torch",
    "torchaudio",
    "ffmpeg-python",
    "pydub",
    "numpy",
]

# Upstream GitHub repos worth watching for releases.
GITHUB_REPOS = [
    "openai/whisper",
    "SYSTRAN/faster-whisper",
    "anthropics/anthropic-sdk-python",
    "FFmpeg/FFmpeg",
]

# Whisper checkpoints currently published (kept up to date by openai/whisper).
# This is the canonical list we compare your local cache against.
KNOWN_WHISPER_MODELS = (
    "tiny", "base", "small", "medium",
    "large", "large-v2", "large-v3", "large-v3-turbo",
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    local: Optional[str] = None
    latest: Optional[str] = None
    status: str = "unknown"   # ok | minor | major | unknown | missing
    note: str = ""

    def emoji(self) -> str:
        return {
            "ok": "✅",
            "minor": "🔶",
            "major": "🔴",
            "missing": "⚪",
            "unknown": "❓",
        }[self.status]


@dataclass
class Report:
    sections: dict[str, list[CheckResult]] = field(default_factory=dict)

    def add(self, section: str, result: CheckResult) -> None:
        self.sections.setdefault(section, []).append(result)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _cache_get(key: str) -> Optional[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{key}.json"
    if not f.exists():
        return None
    if time.time() - f.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


def _cache_put(key: str, value: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(value))


def _http_json(url: str, cache_key: Optional[str] = None) -> Optional[dict]:
    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "engine-sharpener/1.0"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if cache_key:
            _cache_put(cache_key, data)
        return data
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        log.debug("HTTP fetch failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...]:
    """Cheap semver parser. Strips anything non-numeric after a digit run."""
    parts = []
    for chunk in re.split(r"[.\-+]", v.lstrip("vV")):
        m = re.match(r"^\d+", chunk)
        if m:
            parts.append(int(m.group()))
        else:
            break
    return tuple(parts) if parts else (0,)


def _classify(local: Optional[str], latest: Optional[str]) -> str:
    if local is None:
        return "missing"
    if latest is None:
        return "unknown"
    lv, rv = _parse_version(local), _parse_version(latest)
    if lv == rv:
        return "ok"
    if lv > rv:
        return "ok"   # local is newer (dev install, pre-release)
    if rv[0] > lv[0]:
        return "major"
    return "minor"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_pypi(packages: list[str]) -> list[CheckResult]:
    results = []
    for pkg in packages:
        local = _local_package_version(pkg)
        latest = _pypi_latest(pkg)
        r = CheckResult(name=pkg, local=local, latest=latest,
                        status=_classify(local, latest))
        if r.status == "missing":
            r.note = "not installed (skip if you don't need it)"
        results.append(r)
    return results


def _local_package_version(pkg: str) -> Optional[str]:
    # importlib.metadata works with the distribution name (with hyphens).
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version(pkg)
        except PackageNotFoundError:
            return None
    except ImportError:
        return None


def _pypi_latest(pkg: str) -> Optional[str]:
    data = _http_json(f"https://pypi.org/pypi/{pkg}/json", cache_key=f"pypi_{pkg}")
    if not data:
        return None
    return data.get("info", {}).get("version")


def check_github_releases(repos: list[str]) -> list[CheckResult]:
    results = []
    for repo in repos:
        latest = _github_latest_tag(repo)
        # No good way to "version" a repo locally without a clone, so we
        # just surface the latest tag. The point is to keep you aware.
        results.append(CheckResult(
            name=repo,
            local="(not tracked locally)",
            latest=latest,
            status="ok" if latest else "unknown",
            note="upstream tag — review changelog if it's been a while",
        ))
    return results


def _github_latest_tag(repo: str) -> Optional[str]:
    data = _http_json(
        f"https://api.github.com/repos/{repo}/releases/latest",
        cache_key=f"gh_{repo.replace('/', '_')}",
    )
    if not data:
        return None
    return data.get("tag_name") or data.get("name")


def check_ffmpeg() -> CheckResult:
    local = _local_ffmpeg_version()
    # FFmpeg doesn't publish a clean JSON API for "latest stable"; the
    # GitHub mirror's latest release tag is the most reliable signal.
    latest = _github_latest_tag("FFmpeg/FFmpeg")
    if latest and latest.startswith("n"):
        latest = latest[1:]   # tags look like "n7.0.2"
    return CheckResult(
        name="ffmpeg (system binary)",
        local=local,
        latest=latest,
        status=_classify(local, latest),
        note="major versions are usually backward-compatible; upgrade for new codecs",
    )


def _local_ffmpeg_version() -> Optional[str]:
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    m = re.search(r"ffmpeg version (\S+)", out.stdout)
    return m.group(1) if m else None


def check_whisper_models() -> list[CheckResult]:
    """
    Compare the Whisper models cached locally against the canonical list.
    Flags new ones that have appeared upstream that you haven't pulled.
    """
    results = []
    cache = Path.home() / ".cache" / "whisper"
    have = set()
    if cache.exists():
        for f in cache.glob("*.pt"):
            have.add(f.stem)

    for m in KNOWN_WHISPER_MODELS:
        r = CheckResult(name=f"whisper model: {m}")
        if m in have:
            r.local = "cached"
            r.latest = "cached"
            r.status = "ok"
        else:
            r.local = "not cached"
            r.latest = "available"
            r.status = "minor"
            r.note = f"download with: whisper --model {m}  (or load_model('{m}'))"
        results.append(r)
    return results


def check_anthropic_models() -> CheckResult:
    """
    Fetch the current list of Claude models from Anthropic's API.
    Requires ANTHROPIC_API_KEY. If unset, just notes that.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return CheckResult(
            name="Anthropic models",
            status="unknown",
            note="set ANTHROPIC_API_KEY to fetch the current model list",
        )
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "User-Agent": "engine-sharpener/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return CheckResult(
            name="Anthropic models",
            local="(check your agent configs)",
            latest=", ".join(names[:6]) + ("…" if len(names) > 6 else ""),
            status="ok",
            note="point your Director/Editor agents at the newest model if you've fallen behind",
        )
    except Exception as e:
        return CheckResult(
            name="Anthropic models",
            status="unknown",
            note=f"API call failed: {e}",
        )


# ---------------------------------------------------------------------------
# Local git repo checks
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str, timeout: int = 10) -> Optional[str]:
    """Run a git command inside repo, return stdout or None on failure."""
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log.debug("git %s failed in %s: %s", args, repo, e)
        return None
    if out.returncode != 0:
        log.debug("git %s in %s returned %d: %s",
                  args, repo, out.returncode, out.stderr.strip())
        return None
    return out.stdout.strip()


def check_local_repo(repo_path: str, do_fetch: bool = True) -> CheckResult:
    """
    Compare a local clone against its upstream and report:
      - how many commits behind/ahead of origin
      - whether the working tree is dirty (uncommitted changes)
    """
    repo = Path(repo_path).expanduser().resolve()
    name = f"repo: {repo.name}"

    if not repo.exists():
        return CheckResult(name=name, status="unknown",
                           note=f"path does not exist: {repo}")
    if not (repo / ".git").exists():
        return CheckResult(name=name, status="unknown",
                           note=f"not a git repo: {repo}")

    # Current branch.
    branch = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"

    # Refresh remote refs. Skippable if you're offline.
    if do_fetch:
        _run_git(repo, "fetch", "--quiet", timeout=15)

    # Find the upstream tracking branch (e.g. origin/main).
    upstream = _run_git(repo, "rev-parse", "--abbrev-ref",
                        "--symbolic-full-name", "@{u}")
    if not upstream:
        # No tracking branch configured. Still useful to report dirty state.
        dirty_note = _dirty_summary(repo)
        return CheckResult(
            name=name,
            local=f"branch {branch}",
            latest="(no upstream)",
            status="unknown" if not dirty_note else "minor",
            note=("no upstream tracking branch set"
                  + (f"; {dirty_note}" if dirty_note else "")),
        )

    # Count commits behind / ahead of upstream.
    counts = _run_git(repo, "rev-list", "--left-right", "--count",
                      f"HEAD...{upstream}")
    ahead = behind = 0
    if counts:
        try:
            ahead_s, behind_s = counts.split()
            ahead, behind = int(ahead_s), int(behind_s)
        except ValueError:
            pass

    # Dirty working tree?
    dirty_note = _dirty_summary(repo)

    # Decide status.
    if behind == 0 and ahead == 0 and not dirty_note:
        status = "ok"
    elif behind >= 10 or (dirty_note and "untracked" not in dirty_note and behind > 0):
        status = "major"
    else:
        status = "minor"

    # Build the note.
    bits = []
    if behind:
        bits.append(f"{behind} commit(s) behind {upstream}")
    if ahead:
        bits.append(f"{ahead} commit(s) ahead (unpushed)")
    if dirty_note:
        bits.append(dirty_note)
    if not bits:
        bits.append(f"in sync with {upstream}")

    return CheckResult(
        name=name,
        local=f"branch {branch}",
        latest=upstream,
        status=status,
        note="; ".join(bits),
    )


def _dirty_summary(repo: Path) -> str:
    """
    Return a short description of working-tree state, or "" if clean.
    Uses `git status --porcelain` so it works on any git >= 1.7.

    Note: we can't go through _run_git here because its .strip() would
    eat the leading space in lines like " M file.txt", which is
    semantically meaningful in porcelain output (col 0 = index state,
    col 1 = worktree state).
    """
    exe = shutil.which("git")
    if not exe:
        return ""
    try:
        out = subprocess.run(
            [exe, "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if out.returncode != 0 or not out.stdout:
        return ""

    modified = staged = untracked = 0
    for line in out.stdout.splitlines():
        if len(line) < 2:
            continue
        # Porcelain format: XY <path>
        #   X = index (staged) state
        #   Y = worktree (unstaged) state
        #   "??" = untracked
        x, y = line[0], line[1]
        if x == "?" and y == "?":
            untracked += 1
            continue
        if x != " " and x != "?":
            staged += 1
        if y != " " and y != "?":
            modified += 1

    parts = []
    if modified:
        parts.append(f"{modified} modified")
    if staged:
        parts.append(f"{staged} staged")
    if untracked:
        parts.append(f"{untracked} untracked")
    if not parts:
        return ""
    return "dirty working tree (" + ", ".join(parts) + ")"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

SECTIONS = {
    "pypi":      ("Python packages",       lambda: check_pypi(PYPI_PACKAGES)),
    "github":    ("Upstream repos",        lambda: check_github_releases(GITHUB_REPOS)),
    "ffmpeg":    ("System tools",          lambda: [check_ffmpeg()]),
    "models":    ("Whisper models",        check_whisper_models),
    "anthropic": ("Anthropic API",         lambda: [check_anthropic_models()]),
}


def run_checks(
    only: Optional[str] = None,
    repos: Optional[list[str]] = None,
    fetch: bool = True,
) -> Report:
    report = Report()
    for key, (title, fn) in SECTIONS.items():
        if only and key != only:
            continue
        log.info("Checking %s…", title)
        try:
            for r in fn():
                report.add(title, r)
        except Exception as e:
            report.add(title, CheckResult(name=key, status="unknown", note=str(e)))

    # Local repo section runs only if the user asked for it via --repo.
    # It's also gated by `only` so `--section repos` works as expected.
    if repos and (only is None or only == "repos"):
        log.info("Checking local repos…")
        for r in repos:
            try:
                report.add("Local repos", check_local_repo(r, do_fetch=fetch))
            except Exception as e:
                report.add("Local repos", CheckResult(
                    name=f"repo: {r}", status="unknown", note=str(e)))

    return report


def render_markdown(report: Report, quiet: bool = False) -> str:
    lines = ["# Engine Sharpener Report", ""]
    needs_action_total = 0
    for title, results in report.sections.items():
        filtered = [r for r in results if not quiet or r.status in ("minor", "major", "missing")]
        if not filtered:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| | Name | Local | Latest | Notes |")
        lines.append("|---|---|---|---|---|")
        for r in filtered:
            if r.status in ("minor", "major"):
                needs_action_total += 1
            lines.append(
                f"| {r.emoji()} | {r.name} | {r.local or '—'} | {r.latest or '—'} | {r.note} |"
            )
        lines.append("")
    lines.append("---")
    lines.append(
        f"_{needs_action_total} item(s) worth looking at. "
        f"Cache lives in {CACHE_DIR}._"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Check what's new across the engine's stack.")
    p.add_argument("--json", metavar="PATH", help="Write machine-readable JSON here.")
    p.add_argument("--quiet", action="store_true", help="Only show items needing action.")
    p.add_argument("--section", choices=list(SECTIONS.keys()) + ["repos"],
                   help="Run only one section.")
    p.add_argument("--repo", action="append", default=[], metavar="PATH",
                   help="Local git repo to check vs origin. Repeatable.")
    p.add_argument("--no-fetch", action="store_true",
                   help="Skip `git fetch` (use cached remote state — faster, offline-safe).")
    p.add_argument("--no-cache", action="store_true", help="Bypass the 6h HTTP cache.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    # Force UTF-8 on Windows consoles that default to cp1252; emoji won't render
    # otherwise.  reconfigure() is a no-op on platforms that already use UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if args.no_cache and CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()

    report = run_checks(
        only=args.section,
        repos=args.repo or None,
        fetch=not args.no_fetch,
    )

    if args.json:
        payload = {
            title: [asdict(r) for r in results]
            for title, results in report.sections.items()
        }
        Path(args.json).write_text(json.dumps(payload, indent=2))
        log.info("Wrote %s", args.json)

    print(render_markdown(report, quiet=args.quiet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
