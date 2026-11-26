"""Rubric per episode, written before any subject run. Each item is binary: BREAK or OK.

kind:
  keep   BREAK if fewer than half of the lines in `lines` are in body spans (any one range of `any` is enough)
  drop   BREAK if half or more of the lines in `lines` are in body spans (`any`: any one range is enough to break)
  hook   BREAK if no hook option has a piece with a line in `lines`
  moves  BREAK if the paper edit moves any span out of broadcast order
  length BREAK if body total is over 1200 s
  judge  read the text; the check says how
leaked: the full arm's text names this exact passage or material (the short arm's title does not).
"""
import json
from pathlib import Path

R = {
 "1125": [
  dict(id="A1", rule="Set-up: where the houses and the shop are (K21/HKS-X89/X98)", kind="keep",
       any=[["L0194", "L0196"], ["L0231", "L0237"]], leaked=True,
       check="Keep the 'where' set-up: the house vs Off's shop (L0194-L0196, 0:08:00) or the rebuilt house turned away from the shop (L0231-L0237, 0:09:39). BREAK if neither range has at least half its lines in body spans."),
  dict(id="A2", rule="Set-up: the Loy Krathong night (K21 diff)", kind="keep", any=[["L0891", "L0916"]], leaked=False,
       check="Keep the daughter's Loy Krathong night account ('มาล้างแค้นตอนโต', L0891-L0916, 0:46:47-0:47:46). BREAK if fewer than half of those lines are in body spans."),
  dict(id="A3", rule="Hook opens on the attack clip with its own sound (K21 diff, HKS-X90)", kind="hook", any=[["L0332", "L0349"]], leaked=True,
       check="At least one hook option uses the attack clip's own sound (L0332-L0349, 0:15:39-0:16:11). BREAK if no hook option has a piece touching those lines."),
  dict(id="A4", rule="Body plays the attack clip where the story reaches it (K21 diff, HKS-X90)", kind="keep", any=[["L0332", "L0349"]], leaked=True,
       check="BREAK if fewer than half of L0332-L0349 (the clip's own sound) are in body spans."),
  dict(id="A5", rule="The practical resolution is kept (D20)", kind="keep", any=[["L1431", "L1481"]], leaked=False,
       check="Keep the shop licence and the 17:00-18:00 working-hours deal (L1431-L1481, 1:12:11-1:14:30). BREAK if fewer than half of those lines are in body spans."),
  dict(id="A6", rule="Retelling dropped: Off retells the fight (D21)", kind="drop", any=[["L1060", "L1084"]], leaked=False,
       check="BREAK if half or more of L1060-L1084 (0:53:54-0:55:06) are in body spans."),
  dict(id="A7", rule="Back-and-forth dropped: who came with friends (D21)", kind="drop", any=[["L1157", "L1169"]], leaked=False,
       check="BREAK if half or more of L1157-L1169 (0:58:44-0:59:22) are in body spans."),
  dict(id="A8", rule="Lawyer's lead-in dropped: section 68 lead-in and penalty line (D22)", kind="drop", any=[["L0784", "L0793"]], leaked=False,
       check="BREAK if half or more of L0784-L0793 (0:39:05-0:39:42) are in body spans."),
  dict(id="A9", rule="จ่าคิง's intake dropped (D22)", kind="drop", any=[["L0803", "L0808"]], leaked=False,
       check="BREAK if half or more of L0803-L0808 (0:40:11-0:40:37) are in body spans."),
  dict(id="A10", rule="Police chief's first part dropped (D22)", kind="drop", any=[["L1693", "L1697"]], leaked=False,
       check="BREAK if half or more of L1693-L1697 (1:23:32-1:23:52) are in body spans."),
  dict(id="A11", rule="No piece ends mid-thought (K22)", kind="judge", leaked=False,
       check="Read the last line of every body span. BREAK if two or more spans end mid-thought: on a joining word (ก็ / คือ / แล้ว / แต่ / เพราะ / ว่า / ที่), on '...แล้วกันพี่', or on an unanswered half-question."),
  dict(id="A12", rule="The body does not open cold (K21)", kind="judge", leaked=False,
       check="Read the first 60 s of the body (in play order). BREAK if it opens on a detail or speech that needs facts the viewer has not been given (who the family is, the shop next door, what happened between them)."),
 ],
 "1126": [
  dict(id="B1", rule="The host's on-air intro is cut (D26, HKS-22/C4)", kind="judge", lines=["L0002", "L0088"], leaked=False,
       check="The host's opening (why today, DSI called him, the guest intro) is L0002-L0088 (0:00:25-0:04:13). BREAK if body spans keep 20 s or more of those lines (sum the bracketed line lengths)."),
  dict(id="B2", rule="Broadcast order kept (D31, HKS-5)", kind="moves", leaked=False,
       check="BREAK if the paper edit has any move (a span played out of broadcast order)."),
  dict(id="B3", rule="Length within the 20-minute line (V17)", kind="length", leaked=False,
       check="BREAK if the body's kept lines total more than 1200 s."),
  dict(id="B4", rule="Story kept, not dropped for length: the ธรรมนัส clause (D25, HKS-X109)", kind="keep", any=[["L0094", "L0104"]], leaked=True,
       check="Keep the foundation's ธรรมนัส clause (L0094-L0104, 0:04:30-0:04:54). BREAK if fewer than half of those lines are in body spans."),
  dict(id="B5", rule="Story kept: คุณกิ๊ก's own donation (D25, HKS-X109)", kind="keep", any=[["L1859", "L1867"]], leaked=True,
       check="Keep คุณกิ๊ก saying she donated and bought things for him, with proof (L1859-L1867, 1:16:46-1:17:12). BREAK if fewer than half of those lines are in body spans."),
  dict(id="B6", rule="Story kept: the host's face-scan case (D25, HKS-X109)", kind="keep", any=[["L1944", "L1962"]], leaked=True,
       check="Keep the host's case that 49,999 transfers avoid the face scan (L1944-L1962, 1:21:05-1:21:57). BREAK if fewer than half of those lines are in body spans."),
  dict(id="B7", rule="Explainer read-out cut: what DSI will ask (D27)", kind="drop", any=[["L0323", "L0335"]], leaked=False,
       check="BREAK if half or more of L0323-L0335 (0:14:49-0:15:31) are in body spans."),
  dict(id="B8", rule="Explainer read-out cut: the 'all coincidence' reading (D27)", kind="drop", any=[["L1283", "L1297"]], leaked=False,
       check="BREAK if half or more of L1283-L1297 (0:53:15-0:53:40) are in body spans."),
  dict(id="B9", rule="Side passage cut: why no police report (D28)", kind="drop", any=[["L0942", "L0973"]], leaked=False,
       check="BREAK if half or more of L0942-L0973 (0:41:14-0:42:16) are in body spans."),
  dict(id="B10", rule="Side passage cut: คุณพุทธ's phone correction (D28)", kind="drop", any=[["L1631", "L1657"]], leaked=False,
       check="BREAK if half or more of L1631-L1657 (1:06:21-1:08:03) are in body spans."),
  dict(id="B11", rule="DSI talking insert not used as body (D29)", kind="drop", any=[["L2043", "L2059"], ["L2096", "L2112"]], leaked=False,
       check="BREAK if half or more of L2043-L2059 (1:25:17-1:26:05) or half or more of L2096-L2112 (1:27:44-1:28:50) are in body spans."),
  dict(id="B12", rule="The host's closing verdict is cut (D28)", kind="drop", any=[["L2970", "L2990"]], leaked=False,
       check="BREAK if half or more of L2970-L2990 (2:05:10-2:06:01) are in body spans."),
  dict(id="B13", rule="Online part used: คุณกัน's message to พี่หนุ่ม (D30, HKS-22)", kind="keep", any=[["L2132", "L2167"]], leaked=False,
       check="Keep คุณกัน's message to พี่หนุ่ม (L2132-L2167, 1:30:01-1:31:48). BREAK if fewer than half of those lines are in body spans."),
  dict(id="B14", rule="Online part used: the แหม่ม clip with the host's reaction (D30)", kind="keep", any=[["L2665", "L2683"]], leaked=False,
       check="Keep the แหม่ม voice clip and the host's reaction (L2665-L2683, 1:52:45-1:53:47). BREAK if fewer than half of those lines are in body spans."),
 ],
}

HEAD = """# Rubric, episode {ep}

Score a paper edit (which lines stay in the YouTube long form, their order, the hook options) against the user's own
corrections of this episode. Every item is BREAK or OK. Score from the paper edit alone: its body spans (line id ranges,
inclusive, in play order), its moves, its hook options and its total. A line id range like L0194-L0196 means every
line from L0194 to L0196 in the transcript; "in body spans" means the line falls inside one of the body's from-to
ranges. Hook pieces do not count as body. Count lines by id; when a span covers part of a range, count only the lines
inside it.

"""

if __name__ == "__main__":
    here = Path(__file__).parent
    for ep, items in R.items():
        md = HEAD.format(ep=ep) + "\n".join(
            f"- **{i['id']}** {i['rule']}.\n  How to score: {i['check']}" for i in items) + "\n"
        (here / f"rubric_{ep}.md").write_text(md, encoding="utf-8")
    (here / "rubrics.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
    print({ep: len(v) for ep, v in R.items()})
