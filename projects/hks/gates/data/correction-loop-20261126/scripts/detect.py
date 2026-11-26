import json,sys,re,glob,os
S=sys.argv[1]
gold=json.load(open(S+'/gold_map.json',encoding='utf-8'))
MARK=re.compile(r"\b[Uu]ser(?:'s)?\b[^\"“\n]{0,80}?:\s*\**\s*[\"“][^\"”]{6,}|\*\*User correction")
def paras(text):
    out=[];cur=[];s=1;lines=text.splitlines()
    for i,l in enumerate(lines,1):
        if not l.strip():
            if cur: out.append((s,i-1,'\n'.join(cur))); cur=[]
            continue
        if not cur: s=i
        cur.append(l)
    if cur: out.append((s,len(lines),'\n'.join(cur)))
    return out
det={}
for p in glob.glob('projects/hks/memory/*.md'):
    p=p.replace(os.sep,'/')
    det[p]=[(a,b,t) for a,b,t in paras(open(p,encoding='utf-8').read()) if MARK.search(t)]
places=[(g['id'],m) for g in gold for m in g['memory'] if not m['file'].startswith('global:')]
q=[x for x in places if x[1]['kind']=='quote']
hit=lambda m:any(a<=m['line']<=b for a,b,_ in det.get(m['file'],[]))
print('quote places',len(q),'detected',sum(hit(m) for _,m in q),'| all places',len(places),'detected',sum(hit(m) for _,m in places))
nb=sum(len(v) for v in det.values())
tp=sum(1 for p,v in det.items() for a,b,t in v if any(m['file']==p and a<=m['line']<=b for _,m in places))
print('blocks detected',nb,'containing a gold place',tp,'precision',round(tp/nb,2))
for p,v in det.items():
    for a,b,t in v:
        if not any(m['file']==p and a<=m['line']<=b for _,m in places): print('  FP',p.split('/')[-1],a,t[:110].replace('\n',' '))
