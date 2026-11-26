"""Subject answer -> blind rendered paper edit + deterministic rubric score. Throwaway."""
import json, random, re, sys
from pathlib import Path

HERE = Path(__file__).parent
R = json.loads((HERE / "rubrics.json").read_text(encoding="utf-8"))


def clock(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"


def table(ep):
    L = json.loads((HERE / "prompts" / f"{ep}.lines.json").read_text(encoding="utf-8"))
    return L, {l[0]: i for i, l in enumerate(L)}


def answer(job):
    r = json.loads((HERE / "runs" / f"{job}.raw.json").read_text(encoding="utf-8"))
    text = r["result"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))


def body(ep, a):
    L, ix = table(ep)
    spans = [(ix[s["from"]], ix[s["to"]]) for s in a["spans"]]
    assert all(x <= y for x, y in spans), "backwards span"
    order = list(spans)
    for mv in a.get("moves", []) or []:
        src = next(s for s in order if L[s[0]][0] == mv["span"])
        order.remove(src)
        dst = next(k for k, s in enumerate(order) if L[s[0]][0] == mv["after"])
        order.insert(dst + 1, src)
    return L, ix, order


def kept_ids(L, order):
    return {L[i][0] for x, y in order for i in range(x, y + 1)}


def render(ep, a):
    L, ix, order = body(ep, a)
    kept = kept_ids(L, order)
    tot = sum(L[i][2] - L[i][1] for x, y in order for i in range(x, y + 1))
    scrub = lambda s: re.sub(r"\b(HKS-[A-Z]*\d+|M-\d+)\b", "", str(s))
    out = [f"# Paper edit (episode {ep})", "",
           f"Body: {len(order)} spans, {len(kept)} lines, {tot:.1f} s of kept lines (sum of line lengths).",
           f"Moves out of broadcast order: {len(a.get('moves') or [])}"]
    for mv in a.get("moves") or []:
        out.append(f"- span starting {mv['span']} plays right after the span starting {mv['after']}")
    out += ["", "## Hook options (not body)"]
    for k, h in enumerate(a.get("hooks", []), 1):
        out.append(f"### Option {k}: {scrub(h.get('kind', ''))}")
        for p in h["pieces"]:
            for i in range(ix[p["from"]], ix[p["to"]] + 1):
                l = L[i]
                out.append(f"{l[0]} [{clock(l[1])}] ({l[2] - l[1]:.1f}s) {l[3]}")
    out += ["", "## Body, in play order"]
    for n, (x, y) in enumerate(order, 1):
        d = sum(L[i][2] - L[i][1] for i in range(x, y + 1))
        out.append(f"### {n}. {L[x][0]}-{L[y][0]} [{clock(L[x][1])}-{clock(L[y][2])}] ({y - x + 1} lines, {d:.1f} s)")
        for i in range(x, y + 1):
            l = L[i]
            out.append(f"{l[0]} [{clock(l[1])}] ({l[2] - l[1]:.1f}s) {l[3]}")
    return "\n".join(out) + "\n", tot


def det_score(ep, a):
    """Deterministic score of the line-range items; judge items -> None."""
    L, ix, order = body(ep, a)
    kept = kept_ids(L, order)
    tot = sum(L[i][2] - L[i][1] for x, y in order for i in range(x, y + 1))
    share = lambda rg: sum(L[i][0] in kept for i in range(ix[rg[0]], ix[rg[1]] + 1)) / (ix[rg[1]] - ix[rg[0]] + 1)
    hooked = {L[i][0] for h in a.get("hooks", []) for p in h["pieces"] for i in range(ix[p["from"]], ix[p["to"]] + 1)}
    res = {}
    for it in R[ep]:
        k = it["kind"]
        if k == "keep":
            res[it["id"]] = not any(share(rg) >= 0.5 for rg in it["any"])
        elif k == "drop":
            res[it["id"]] = any(share(rg) >= 0.5 for rg in it["any"])
        elif k == "hook":
            rg = it["any"][0]
            res[it["id"]] = not any(L[i][0] in hooked for i in range(ix[rg[0]], ix[rg[1]] + 1))
        elif k == "moves":
            res[it["id"]] = bool(a.get("moves"))
        elif k == "length":
            res[it["id"]] = tot > 1200
        elif it["id"] == "B1":
            rg = it["lines"]
            res[it["id"]] = sum(L[i][2] - L[i][1] for i in range(ix[rg[0]], ix[rg[1]] + 1) if L[i][0] in kept) >= 20
        else:
            res[it["id"]] = None
    return res, tot


if __name__ == "__main__":
    jobs = sorted(p.name[:-9] for p in (HERE / "runs").glob("*.raw.json"))
    key_path = HERE / "judge" / "blind_key.json"
    (HERE / "judge").mkdir(exist_ok=True)
    key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.exists() else {}
    det = {}
    for job in jobs:
        ep = job.split("_")[0]
        try:
            a = answer(job)
            text, tot = render(ep, a)
        except Exception as e:
            print(job, "FAILED to parse/render:", repr(e))
            continue
        if job not in key.values():
            name = f"pe_{random.randrange(16**6):06x}"
            key[name] = job
        name = next(k for k, v in key.items() if v == job)
        (HERE / "judge" / f"{name}.md").write_text(text, encoding="utf-8")
        det[job] = det_score(ep, a)
        print(job, name, f"{tot:.0f}s", {k: v for k, v in det[job][0].items() if v})
    key_path.write_text(json.dumps(key, indent=1), encoding="utf-8")
    (HERE / "det_scores.json").write_text(json.dumps(det, indent=1), encoding="utf-8")
