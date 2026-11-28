"""Move docs with `git mv` and rewrite every citation of them, or check that citations resolve.

    python tools/move_docs.py [--skip FILE]... OLD=NEW...          move, then rewrite
    python tools/move_docs.py --check [--skip FILE]... OLD=NEW...  report, change nothing
    --pairs FILE reads OLD=NEW lines from FILE in place of (or as well as) the arguments.

A citation is any mention of a moved doc's file name in a tracked text file. Markdown and HTML
link targets are file-relative, so each relative link is recomputed from its file's new place;
that also fixes the outbound links of the moved docs. Every other mention (prose, docstrings,
comments) becomes the repo-relative new path, unless it still resolves from where it stands.
Basenames of moved docs must be unique in the repo. Safe to rerun: a resolved mention is left.
--skip leaves a file untouched (records whose content is hashed).
"""

import argparse
import os
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote

LINK = re.compile(r"\]\(([^)\s]+)|(?:href|src)=[\"']([^\"']+)[\"']")


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def read_text(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if b"\0" in raw or len(raw) > 5_000_000:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def norm(path):
    path = posixpath.normpath(path)
    return "" if path == "." else path


class Repo:
    def __init__(self, files, moves):
        self.files = set(files)
        self.dirs = {posixpath.dirname(f) for f in files}
        for d in list(self.dirs):
            while d:
                d = posixpath.dirname(d)
                self.dirs.add(d)
        self.by_name = {posixpath.basename(new): new for new in moves.values()}
        # Accept an already-moved tree, so a rerun is a no-op.
        self.known = {old: new for old, new in moves.items()} | {new: new for new in moves.values()}

    def exists(self, path):
        return path in self.files or path in self.dirs or path in self.known

    def target(self, path):
        """Where `path` (repo-relative) lives after the move."""
        return self.known.get(path, path)


def split_target(raw):
    cut = min([i for i in (raw.find("#"), raw.find("?")) if i >= 0], default=len(raw))
    return raw[:cut], raw[cut:]


def rewrite_link(repo, raw, old_dir, new_dir):
    """New text for one link target, or None to keep it."""
    path, tail = split_target(raw)
    if not path:
        return None
    name = posixpath.basename(unquote(path).rstrip("/"))
    if path.startswith("file:"):
        url = unquote(path)
        hit = [old for old in repo.known if url.endswith("/" + old)]
        if not hit:
            return None
        resolved = max(hit, key=len)
    elif re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", path):
        return None
    else:
        plain = unquote(path)
        resolved = norm(plain.lstrip("/")) if plain.startswith("/") else norm(posixpath.join(old_dir, plain))
        if not repo.exists(resolved):
            if name in repo.by_name:
                raise LookupError(raw)
            return None
    if old_dir == new_dir and repo.target(resolved) == resolved:
        return None
    new = posixpath.relpath(repo.target(resolved), new_dir or ".")
    if "%20" in path:
        new = new.replace(" ", "%20")
    if path.endswith("/") and not new.endswith("/"):
        new += "/"
    return None if new == path else new + tail


def mention_re(names):
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(r"(?<![\w.\\/-])((?:[\w.-]+/)*)(" + alt + r")(?![\w-])")


def rewrite_text(repo, text, old_path, pattern):
    """Return (new text, replacements, unresolved mentions)."""
    old_dir = posixpath.dirname(old_path)
    new_dir = posixpath.dirname(repo.target(old_path))
    edits, spans, unresolved = [], [], []
    for m in LINK.finditer(text):
        g = 1 if m.group(1) is not None else 2
        spans.append((m.start(g), m.end(g)))
        try:
            new = rewrite_link(repo, m.group(g), old_dir, new_dir)
        except LookupError:
            unresolved.append(m.group(g))
            continue
        if new is not None:
            edits.append((m.start(g), m.end(g), new))
    for m in pattern.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        prefix, name = m.group(1), m.group(2)
        dest = repo.by_name[name]
        here = norm(posixpath.join(new_dir, prefix + name))
        if here == dest or norm(prefix + name) == dest:
            continue  # already resolves from where it stands
        candidates = {norm(posixpath.join(old_dir, prefix + name)), norm(prefix + name)}
        if prefix and not any(repo.target(c) == dest for c in candidates):
            unresolved.append(prefix + name)
            continue
        edits.append((m.start(), m.end(), dest))
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text, len(edits), unresolved


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--pairs", dest="pairs_file")
    ap.add_argument("pairs", nargs="*", metavar="OLD=NEW")
    args = ap.parse_args()
    if args.pairs_file:
        with open(args.pairs_file, encoding="utf-8") as fh:
            args.pairs += [line.strip() for line in fh if line.strip()]
    moves = dict(p.split("=", 1) for p in args.pairs)
    files = tracked()
    names = [posixpath.basename(n) for n in moves.values()]
    clashes = [f for f in files if posixpath.basename(f) in names and f not in moves and f not in moves.values()]
    if clashes or len(set(names)) != len(names):
        sys.exit(f"basenames are not unique: {clashes}")
    repo = Repo(files, moves)
    pattern = mention_re(names)

    plan, total, dangling = {}, 0, []
    for path in files:
        if path in args.skip:
            continue
        text = read_text(path)
        if text is None:
            continue
        new_text, count, unresolved = rewrite_text(repo, text, path, pattern)
        dangling += [f"{path}: {u}" for u in unresolved]
        if count:
            plan[path] = new_text
            total += count
            print(f"{count:4d}  {path}")
    print(f"{total} citations in {len(plan)} files need rewriting" if args.check
          else f"{total} citations rewritten in {len(plan)} files")
    for d in dangling:
        print("UNRESOLVED", d)
    if args.check:
        sys.exit(1 if total or dangling else 0)

    for old, new in moves.items():
        if os.path.exists(old):
            os.makedirs(os.path.dirname(new), exist_ok=True)
            subprocess.run(["git", "mv", old, new], check=True)
    for path, text in plan.items():
        with open(repo.target(path), "w", encoding="utf-8", newline="") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
