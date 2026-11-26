import json,sys,re,glob,os
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
S=sys.argv[1]
from cutdeck.hks_registry import load_rules
inp=json.load(open(S+'/matrix_input.json',encoding='utf-8'))['corrections']
gold={g['id']:g for g in json.load(open(S+'/gold_map.json',encoding='utf-8'))}
rules={r['id']:r for r in load_rules()}
kept={k for k,v in json.load(open('projects/hks/gates/registry.json',encoding='utf-8'))['gates'].items() if v['status']=='kept'}
skills=''.join(open(p,encoding='utf-8').read() for p in glob.glob('.claude/skills/hks-*/SKILL.md'))
ids=[c['id'] for c in inp]
later={i:[] for i in ids}
for c in inp:
    for r in c['repeat_of']:
        if r in later: later[r].append(c['id'])
def active(rid):
    r=rules[rid]
    while r['status']=='superseded': r=rules[r['superseded_by']]
    return r if r['status']=='active' else None
rows=[]
for c in inp:
    g=gold[c['id']]
    rs=[x['id'] for x in g['rules']]; full=[x['id'] for x in g['rules'] if x['fit']=='full']
    act=[a for a in (active(x) for x in rs) if a]
    inskill=[a['id'] for a in act if f"**{a['id']}**" in skills]
    gated=[a['id'] for a in act if a['gate'] in kept]
    rows.append(dict(id=c['id'],ep=c['episode'],src=c['source'],mem=bool(g['memory']),rule=bool(rs),full=bool(full),skill=bool(inskill),gate=bool(gated),
        repeat_strict=any(not r.startswith('T:') for r in c['repeat_of']),repeat_loose=bool(c['repeat_of']),came_back=later[c['id']],
        rule_before=any(rules[x]['added']<('2026-'+c['episode'][4:6]+'-'+c['episode'][6:]) for x in rs if rules[x]['added']),mistake=c['mistake'],rules=rs,gates=gated))
json.dump(rows,open(S+'/matrix.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
n=len(rows)
f=lambda k:sum(1 for r in rows if r[k])
print('n',n,'memory',f('mem'),'rule',f('rule'),'full',f('full'),'skill',f('skill'),'gate',f('gate'))
print('repeat strict',f('repeat_strict'),'loose',f('repeat_loose'),'came back',sum(1 for r in rows if r['came_back']))
for ep in sorted({r['ep'] for r in rows}):
    rr=[r for r in rows if r['ep']==ep]
    print(ep,len(rr),'rep strict',sum(r['repeat_strict'] for r in rr),'loose',sum(r['repeat_loose'] for r in rr),'mem',sum(r['mem'] for r in rr),'rule',sum(r['rule'] for r in rr),'gate',sum(r['gate'] for r in rr))
# among those that came back: what had they reached?
cb=[r for r in rows if r['came_back']]
print('came back:',len(cb),'with mem',sum(r['mem'] for r in cb),'rule',sum(r['rule'] for r in cb),'gate',sum(r['gate'] for r in cb))
# repeats: was a rule existing at time?
rp=[r for r in rows if r['repeat_strict']]
print('repeats with rule existing before episode',sum(r['rule_before'] for r in rp),'of',len(rp))
