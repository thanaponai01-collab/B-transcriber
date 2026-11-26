"""Build the 4 subject prompts (2 episodes x 2 arms) and the shown-line tables. Throwaway."""
import json
from pathlib import Path

HERE = Path(__file__).parent
S = HERE.parent
J = Path(r"E:/Me/5.Claude/Transcriber_v2/test_projects/hks_judge")


def clock(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"


# --- 1125: the real one-shot judge prompt's own context paragraph and transcript, rule block removed
p25 = (J / "20261125/v1/20261125/cut.prompt.md").read_text(encoding="utf-8").splitlines()
ctx25 = "\n".join(p25[:9]) + "\nof speech, with its position in the broadcast."
tx25 = "\n".join(p25[p25.index("## Transcript") + 1:])
lines25 = list(json.loads((J / "20261125/v1/20261125/cut.lines.json").read_text(encoding="utf-8")).values())[0]["lines"]

# --- 1126: questions line table (drops hidden), sponsors removed by seconds, question headers
q = list(json.loads((J / "20261126/questions.lines.json").read_text(encoding="utf-8")).values())[0]["lines"]
sl = list(json.loads((J / "20261126/sponsors.lines.json").read_text(encoding="utf-8")).values())[0]["lines"]
six = {x[0]: x for x in sl}
spons = [(six[s["from"]][1], six[s["to"]][2]) for s in json.loads((J / "20261126/sponsors.answer.json").read_text(encoding="utf-8"))["spans"]]
lines26 = [l for l in q if not any(a <= (l[1] + l[2]) / 2 <= b for a, b in spons)]
qa = json.loads((J / "20261126/questions.answer.json").read_text(encoding="utf-8"))
qix = {x[0]: x for x in q}
heads = sorted(((qix[t["start"]][1], t["story"], t["title"]) for t in qa["topics"]))
body = []
for l in lines26:
    while heads and heads[0][0] <= l[1] + 0.05:
        _, story, title = heads.pop(0)
        body.append(f"=== question (part {story}): {title} ===")
    body.append(f"{l[0]} [{clock(l[1])}] ({l[2] - l[1]:.1f}s) {l[3]}")
tx26 = "\n".join(body)
ctx26 = """You are helping edit a Thai live news-talk show, โหนกระแส. The host (คุณหนุ่ม กรรชัย) interviews guests about a news
incident. Today: accusations about คุณกัน จอมพลัง's foundation and money, on the day he is questioned at DSI. In the
studio: ทนายนรเศษ, a lawyer who has long tracked คุณกัน's business, and ดร.ธนกฤษ, former deputy minister of justice, who
explains DSI. The talk covers the foundation's unfiled accounts, a พรพิมล account on a gambling site, and money through
a gold shop and a claw-machine company. Phone calls later: คุณพุทธ, and a long call with คุณกิ๊ก the gold-shop owner.
Then คุณกัน's live interview at DSI (an insert with its own sound), a woman who claims she bought a gambling site from
him, the field reporter ดิน at DSI, คุณกัน paying back a million in transfers of 49,999, whether voice clips count as
evidence, a voice clip of คุณแหม่ม, คุณก้อง asking for money back, and the host's close. The broadcast runs about two
hours: first the TV part, then a social-media-only part.
The words below are an automatic transcript (it has errors; names are often misspelt), one numbered line per stretch
of speech, with its position in the broadcast."""

TASK = """Task: write the paper edit for the YouTube long form, 17 to 20 minutes (the kept lines must total 1020 to 1200 s;
each line's length is in brackets). Choose the lines to KEEP; everything else is cut. Also give options for the
cold-open hook (the short opening before the title that makes a viewer stay). Opening titles, ad breaks, sponsor reads
and credits are already removed from the transcript. Lines starting with === (if any) are question names, not lines.

Answer with JSON only, in this shape:
{"spans": [{"from": "L0123", "to": "L0130", "why": "<what this keep is>"}],
 "moves": [{"span": "L0456", "after": "L0130", "why": "<why it plays better there>"}],
 "hooks": [{"kind": "<how it is built>", "pieces": [{"from": "L0400", "to": "L0401"}], "why": "<why it hooks>"}],
 "ending": "<one sentence: how the cut ends and whether the story is open>"}
"spans" in broadcast order, not overlapping, "from" not after "to". A move names a kept span by its "from" line and
the span it should play right after (by that span's "from" line); "moves" may be empty. Use only line ids shown."""


def prompt(ctx, arm, tx):
    skill = (S / "arms" / f"paper_edit_{arm}.md").read_text(encoding="utf-8")
    return (f"{ctx}\n\nThe editor's rule book for this step (the hks-paper-edit skill) follows. Follow it.\n\n"
            f"<skill>\n{skill.strip()}\n</skill>\n\n{TASK}\n\n## Transcript\n{tx}\n")


out = HERE / "prompts"
out.mkdir(exist_ok=True)
for ep, ctx, tx, lines in (("1125", ctx25, tx25, lines25), ("1126", ctx26, tx26, lines26)):
    (out / f"{ep}.lines.json").write_text(json.dumps(lines, ensure_ascii=False), encoding="utf-8")
    for arm in ("full", "short"):
        (out / f"{ep}_{arm}.md").write_text(prompt(ctx, arm, tx), encoding="utf-8")
    print(ep, len(lines), "lines", len(tx), "chars")
