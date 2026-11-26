"""Run subject cells in order; raw stdout saved before parsing; existing runs skipped; stop at the cap.
usage: python run_subjects.py 1126_short_1 1125_full_1 ..."""
import json, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).parent
RUNS = HERE / "runs"
RUNS.mkdir(exist_ok=True)
CAP = 15.0


def spent():
    tot = 0.0
    for f in list(RUNS.glob("*.raw.json")) + list((HERE / "judge").glob("*.raw.json")):
        try:
            tot += json.loads(f.read_text(encoding="utf-8")).get("total_cost_usd", 0.0)
        except Exception:
            pass
    return tot


for job in sys.argv[1:]:
    ep, arm, n = job.split("_")
    raw = RUNS / f"{job}.raw.json"
    if raw.exists():
        print(job, "exists, skipped", flush=True)
        continue
    est = 1.9 if ep == "1126" else 1.4
    if spent() + 0.25 + est > CAP - 1.5:  # 0.25: advisor-off probe calls; 1.5 kept for the judges
        print(job, f"stopped: spent {spent():.2f}", flush=True)
        break
    prompt = (HERE / "prompts" / f"{ep}_{arm}.md").read_text(encoding="utf-8")
    t0 = time.time()
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run(["claude", "-p", "--model", "opus", "--tools", "", "--strict-mcp-config",
                            "--no-session-persistence", "--output-format", "json",
                            # user settings carry advisorModel=fable (the probe run called it): load none, keep effort
                            "--setting-sources", "project", "--settings", '{"effortLevel": "medium"}'],
                           input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=1800)
    raw.write_text(p.stdout or json.dumps({"error": p.stderr}), encoding="utf-8")
    try:
        r = json.loads(p.stdout)
        u = r.get("usage", {})
        print(job, f"{time.time() - t0:.0f}s cost {r.get('total_cost_usd')} in {u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)} out {u.get('output_tokens')} err={r.get('is_error')} total_spent {spent():.2f}", flush=True)
    except Exception as e:
        print(job, "unparseable stdout", e, p.stderr[:500], flush=True)
