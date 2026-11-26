"""Unblind and tabulate: judge breaks, deterministic breaks, agreement, cost/tokens per arm."""
import json, statistics as st
from pathlib import Path

HERE = Path(__file__).parent
R = json.loads((HERE / "rubrics.json").read_text(encoding="utf-8"))
leaked = {i["id"] for ep in R for i in R[ep] if i["leaked"]}
key = json.loads((HERE / "judge" / "blind_key.json").read_text(encoding="utf-8"))
det = json.loads((HERE / "det_scores.json").read_text(encoding="utf-8"))
rows, agree, total = {}, 0, 0
for name, job in sorted(key.items(), key=lambda kv: kv[1]):
    vf = HERE / "judge" / f"{name}.verdict.json"
    if not vf.exists():
        continue
    v = {i["id"]: i["verdict"] == "BREAK" for i in json.loads(vf.read_text(encoding="utf-8"))}
    d = det[job][0]
    for k, x in d.items():
        if x is not None:
            total += 1
            agree += (x == v.get(k))
    raw = json.loads((HERE / "runs" / f"{job}.raw.json").read_text(encoding="utf-8"))
    u = raw["usage"]
    jr = json.loads((HERE / "judge" / f"{name}.raw.json").read_text(encoding="utf-8"))
    rows[job] = dict(name=name, judge=sum(v.values()), judge_noleak=sum(x for k, x in v.items() if k not in leaked),
                     det=sum(bool(x) for x in d.values()), len_s=round(det[job][1]),
                     breaks=sorted(k for k, x in v.items() if x),
                     disagree=sorted(k for k, x in d.items() if x is not None and x != v.get(k)),
                     cost=raw["total_cost_usd"], judge_cost=jr["total_cost_usd"],
                     in_tok=u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"],
                     out_tok=u["output_tokens"], models=sorted(raw.get("modelUsage", {})))
for job, r in rows.items():
    print(job, r)
print(f"\njudge vs deterministic agreement on line-range items: {agree}/{total}")
for ep in ("1125", "1126"):
    print(f"\nepisode {ep} ({len(R[ep])} items, {sum(i['leaked'] for i in R[ep])} leaked)")
    for arm in ("full", "short"):
        rs = [r for j, r in rows.items() if j.startswith(f"{ep}_{arm}_") and not j.endswith("adv")]
        if rs:
            for k in ("judge", "judge_noleak", "det"):
                xs = [r[k] for r in rs]
                print(f"  {arm:5} {k:12} {xs} mean {st.mean(xs):.1f} range {max(xs) - min(xs)}")
for arm in ("full", "short"):
    rs = [r for j, r in rows.items() if f"_{arm}_" in j and not j.endswith("adv")]
    if rs:
        print(f"{arm}: runs {len(rs)} cost {sum(r['cost'] for r in rs):.2f} in_tok {sum(r['in_tok'] for r in rs)} out_tok {sum(r['out_tok'] for r in rs)}")
print("judge cost", round(sum(r["judge_cost"] for r in rows.values()), 2))
