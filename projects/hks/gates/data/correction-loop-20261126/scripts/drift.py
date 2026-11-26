import sys,re,subprocess,json
sys.path.insert(0,'.')
from cutdeck.hks_registry import load
from cutdeck.hks_rule_conflicts import split_rules
sys.stdout.reconfigure(encoding='utf-8')
rev=sys.argv[1] if len(sys.argv)>1 else 'HEAD'
reg=load()
def norm(s): return re.sub(r'[\s*`_]+',' ',s).strip().lower()
def toks(s): return set(re.findall(r'[a-z\u0e00-\u0e7f]{3,}',s.lower()))
for doc in ['projects/hks/rules.md','projects/hks/principles.md']:
    md=subprocess.run(['git','show',f'{rev}:{doc}'],capture_output=True,encoding='utf-8').stdout
    units=split_rules(md,doc)
    mine=[r for r in reg['rules'] if r['source']['file']==doc]
    probes=[(r,[norm(p) for p in r['probe']]) for r in reg['rules']]
    covered=0; orphan=[]
    for u in units:
        t=norm(u['text'])
        hit=[r['id'] for r,ps in probes if any(p in t for p in ps)]
        if not hit:
            tt=toks(u['text']); best=max((len(tt&toks(r['text']))/max(1,len(tt)),r['id']) for r in reg['rules'])
            if best[0]>=0.6: hit=[best[1]]
        if hit: covered+=1
        else: orphan.append(u)
    stale=[r['id'] for r in mine if r['status']=='active' and not any(norm(p) in norm(md) for p in r['probe'])]
    textdiff=[r['id'] for r in mine if r['status']=='active' and norm(r['text'])[:80] not in norm(md)]
    print(f'{doc}@{rev}: units {len(units)}, matched to a registry entry {covered}, no entry {len(orphan)}; registry entries from it {len(mine)}, active whose probe is gone {len(stale)}, active whose text start is not in the doc {len(textdiff)}')
    for u in orphan[:40]: print('   ORPHAN',u['id'],u['text'][:110])
