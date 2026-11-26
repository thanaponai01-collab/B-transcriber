"""Blind sonnet judge per rendered paper edit. Raw saved; existing skipped. usage: python run_judges.py"""
import json, re, subprocess, tempfile, time
from pathlib import Path

HERE = Path(__file__).parent
JD = HERE / "judge"
key = json.loads((JD / "blind_key.json").read_text(encoding="utf-8"))

ASK = """You score one video paper edit against a rubric. Read the rubric, then the paper edit. For each rubric item
decide BREAK or OK exactly as its "How to score" says, using only the paper edit. Check line ids carefully: a body span
Lxxxx-Lyyyy includes every line id between them. Answer with JSON only:
{"items": [{"id": "A1", "verdict": "BREAK" or "OK", "evidence": "<one line: which spans/lines decided it>"}]}"""

for name, job in sorted(key.items()):
    raw = JD / f"{name}.raw.json"
    if raw.exists():
        continue
    ep = job.split("_")[0]
    rubric = (HERE / f"rubric_{ep}.md").read_text(encoding="utf-8")
    pe = (JD / f"{name}.md").read_text(encoding="utf-8")
    prompt = f"{ASK}\n\n<rubric>\n{rubric}</rubric>\n\n<paper_edit>\n{pe}</paper_edit>\n"
    t0 = time.time()
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run(["claude", "-p", "--model", "sonnet", "--tools", "", "--strict-mcp-config",
                            "--no-session-persistence", "--output-format", "json"],
                           input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=1200)
    raw.write_text(p.stdout or json.dumps({"error": p.stderr}), encoding="utf-8")
    r = json.loads(p.stdout)
    items = json.loads(re.search(r"\{.*\}", r["result"], re.S).group(0))["items"]
    (JD / f"{name}.verdict.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(name, f"{time.time() - t0:.0f}s cost {r.get('total_cost_usd'):.3f}",
          "breaks", [i["id"] for i in items if i["verdict"] == "BREAK"], flush=True)
