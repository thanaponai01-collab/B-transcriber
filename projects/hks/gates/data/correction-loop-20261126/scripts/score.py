import json,sys,re,glob
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from cutdeck.hks_registry import load_rules
from test_hks_corrections import correction_blocks
S=sys.argv[1]
gold={g['id']:g for g in json.load(open(S+'/gold_map.json',encoding='utf-8'))}
G={(c,r['id']) for c,g in gold.items() for r in g['rules']}
rules=load_rules()
def score(name,P,scope=None):
    g={p for p in G if scope is None or p[0] in scope}
    p={x for x in P if scope is None or x[0] in scope}
    tp=len(p&g); pr=tp/len(p) if p else 0; rc=tp/len(g) if g else 0
    # correction-level: says "has a rule"
    cs=scope or set(gold)
    has_g={c for c in cs if any(x[0]==c for x in g)}; has_p={c for c in cs if any(x[0]==c for x in p)}
    print(f'{name:28s} pairs P={pr:.2f} R={rc:.2f} (tp {tp}, pred {len(p)}, gold {len(g)}) | corrections with a rule: pred {len(has_p)}, gold {len(has_g)}, both {len(has_p&has_g)}, pred-only {len(has_p-has_g)}')
# model
m=json.load(open(S+'/matcher/model_map.json'))['map']
score('model (sonnet)',{(c,r) for c,rs in m.items() for r in rs})
# id tags = rule.corrections links (exist only for K ids)
T={(k,r['id']) for r in rules for k in r['corrections']}
score('ID tags (all 80)',T); score('ID tags (K rows only)',T,{c for c in gold if c.startswith('K')})
# heading parse: gold memory place -> enclosing heading -> rules sourced from that file+heading
def heading_at(path,line):
    lines=open(path,encoding='utf-8').read().splitlines()
    for i in range(min(line,len(lines))-1,-1,-1):
        if lines[i].startswith('#'): return lines[i].lstrip('#').strip()
    return None
H=set(); located=0
for c,g in gold.items():
    for m_ in g['memory']:
        if m_['file'].startswith('global:'): continue
        h=heading_at(m_['file'],m_['line'])
        for r in rules:
            if r['source']['file']==m_['file'] and r['source']['heading']==h: H.add((c,r['id']))
score('heading parse (gold places)',H)
# detection: share of gold repo memory places that correction_blocks() finds (a block containing the line's text)
places=[(c,m_) for c,g in gold.items() for m_ in g['memory'] if not m_['file'].startswith('global:')]
found=0
for c,m_ in places:
    text=open(m_['file'],encoding='utf-8').read(); line=text.splitlines()[m_['line']-1]
    if any(line.strip()[:40] in b for b in correction_blocks(text)): found+=1
blocks=sum(len(correction_blocks(open(p,encoding='utf-8').read())) for p in glob.glob('projects/hks/memory/*.md'))
print(f'detection by correction_blocks(): {found} of {len(places)} gold memory places inside a detected block; {blocks} blocks detected')
