"""Pseudo-label purity measured by a person: a seeded sample of kept footage cues, a local review
page, and the character error rate of the sample against what the reviewer heard.

    # draw the sample and cut each cue's exact audio span
    python -m tools.purity_review sample output/pseudo_label/footage.jsonl --dir output/purity
    # review in the browser at http://127.0.0.1:8020 (every edit is saved to corrections.json)
    python -m tools.purity_review serve --dir output/purity
    # CER of the reviewed cues, with a bootstrap CI and the verdict against MAX_CER
    python -m tools.purity_review score --dir output/purity

The reviewer fixes what was misheard and leaves the script alone: an English term the pipeline
wrote in Thai stays in Thai and is ticked instead, so the number does not set the loanword policy.
The page starts each cue from the pipeline's text, which biases the result optimistic.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pseudo_label import _config, _norm  # noqa: E402

THRESHOLD = 0.95
MAX_CER = 0.05
SAMPLE_SIZE = 150
SEED = 20261128


def draw(labels: Path, n: int = SAMPLE_SIZE, threshold: float = THRESHOLD, seed: int = SEED) -> list[dict]:
    rows = [json.loads(line) for line in labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [r for r in rows if "start_ms" in r and (r["confidence"] or 0.0) >= threshold]
    picked = random.Random(seed).sample(kept, min(n, len(kept)))
    return [{"id": i, "file": r["file"], "start_ms": r["start_ms"], "end_ms": r["end_ms"],
             "hyp": r["text"], "clip": f"clips/{i:03d}.mp3"} for i, r in enumerate(picked)]


def sample(labels: Path, out: Path) -> None:
    items = draw(labels)
    (out / "clips").mkdir(parents=True, exist_ok=True)
    for it in items:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{it['start_ms'] / 1000:.3f}",
                        "-to", f"{it['end_ms'] / 1000:.3f}", "-i", it["file"], "-ac", "1", "-ar", "16000",
                        "-b:a", "64k", str(out / it["clip"])], check=True)
    (out / "sample.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[purity] {len(items)} cues from {len({it['file'] for it in items})} files -> {out}")


def score(items: list[dict], corrections: dict, config: dict, seed: int = SEED, n_boot: int = 2000) -> dict:
    """Errors over reference characters for the reviewed cues. A cue marked no-speech has an empty
    reference, so every character the pipeline wrote there counts as an error."""
    from rapidfuzz.distance import Levenshtein
    per = []
    for it in items:
        c = corrections.get(str(it["id"]))
        if c is None:
            continue
        hyp = _norm(it["hyp"], config)
        ref = "" if c.get("no_speech") else _norm(c["text"], config)
        per.append({"file": it["file"], "errors": Levenshtein.distance(hyp, ref), "ref_len": len(ref),
                    "thai_loanword": bool(c.get("thai_loanword")),
                    "minutes": (it["end_ms"] - it["start_ms"]) / 60000})
    if not per:
        return {"reviewed": 0}

    def cer(rows: list[dict]) -> float:
        return sum(r["errors"] for r in rows) / max(1, sum(r["ref_len"] for r in rows))

    rng = random.Random(seed)
    boots = sorted(cer([rng.choice(per) for _ in per]) for _ in range(n_boot))
    lo, hi = boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
    verdict = "pass" if hi <= MAX_CER else "fail" if lo > MAX_CER else "unresolved"
    by_file: dict[str, list[dict]] = {}
    for r in per:
        by_file.setdefault(r["file"], []).append(r)
    return {"reviewed": len(per), "of": len(items), "cer": round(cer(per), 4), "ci": [round(lo, 4), round(hi, 4)],
            "verdict": verdict, "max_cer": MAX_CER,
            "thai_loanword_share": round(sum(r["thai_loanword"] for r in per) / len(per), 3),
            "thai_loanword_minutes_share": round(sum(r["minutes"] for r in per if r["thai_loanword"])
                                                 / sum(r["minutes"] for r in per), 3),
            "by_file": {Path(f).name: {"cues": len(rs), "cer": round(cer(rs), 4)} for f, rs in sorted(by_file.items())}}


PAGE = """<!doctype html><meta charset="utf-8"><title>Purity review</title>
<style>
:root{--bg:#fff;--fg:#111;--mut:#666;--line:#ddd;--acc:#1a5fd0}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#eee;--mut:#9aa;--line:#333;--acc:#6ea8ff}}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:0 auto;padding:16px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0}.card.done{opacity:.55}
textarea{width:100%;box-sizing:border-box;font:20px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-radius:6px;padding:8px}small,.mut{color:var(--mut)}audio{width:100%}
label{margin-right:16px}</style>
<h1>Purity review</h1>
<p>Listen, then fix only what was <b>misheard</b>. If an English term is written in Thai, leave it in
Thai and tick the box. Tick <i>no speech</i> if nothing (or only noise) is said. Saving is automatic.
<b>Ctrl+Enter</b> saves and plays the next cue; <b>Ctrl+Space</b> replays.</p>
<p class=mut id=progress></p><div id=list></div>
<script>
let items=[],corr={};
const save=async(it,card)=>{const c={text:card.querySelector('textarea').value,
 thai_loanword:card.querySelector('.tl').checked,no_speech:card.querySelector('.ns').checked};
 corr[it.id]=c;await fetch('/save',{method:'POST',body:JSON.stringify({id:it.id,...c})});
 card.classList.add('done');progress()};
const progress=()=>document.getElementById('progress').textContent=
 Object.keys(corr).length+' of '+items.length+' reviewed';
(async()=>{items=await (await fetch('/sample.json')).json();corr=await (await fetch('/corrections.json')).json();
const list=document.getElementById('list');items.forEach((it,k)=>{const c=corr[it.id];const card=document.createElement('div');
card.className='card'+(c?' done':'');card.innerHTML=`<small>${k+1} / ${items.length}</small>
<audio controls preload=none src="${it.clip}"></audio><textarea rows=2></textarea>
<label><input type=checkbox class=tl> English term written in Thai</label><label><input type=checkbox class=ns> no speech</label>`;
const ta=card.querySelector('textarea');ta.value=c?c.text:it.hyp;card.querySelector('.tl').checked=!!(c&&c.thai_loanword);
card.querySelector('.ns').checked=!!(c&&c.no_speech);
card.querySelectorAll('input').forEach(i=>i.onchange=()=>save(it,card));ta.onchange=()=>save(it,card);
ta.onkeydown=e=>{const a=card.querySelector('audio');if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();save(it,card);
const nx=card.nextElementSibling;if(nx){nx.scrollIntoView({block:'center'});nx.querySelector('textarea').focus();nx.querySelector('audio').play()}}
if(e.ctrlKey&&e.code==='Space'){e.preventDefault();a.currentTime=0;a.play()}};list.appendChild(card)});progress();
const first=[...list.children].find(c=>!c.classList.contains('done'));if(first){first.scrollIntoView({block:'center'});first.querySelector('textarea').focus()}})();
</script>"""


def serve(out: Path, port: int) -> None:
    corr_path = out / "corrections.json"

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            name = self.path.split("?")[0].lstrip("/")
            if name == "":
                return self._send(PAGE.encode(), "text/html; charset=utf-8")
            if name == "corrections.json" and not corr_path.exists():
                return self._send(b"{}", "application/json")
            target = (out / name).resolve()
            if out.resolve() not in target.parents or not target.is_file():
                return self.send_error(404)
            ctype = "audio/mpeg" if target.suffix == ".mp3" else "application/json"
            self._send(target.read_bytes(), ctype)

        def do_POST(self) -> None:
            if self.path != "/save":
                return self.send_error(404)
            c = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            corr = json.loads(corr_path.read_text(encoding="utf-8")) if corr_path.exists() else {}
            corr[str(c.pop("id"))] = c
            tmp = corr_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(corr, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(corr_path)
            self._send(b"{}", "application/json")

        def log_message(self, *args) -> None:
            pass

    print(f"[purity] reviewing {out} at http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("labels", type=Path)
    for p in (s, sub.add_parser("serve"), sub.add_parser("score")):
        p.add_argument("--dir", type=Path, default=Path("output/purity"))
    sub.choices["serve"].add_argument("--port", type=int, default=8020)
    args = parser.parse_args()
    if args.cmd == "sample":
        sample(args.labels, args.dir)
    elif args.cmd == "serve":
        serve(args.dir, args.port)
    else:
        items = json.loads((args.dir / "sample.json").read_text(encoding="utf-8"))
        corr_path = args.dir / "corrections.json"
        corr = json.loads(corr_path.read_text(encoding="utf-8")) if corr_path.exists() else {}
        print(json.dumps(score(items, corr, _config()), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
