"""Build corrections_verbal.json and check every quoted fragment against the raw user text."""
import ast, json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.expanduser('~/.claude/projects/E--Me-5-Claude-Transcriber-v2')

# corpus: (session, when) -> list of texts
corpus = {}
sess = None
for line in open(os.path.join(HERE, 'usermsgs_full.txt'), encoding='utf-8'):
    line = line.rstrip('\n')
    if line.startswith('=== AskUserQuestion'):
        sess = 'ASK'; continue
    if line.startswith('=== '):
        sess = line[4:12]; continue
    if sess == 'ASK':
        s, md, hm, rest = line.split(' ', 3)
        key = (s, f'{md} {hm}')
    else:
        md, hm, rest = line.split(' ', 2)
        key = (sess, f'{md} {hm}')
    try:
        txt = ast.literal_eval(rest)
    except Exception:
        txt = rest
    corpus.setdefault(key, []).append(txt)

# queued messages typed while the agent worked (absent from usermsgs_full.txt)
from datetime import datetime, timedelta
for f in os.listdir(D):
    if not f.endswith('.jsonl') or f[:8] not in ('eeb22609', 'd6cbb4b9', 'cece435c'):
        continue
    for l in open(os.path.join(D, f), encoding='utf-8'):
        try: o = json.loads(l)
        except Exception: continue
        if o.get('type') == 'attachment' and (o.get('attachment') or {}).get('type') == 'queued_command':
            ts = o['timestamp']
            lt = (datetime.fromisoformat(ts.replace('Z', '+00:00')) + timedelta(hours=7)).strftime('%m%d %H:%M')
            corpus.setdefault((f[:8], lt), []).append(o['attachment']['prompt'])

R = []
def row(k, when, session, episode, source, words, mistake, repeat_of=(), confidence='high', acceptance=None):
    R.append(dict(k=k, when=when, session=session, episode=episode, source=source, words=words,
                  mistake=mistake, repeat_of=list(repeat_of), confidence=confidence,
                  acceptance=acceptance or ('k_match' if k else 'new')))

T, V, M = 'teaching', 'verbal', 'red_marker'
E20 = '20261120'
# ---- 0930: topic-cut design talk, user describing own practice
row(None, '0930 12:31', 'e5c69065', '20260929', T,
    "what i want to cut is avoid jump cut, i want it to cut where the video or live cut to different scenes",
    "(teaching) avoid jump cuts; cut only where the broadcast itself changes scene", confidence='low')
# ---- 1120: user narrates own edit (c661e379)
c = 'c661e379'
row(None, '1120 16:09', c, E20, T,
    "the 7:40 part is sponsor, i always cut it, 13:45 cut the sponsor as well",
    "(teaching) sponsor segments are always cut")
row(None, '1120 16:09', c, E20, T,
    "the backup sequence is for insert, on the main footage, like i see the part where, i can use later like footage of the scene, or person doing nothing,",
    "(teaching) Backup sequence holds the inserts: scene footage and people doing nothing")
row(None, '1120 16:23', c, E20, T,
    "when i lift to V2 that means i pick that part to cutting, yes i go into order following the flow of story",
    "(teaching) picked pieces go up to V2, ordered by the story's flow")
row(None, '1120 16:23', c, E20, T,
    "i try to cut to the topic as quick as i can not much of a background story",
    "(teaching) get into the topic fast, little background story")
row(None, '1120 16:34', c, E20, T,
    "at first host clarifying, sometime i keep it, sometime i cut it out go straight to story, when i use host is when the story at first too long and not get into the story, i would summary by host",
    "(teaching) host set-up kept only when it summarises a slow start")
row(None, '1120 16:38', c, E20, T,
    "this video we dont use jumpt cut, but we can cut it agreesive when there is b roll cover it, or create another scene for it like the scene where someone static, and talker talks",
    "(teaching) no jump cuts; cut hard only under B-roll or a static-listener shot")
row(None, '1120 16:38', c, E20, T,
    "overall clip stay within 15-20 mins can be above a bit",
    "(teaching) YT long form length 15-20 min")
row(None, '1120 16:45', c, E20, T,
    "its the clip in the same story, sometime same moment as they talk, only footage in the actual footage we have, sometime there is no b roll, we can find like scene static perom",
    "(teaching) cover B-roll comes from the same story and moment; else a static person")
row(None, '1120 16:45', c, E20, T,
    "i try to make it talking in one time, like no repeat story, to keep it concise",
    "(teaching) each story told once, concise")
row(None, '1120 18:05', c, E20, T,
    "sometime like host reaction i add it in to add drama, but opinion in the story no, viewer i always cut",
    "(teaching) host reactions may stay for drama; host opinion and viewer comments are cut")
row(None, '1120 18:16', c, E20, T,
    "swear words mainly bleep them, the end same as every episode",
    "(teaching) bleep swear words; same ending every episode")
row(None, '1120 18:35', c, E20, T,
    "if there is the most violent part or emotinal moment, if not i may pick things like something the climax, lead into climax, like what!, things that bad, always the same music",
    "(teaching) hook = most violent/emotional moment or the climax, same music")
row(None, '1120 18:36', c, E20, T,
    "things that have the time on the top left i always blur them, and insert or b roll always full with to banner if its already run in full that fine, if its in the small window needed to be zommed in",
    "(teaching) blur the TV clock; full-frame inserts stay as is, small-window inserts get zoomed")
row(None, '1120 18:38', c, E20, T,
    "film damage on all b roll, v9 blur is the clip logo and credit of video that get cut",
    "(teaching) film damage on all B-roll; blur clip logos and credits")
row(None, '1120 18:40', c, E20, T,
    "the music is around -33db and Highlight is -24db, in the end -12 db",
    "(teaching) audio levels: music -33 dB, highlight -24 dB, end -12 dB")
row(None, '1120 19:30', c, E20, T,
    "yes 1080x1080, fb always 2:59:24 mins or not above or equal 3 mins, main story only, scale, the b roll need to be filled full page, or if that broll is standalone with banner keep it fit to frame, ending no end logo always",
    "(teaching) FB cut: 1080x1080, under 3:00, main story only, B-roll fills frame, no end logo")
row(None, '1120 19:35', c, E20, T,
    "fb hook always same as youtube,  choosing is the climax of the story",
    "(teaching) FB hook is the YT hook, the climax")
row(None, '1120 19:35', c, E20, T,
    "the footage in this fb d1 comes from yt d1 mainly that i already edit, it the exact same things i just copy here and trim or re oganize to fit the 3 mins",
    "(teaching) FB is derived from YT D1 by copy and trim, not rebuilt")
row(None, '1120 19:42', c, E20, T,
    "its the same as fb d1 but trim to 1 min, and its in the 4 reel with frame,",
    "(teaching) 1-min square derived from FB D1, trimmed to 1 min, in the 4-reel frame")
row(None, '1120 19:44', c, E20, T,
    "is the dupplicate of fb d1, i just dupplicate there and remove the logo then put it in 5 reel,",
    "(teaching) 5-reel cut derived from FB D1, logo removed")

# ---- 1123 day setup and drafts
E23 = '20261123'
row(None, '1123 16:24', 'd6cbb4b9', E23, V,
    "and what you didnt do is flag the break, sponsore",
    "question markers left the breaks and the sponsor unflagged", ['1120 16:09'], 'low')
row(None, '1123 16:49', 'eeb22609', E23, V,
    "the color audio as well need to be the same",
    "labelled the V2 video pieces but not their audio")
row(None, '1123 16:52', 'eeb22609', E23, V,
    "link the video and audio back together",
    "moving pieces to V2 left video unlinked from its audio")
row(None, '1123 16:52', 'eeb22609', E23, V,
    "this is how i color, pink first mainly guest, then purple sencond guess, blue lawyer , green host, yellow is the things need to be in video or can be highlight, orange is ending sentences, teal caller phone in",
    "labelled topics with arbitrary cycling colours instead of the user's speaker/role scheme")
row(None, '1123 16:54', 'eeb22609', E23, V,
    "and light green in insert and video, or things can be b roll , or static person, reset them",
    "agent's topic colours had to be reset; light green marks insert/B-roll material")
row(None, '1123 17:04', 'eeb22609', E23, V,
    "just simple, like host asking guest 1 thats it color one dont use a lot of color like split, i mainly relate to question",
    "(question answer) planned to split and colour at every speaker change; label per question instead", confidence='low')
row('K1', '1123 17:32', 'eeb22609', E23, M,
    "i mark red you miss one in the sq",
    "insert search missed one insert the user wanted in Backup")
row(None, '1123 17:49', 'eeb22609', E23, V,
    "remember the rule as well no jump cut only can when b roll above, the trick is if they talk to some story if that has b roll, you can put it on top and aggressive cut",
    "(question answer) pre-draft reminder: no uncovered jump cuts", ['1120 16:38', '0930 12:31'], 'low')
row('K2', '1123 18:07', 'eeb22609', E23, V,
    "In each cut, I saw you put some clip, like B-roll, clip there. That's not good. … if it's the same scene, don't keep it short like that. It feels weird.",
    "dropped a short B-roll clip on every cut instead of one long same-scene cover")
row(None, '1123 18:07', 'eeb22609', E23, V,
    "right now you just put the like whole of speech in. Yeah, I want to be. I want it to be like concise and clear.",
    "kept whole speeches instead of tightening with J/L cuts under the picture", ['1120 16:45'], 'low')
row('K3', '1123 18:29', 'eeb22609', E23, V,
    "You miss some question asking. Yeah, sometimes it needs to be asked before tell the story. … asking is the s- is okay to do.",
    "cut the host questions that set up a story")
row(None, '1123 18:29', 'eeb22609', E23, V,
    "in the insert, like there sometime would say like there is a video audio, show it. You have to show it. Sometimes there's a audio, you have to put also audio in it.",
    "left out the insert clip (video/voice recording) the speaker refers to")
row('K4', '1123 18:29', 'eeb22609', E23, V,
    "when the audio play, that's where you keep dialogue out. Don't overlap them, just show the clip.",
    "played studio dialogue over an insert's own audio")
row('K5', '1123 19:16', 'eeb22609', E23, V,
    "Some have some static frame. It's not actually static, and they're speaking and it not sync to the audio.",
    "'static' listener covers showed people speaking out of sync")
row('K6', '1123 20:18', 'eeb22609', E23, V,
    "one thing you forget on all your draft is the color label",
    "drafts left unlabelled", confidence='low')
row('K7a', '1123 20:40', 'eeb22609', E23, M,
    "the first RAID mark is like a jump cut. … I don't want that ever.",
    "uncovered jump cut in the draft", ['1120 16:38', '1123 17:49'])
row('K7b', '1123 20:40', 'eeb22609', E23, M,
    "Show the fully on. Don't show the resolve.",
    "B-roll shown mid-dissolve instead of fully on")
row('K7c', '1123 20:40', 'eeb22609', E23, M,
    "the second red is the sponsor … I just don't want the tab",
    "sponsor tab left visible; hide with a small centred zoom (no 3HD logo, no clock)")
row('K7d', '1123 20:40', 'eeb22609', E23, M,
    "It changed the scene too short, so it's so snappy.",
    "shot held too briefly before the scene changes (snappy)", ['K2'], 'low')
row('K8', '1123 21:06', 'eeb22609', E23, V,
    "can you just like duplicate the same draft then fix it?",
    "rebuilt each draft from scratch instead of copying the last one and fixing it", confidence='low')

# ---- 1124
row(None, '1124 12:44', '14c7aa8b', E23, V,
    "right now i feel like when you want to do things, you do it all over again, but for me, i do things in 1 sq",
    "keeps redoing timeline work from the start instead of deriving from the existing sequence", ['K8'], 'low')
row(None, '1124 12:44', '14c7aa8b', E23, V,
    "on the last night run, i saw the xml fc7 things come back again, i just want you to do the timeline like i edit",
    "built sequences via FCP7 XML instead of editing the timeline the way the user does", [], 'low')
E24 = '20261124'
row('K9', '1124 15:43', 'd61bf7c7', E24, V,
    "trim it, and dont forget that you have to split the edit frist to show the section",
    "drafted without first splitting Edit at the sections")
row('K10', '1124 15:50', 'd61bf7c7', E24, V,
    "you also forgot to do the insert in backup, and the edit sq, like put things to V2",
    "skipped day setup: no inserts in Backup, picks not lifted to V2", ['1120 16:09', '1120 16:23'], 'low')
row('K11', '1124 16:09', 'd61bf7c7', E24, V,
    "cover v2 with insert, and cut i can save more time , and tighening the story",
    "cuts left uncovered and story not tightened", ['K10', '1123 18:07'])
row('K12', '1124 16:37', 'd61bf7c7', E24, V,
    "first of i want this whole video to feel fun not boring ads video for movie",
    "cut read like a film ad, not fun")
row('K13', '1124 16:45', 'd61bf7c7', E24, V,
    "i know it cant be fun in all part, but keep things like v3 but add some fun in",
    "over-corrected tone; keep v3 and add some fun")
row(None, '1124 19:02', 'd61bf7c7', E24, V,
    "start with this [\"คนอื่นเขาคงสร้างเจดีย์ ผมสร้างหนัง\"] remove all in front,",
    "highlight opened before the line the user wanted first", [], 'low')
row('K15', '1125 10:33', '6af416ee', E24, V,
    "we cut the mid sentence or we cut early, it starts weird, and  i feel like you still dont know how to use timeline in premiere",
    "pieces cut mid-sentence or too early")
row('K16', '1125 11:19', '6af416ee', E24, V,
    "avoid when see or heard someone talking while J cut … it needs to be safe interm of frame",
    "J/L-cut held picture shows someone talking", ['K5'], 'low')

# ---- 1125
E25 = '20261125'
row('K17', '1125 19:29', '2ce93c3f', E25, M,
    "this kind of insert that already full screen dont zoom in, and all the zoom in need to be centered",
    "zoomed full-screen inserts; zooms not centred", ['1120 18:36', 'K7c'])
row('K18', '1125 19:31', '2ce93c3f', E25, V,
    "some insert still not center of the frame",
    "inserts still off-centre", ['K17', 'K7c'])
row(None, '1125 20:44', '2ce93c3f', E25, V,
    "i changed the timeline to 1920x1080 fit them all insert as well",
    "draft built at the 720p source size; inserts not fitted to 1920x1080", [], 'low')
row('K19', '1125 21:01', '2ce93c3f', E25, V,
    "you just copy paste the adj, the lemetri dont even black and blur the blood and wound",
    "copied the user's adjustment layer instead of masking the wound")
row('K20', '1125 21:09', '2ce93c3f', E25, V,
    "use the circle, it looks bad on rectanhle",
    "rectangle mask instead of an ellipse")
row('K21', '1125 21:31', '2ce93c3f', E25, V,
    "I feel like you forgot like the context around like the story. … Maybe you can give it some taste first, then just go to that story that you pick",
    "dropped the story context; opened cold", ['K3'], 'low')
row('K22', '1125 21:31', '2ce93c3f', E25, V,
    "don't ever cut the things that is not finished. Like I saw some cut from you, like it feels like yeah, that's bad.",
    "cut pieces before the thought finished", ['K15'])
row('K23', '1125 21:31', '2ce93c3f', E25, V,
    "I can see like jump cut. If you want to change another scene, but it in the same scene, you have to have insert or b-roll to cover it",
    "uncovered jump cuts", ['1120 16:38', '1123 17:49', 'K7a'])
row('K24', '1125 21:31', '2ce93c3f', E25, V,
    "for the J cut and L cut, I want you to always duplicate that layer on top and use it. Don't use the law one.",
    "J/L cuts made on the raw layer instead of a duplicate on top")
row('K25', '1125 21:31', '2ce93c3f', E25, V,
    "I want you to brave enough to create something … ELLIPSE mask tool",
    "did not build its own adjustment layer with a mask", ['K19', 'K20'])
row('K26', '1125 21:39', '2ce93c3f', E25, V,
    "you never use like a color to label like a hot spot, high volume argument, like what needs to be in a video, like uh yellow yellow one",
    "never labelled hot spots yellow", ['1123 16:52', 'K6'])

# ---- 1126
E26 = '20261126'
row(None, '1126 17:20', 'cece435c', E26, V,
    "can u relink the layer on editing,",
    "split/lift on Editing left V2 video unlinked from A1 audio", ['1123 16:52'])
row(None, '1126 17:24', 'cece435c', E26, V,
    "dont forget my insert, backup sq",
    "YT v1 body built with no covers from Backup", ['K10', 'K11'])
row(None, '1126 17:33', 'cece435c', E26, V,
    "make sure the backup is 1920x1080 and all broll scale up and fit the rules",
    "Backup built at 720p; B-roll not scaled per the zoom rules", ['1125 20:44', 'K17'])
row(None, '1126 18:57', 'cece435c', E26, V,
    "First off, I want you to check the length again. It's above 20 minutes. So cut something that you think is not worth in the story.",
    "handed over a body above 20 min", ['1120 16:38', 'K11'])
row(None, '1126 18:57', 'cece435c', E26, V,
    "you spam a lot of like one insert. Don't do that. Like you spam it on every cut. Don't do that because every cut is not the same.",
    "same insert reused as cover on every cut instead of one related to each cut", ['K2', '1120 16:45'])

# ---- ids: K id, else "MMDD HH:MM", with "#2" for a second non-K row at the same time
R.sort(key=lambda r: r['when'])
seen = {}
for r in R:
    if r['k']:
        r['id'] = r['k']
    else:
        n = seen.get(r['when'], 0) + 1; seen[r['when']] = n
        r['id'] = r['when'] if n == 1 else f"{r['when']}#{n}"
# ---- repeat threads: each row's repeat_of = every earlier member of every thread it is in
THREADS = {
    'uncovered cut / jump cut': ['0930 12:31', '1120 16:38', '1123 17:49', 'K7a', 'K11', 'K23', '1126 17:24'],
    'Backup inserts / V2 set-up skipped': ['1120 16:09#2', '1120 16:23', 'K10', '1126 17:24'],
    'too long / not tightened': ['1120 16:38#2', '1120 16:45#2', '1123 18:07', 'K11', '1126 18:57'],
    'same cover clip on every cut': ['1120 16:45', 'K2', '1126 18:57#2'],
    'shots too short / snappy': ['K2', 'K7d'],
    'video unlinked from audio': ['1123 16:52', '1126 17:20'],
    'label scheme not applied': ['1123 16:52#2', 'K6', 'K26'],
    'cut before the thought ends': ['K15', 'K22'],
    'set-up context cut': ['K3', 'K21'],
    'cover shows someone talking': ['K5', 'K16'],
    'insert zoom wrong / off-centre': ['1120 18:36', 'K7c', 'K17', 'K18', '1126 17:33'],
    'frame size not 1920x1080': ['1125 20:44', '1126 17:33'],
    'no own adjustment layer for the wound': ['K19', 'K25'],
    'rectangle mask, not ellipse': ['K20', 'K25'],
    'rebuilt instead of derived': ['1120 19:35#2', 'K8', '1124 12:44'],
    'breaks and sponsor not flagged': ['1120 16:09', '1123 16:24'],
}
byid = {r['id']: r for r in R}
for t, mem in THREADS.items():
    for x in mem:
        assert x in byid, (t, x)
    assert [byid[x]['when'] for x in mem] == sorted(byid[x]['when'] for x in mem), t
for r in R:
    rep = []
    for mem in THREADS.values():
        if r['id'] in mem:
            for x in mem[:mem.index(r['id'])]:
                if x not in rep: rep.append(x)
    r['repeat_of'] = sorted(rep, key=lambda x: byid[x]['when'])
# ---- k_match: K rows must equal the failure-table quote, whitespace-normalised
import re
ft = open(r'E:/Me/5.Claude/Transcriber_v2/.claude/worktrees/hks-correction-loop/projects/hks/gates/failure-table.md', encoding='utf-8').read()
kq = {m.group(1): m.group(2) for m in re.finditer(r'^\| (K\d+[a-d]?) \|[^|]*\|[^|]*\| (.*?) \|', ft, re.M)}
norm = lambda x: ' '.join(re.sub(r'\s*\(\d\d:\d\d\)$', '', x.strip()).replace('"', '').split())
for r in R:
    if r['k']:
        ok = norm(r['words']) == norm(kq[r['k']])
        r['acceptance'] = 'k_match' if ok else 'new'
        if not ok: print('K MISMATCH', r['k'], '|', kq[r['k']][:80])
print('K rows not used:', sorted(set(kq) - {r['k'] for r in R}))
# ---- verify
bad = 0
for r in R:
    texts = corpus.get((r['session'], r['when']), [])
    alltexts = [t for (s2, w), ts in corpus.items() if s2 == r['session'] for t in ts]
    for frag in r['words'].split(' … '):
        if not any(frag in t for t in texts):
            print('not at its own time', r['when'], frag[:50])
        if not any(frag in t for t in alltexts):
            print('NOT FOUND', r['when'], r['session'], frag[:60]); bad += 1
ids = {r['id'] for r in R}
for r in R:
    for x in r['repeat_of']:
        if x not in ids: print('BAD REF', r['when'], x); bad += 1
R = [{k: r[k] for k in ('id','k','when','session','episode','source','words','mistake','repeat_of','confidence','acceptance')} for r in R]
json.dump(R, open(os.path.join(HERE, 'corrections_verbal.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(len(R), 'rows;', bad, 'problems')
