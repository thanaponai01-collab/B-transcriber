"""Registry layout experiment: one rules.json (A) vs rules/<id>.json (B).

Builds throwaway git repos under ./work, runs each scenario with real `git merge`,
and writes ./results.json. Usage: python experiment.py <path to rules.json>
"""
import copy
import json
import os
import stat
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
SRC = Path(sys.argv[1])
FULL = json.loads(SRC.read_text(encoding="utf-8"))
ORDER = [r["id"] for r in FULL["rules"]]
BY_ID = {r["id"]: r for r in FULL["rules"]}
ADDED = ["HKS-X42", "HKS-X95", "HKS-X96"]  # K24 J/L copy, K25 ellipse mask, K19/K20/K25 circle


# ---------- state: {"meta": {...}, "rules": [...], "indent": int, "sorted": bool}

def full_state(drop=()):
    return {"meta": {"schema": FULL["schema"], "stages": FULL["stages"]},
            "rules": [copy.deepcopy(r) for r in FULL["rules"] if r["id"] not in drop],
            "indent": 1, "sorted": False}


def dumps(obj, indent):
    return json.dumps(obj, ensure_ascii=False, indent=indent) + "\n"


def write(repo, layout, st):
    rules = sorted(st["rules"], key=lambda r: r["id"]) if st["sorted"] else st["rules"]
    if layout == "A":
        doc = dict(st["meta"], rules=rules)
        (repo / "rules.json").write_bytes(dumps(doc, st["indent"]).encode())
    else:
        d = repo / "rules"
        d.mkdir(exist_ok=True)
        (repo / "meta.json").write_bytes(dumps(st["meta"], st["indent"]).encode())
        keep = set()
        for r in rules:
            p = d / f"{r['id']}.json"
            keep.add(p.name)
            p.write_bytes(dumps(r, st["indent"]).encode())
        for p in d.glob("*.json"):
            if p.name not in keep:
                p.unlink()


def strict_load(text):
    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key " + ",".join(k for k in keys if keys.count(k) > 1))
        return dict(pairs)
    return json.loads(text, object_pairs_hook=hook)


def read(repo, layout):
    """Return {id: rule} or raise on bad JSON / duplicate keys / duplicate ids."""
    if layout == "A":
        rules = strict_load((repo / "rules.json").read_text(encoding="utf-8"))["rules"]
    else:
        rules = []
        for p in sorted((repo / "rules").glob("*.json")):
            r = strict_load(p.read_text(encoding="utf-8"))
            if r["id"] != p.stem:
                raise ValueError(f"{p.name} holds {r['id']}")
            rules.append(r)
    ids = [r["id"] for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate rule id")
    return {r["id"]: r for r in rules}


# ---------- transforms (state -> new state)

def add_at_original(rid):
    def f(st):
        st = copy.deepcopy(st)
        present = {r["id"] for r in st["rules"]}
        prev = [x for x in ORDER[:ORDER.index(rid)] if x in present]
        at = [r["id"] for r in st["rules"]].index(prev[-1]) + 1 if prev else 0
        st["rules"].insert(at, copy.deepcopy(BY_ID[rid]))
        return st
    return f


def add_at_end(rid):
    def f(st):
        st = copy.deepcopy(st)
        st["rules"].append(copy.deepcopy(BY_ID[rid]))
        return st
    return f


def supersede(rid, by):
    def f(st):
        st = copy.deepcopy(st)
        r = next(r for r in st["rules"] if r["id"] == rid)
        r["status"], r["superseded_by"], r["confirm"] = "superseded", by, None
        return st
    return f


def set_text(rid, text):
    def f(st):
        st = copy.deepcopy(st)
        next(r for r in st["rules"] if r["id"] == rid)["text"] = text
        return st
    return f


def resort(st):
    return dict(copy.deepcopy(st), sorted=True)


def reformat(st):
    return dict(copy.deepcopy(st), indent=2)


# ---------- git

def git(repo, *args, check=True):
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if check and p.returncode:
        raise RuntimeError(f"git {args}: {p.stdout}{p.stderr}")
    return p


def new_repo(name, layout, base, union):
    repo = WORK / name
    if repo.exists():
        shutil.rmtree(repo, onexc=lambda f, x, _: (os.chmod(x, stat.S_IWRITE), f(x)))
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "master")
    for k, v in (("core.autocrlf", "false"), ("commit.gpgsign", "false"),
                 ("user.name", "exp"), ("user.email", "exp@example.invalid")):
        git(repo, "config", k, v)
    if union:
        (repo / ".gitattributes").write_text("rules.json merge=union\n")
    write(repo, layout, base)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def changed_ids(a, b):
    return {i for i in a.keys() | b.keys() if a.get(i) != b.get(i)}


def run(name, layout, base, branches, union=False):
    """branches: [(branch name, transform)]; merged into master in this order."""
    repo = new_repo(f"{name}-{layout}{'-union' if union else ''}", layout, base, union)
    base_rules = {r["id"]: r for r in base["rules"]}
    out = {"scenario": name, "layout": layout, "union": union, "branches": [], "merges": []}
    for bname, fn in branches:
        git(repo, "checkout", "-q", "-b", bname, "master")
        write(repo, layout, fn(base))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", bname)
        ns = git(repo, "diff", "--numstat", "master", bname).stdout.split("\n")
        ns = [l.split("\t") for l in ns if l]
        out["branches"].append({"branch": bname, "files": len(ns),
                                "lines": sum(int(a) + int(d) for a, d, _ in ns)})
        git(repo, "checkout", "-q", "master")
    expected = base
    for bname, fn in branches:
        ours_ids = changed_ids(base_rules, {r["id"]: r for r in expected["rules"]})
        theirs_ids = changed_ids(base_rules, {r["id"]: r for r in fn(base)["rules"]})
        expected = fn(expected)
        exp_rules = {r["id"]: r for r in expected["rules"]}
        p = git(repo, "merge", "--no-ff", "-q", "-m", f"merge {bname}", bname, check=False)
        files = sorted({l.split("\t")[1] for l in git(repo, "ls-files", "-u").stdout.splitlines()})
        m = {"branch": bname, "conflicted": bool(files), "files": len(files), "hunks": 0,
             "false": None, "result": None}
        if files:
            for f in files:
                fp = repo / f
                if fp.exists():
                    m["hunks"] += sum(1 for l in fp.read_text(encoding="utf-8").splitlines()
                                      if l.startswith("<<<<<<<"))
            m["false"] = not (ours_ids & theirs_ids)
            m["result"] = "conflict"
        else:
            try:
                got = read(repo, layout)
                m["result"] = "correct" if got == exp_rules else \
                    f"WRONG (clean merge, {len(changed_ids(exp_rules, got))} rules differ)"
            except Exception as e:  # corrupt JSON, duplicate keys or ids
                m["result"] = f"CORRUPT ({type(e).__name__}: {str(e)[:60]})"
        out["merges"].append(m)
        if m["result"] != "correct":  # resolve to the known-right state so the next merge is fair
            write(repo, layout, expected)
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "--no-edit", "-m", f"resolve {bname}")
    return out


def scenarios():
    drop3 = full_state(drop=ADDED)
    drop1 = full_state(drop=["HKS-X95"])
    full = full_state()
    t1 = BY_ID["HKS-X96"]["text"]
    return [
        ("s1a_add3_original_pos", drop3, [(f"add-{r}", add_at_original(r)) for r in ADDED], "AB"),
        ("s1b_add3_append_end", drop3, [(f"add-{r}", add_at_end(r)) for r in ADDED], "A"),
        ("s2a_add_beside_supersede_prev", drop1,
         [("add-X95", add_at_original("HKS-X95")), ("supersede-X94", supersede("HKS-X94", "HKS-X96"))], "AB"),
        ("s2b_add_end_supersede_last", drop1,
         [("add-X95", add_at_end("HKS-X95")), ("supersede-X104", supersede("HKS-X104", "HKS-X103"))], "A"),
        ("s3_same_rule_two_edits", full,
         [("edit1", set_text("HKS-X96", t1 + " Ellipse first.")),
          ("edit2", set_text("HKS-X96", t1 + " Circle mask for faces."))], "AB"),
        ("s4a_resort_vs_add", drop1, [("resort", resort), ("add-X95", add_at_original("HKS-X95"))], "A"),
        ("s4a2_resort_vs_add_M3", full_state(drop=["M-3"]),
         [("resort", resort), ("add-M-3", add_at_original("M-3"))], "A"),
        ("s4b_reformat_vs_add", drop1, [("reformat", reformat), ("add-X95", add_at_original("HKS-X95"))], "AB"),
        ("s4c_reformat_vs_edit", full, [("reformat", reformat), ("supersede-X94", supersede("HKS-X94", "HKS-X96"))], "AB"),
    ]


def main():
    WORK.mkdir(exist_ok=True)
    results = []
    for name, base, branches, layouts in scenarios():
        for layout in layouts:
            results.append(run(name, layout, base, branches))
        results.append(run(name, "A", base, branches, union=True))
    (HERE / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    for r in results:
        tag = r["layout"] + ("+union" if r["union"] else "")
        adds = " ".join(f"{b['lines']}L/{b['files']}f" for b in r["branches"])
        ms = "; ".join(f"{m['branch']}: {m['result']}" + (f" files={m['files']} hunks={m['hunks']} false={m['false']}" if m["conflicted"] else "")
                       for m in r["merges"])
        print(f"{r['scenario']:32} {tag:8} diff[{adds}] | {ms}")
    shared = {r["scenario"] for r in results if r["layout"] == "B"}
    for label, keep in (("all scenarios", lambda r: True), ("scenarios B also ran", lambda r: r["scenario"] in shared)):
        for tag, sel in (("A", lambda r: r["layout"] == "A" and not r["union"]), ("B", lambda r: r["layout"] == "B"),
                         ("A+union", lambda r: r["union"])):
            ms = [m for r in results if sel(r) and keep(r) for m in r["merges"]]
            if tag == "B" and label == "all scenarios":
                continue
            print(f"TOTAL {label:22} {tag:8} merges={len(ms)} conflicted={sum(m['conflicted'] for m in ms)} "
                  f"false={sum(bool(m['false']) for m in ms)} corrupt={sum(str(m['result']).startswith('CORRUPT') for m in ms)} "
                  f"wrong={sum(str(m['result']).startswith('WRONG') for m in ms)}")


if __name__ == "__main__":
    main()
