"""One size limit for the HKS analysis caches in %TEMP% (``hks_audit``, ``hks_breaks``,
``hks_cutpoints``, ``hks_layout``, ``hks_silence``, ``hks_turns``).

Each footage file's entries share the name up to its first dot (``<key>.npz``, ``<key>.thumbs``,
...), and they go together. A cache hit calls ``touch`` so a file's entries age from its last use.
After a new entry is written, ``trim`` drops whole groups, biggest first, until the caches fit in
``LIMIT``: each drop costs one recompute, so the fewest recomputes free the space, and the small
ones (speaker embeddings, clock tracks: slow to make, a few MB) stay. Groups used in the last
``KEEP_RECENT_S`` are never dropped (a long ``--all`` run or another process may still need
them, so the caches can sit over the limit until then). The
smallest file of a group goes first: an index (``.npz``, ``.layout.npy``) before the data it
points at, and each reader rebuilds an entry with any file missing, so a half-deleted
group is rebuilt, never read as broken.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

DIRS = ("hks_audit", "hks_breaks", "hks_cutpoints", "hks_layout", "hks_silence", "hks_turns")
LIMIT = 10 * 2**30
KEEP_RECENT_S = 24 * 3600


def touch(*paths: Path) -> None:
    for p in paths:
        try:
            os.utime(p)
        except OSError:
            pass


def trim(root: Path, limit: int = LIMIT) -> None:
    """Trim the HKS caches under ``root``, the folder holding the cache just written to (%TEMP% by
    default): a run with its own ``--cache`` folder never touches the default caches."""
    groups: dict[tuple[str, str], list[tuple[Path, os.stat_result]]] = {}
    for d in DIRS:
        for p in (root / d).glob("*"):
            try:
                st = p.stat()
            except OSError:
                continue
            if p.is_file():
                groups.setdefault((d, p.name.split(".")[0]), []).append((p, st))
    total = sum(st.st_size for g in groups.values() for _, st in g)
    recent = time.time() - KEEP_RECENT_S
    for g in sorted(groups.values(), key=lambda g: -sum(st.st_size for _, st in g)):
        if total <= limit:
            return
        if max(st.st_mtime for _, st in g) > recent:
            continue
        for p, st in sorted(g, key=lambda f: f[1].st_size):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError:  # held open (a memmap in another run): leave the rest of the group
                break
            total -= st.st_size
