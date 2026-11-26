"""Backfill the correction ledger from the Step 1 matrix (gold_map.json + matrix_input.json)."""
import json,sys,re
sys.path.insert(0,'.'); sys.path.insert(0,'tools')
from cutdeck.hks_registry import load_rules,load_corrections,write_rule,write_correction,id_key
from hks_correct import probe
S=sys.argv[1]
inp=json.load(open(S+'/matrix_input.json',encoding='utf-8'))['corrections']
gold={g['id']:g for g in json.load(open(S+'/gold_map.json',encoding='utf-8'))}
rules={r['id']:r for r in load_rules()}
old={c['id']:c for c in load_corrections()}
def key(c):
    return (c['episode'], c['when'] or '9999 99:99', 0 if c['source']!='diff' else 1)
new=[c for c in inp if not c['id'].startswith('K')]
new.sort(key=key)
idmap={c['id']:c['id'] for c in inp if c['id'].startswith('K')}
for n,c in enumerate(new,28): idmap[c['id']]=f'K{n}'
def mem(g):
    rep=[m['file'] for m in g['memory'] if not m['file'].startswith('global:')]
    return rep[0] if rep else (g['memory'][0]['file'] if g['memory'] else None)
for c in inp:
    kid=idmap[c['id']]; g=gold[c['id']]
    rep=sorted({idmap[r] for r in c['repeat_of'] if r in idmap}, key=lambda x:(id_key(x.rstrip('abcd')),x))
    if kid in old:
        e=old[kid]; e.update(session=c['session'] or e['session'], memory=mem(g) or e['memory'], repeat_of=rep)
    else:
        when=c['when']
        e={"id":kid,"date":f"2026-{when[:2]}-{when[2:4]}" if when else f"{c['episode'][:4]}-{c['episode'][4:6]}-{c['episode'][6:]}",
           "time":when[5:] if when else None,"episode":c['episode'],"session":c['session'],"source":c['source'] if c['source']!='teaching' else 'verbal',
           "words":c['words'],"way":None,"repeat_of":rep,"memory":mem(g)}
    write_correction(e)
    for r in g['rules']:
        rr=rules[r['id']]
        if kid not in rr['corrections']: rr['corrections'].append(kid)
NEWRULES=[
 ('V2','day_setup','A piece\'s audio carries its video\'s label colour.',
  'A piece\'s audio carries the same label colour as its video, on `Editing` and in every draft (user, 20261123: the agent coloured the V2 pictures and left their audio unlabelled).',
  'Do the audio pieces carry the same label colours as their video?'),
 ('K12','paper_edit','A film-promo day feels fun, not like an ad.',
  'On a film-promo episode the long form feels fun, not like an advertisement for the film (user, 20261124: the v3 cut read like an ad). Not every part can be fun: keep the story that works and add the fun moments in, whole (the user, on the v4 fun paper edit).',
  'Which fun moments are in, and does any part read like an ad for the film?'),
 ('V12','paper_edit','The piece opens on the line the user names.',
  'When the user names the line a piece opens on, it opens on that line and everything before it goes (user, 20261124, on the highlight: "start with this ... remove all in front").',
  'Did the user name an opening line, and does the piece open on it?'),
 ('D4','build','The first voice pre-laps under a full sting.',
  'After a sting the body never starts flat: the sting plays its full length and the body\'s first voice starts under it (the user\'s fixes of 20261124: the host\'s question pre-lapped 2.16 s under a 4.04 s sting, in the YT and the 1-min).',
  'Where does each sting end, and does the first voice of the body start under it?'),
 ('D29','paper_edit','A talking insert is not a body piece.',
  'An interview clip the broadcast inserts, where someone talks to camera (the DSI interview of 20261126), is not a body piece: the user dropped both places the agent used it (1:25:16, 1:27:48).',
  'Is any body piece an inserted interview clip, and why does it stay?'),
]
extra={'K12':['K13'],'D4':['D14']}
nxt=max(int(i[5:]) for i in rules if i.startswith('HKS-X'))
for cid,stage,title,text,confirm in NEWRULES:
    nxt+=1; kid=idmap[cid]; ks=[kid]+[idmap[x] for x in extra.get(cid,[])]
    words=json.load(open(f'projects/hks/registry/corrections/{kid}.json',encoding='utf-8'))['words']
    r={"id":f"HKS-X{nxt}","aliases":[],"title":title,"text":text,"source":{"file":f"projects/hks/registry/corrections/{kid}.json","heading":kid},
       "status":"active","superseded_by":None,"confirmed":False,"kind":"do_confirm","kind_source":"backfill 2026-11-26, not yet confirmed",
       "stage":stage,"corrections":ks,"gate":None,"confirm":confirm,"probe":[probe(words)],"commit":None,"added":"2026-11-26"}
    rules[r['id']]=r; print(r['id'],ks,stage)
for r in rules.values(): write_rule(r)
json.dump(idmap,open(S+'/idmap.json','w'),indent=0)
print('ledger',len(load_corrections()))
