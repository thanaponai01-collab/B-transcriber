import json,sys,os,re,io
from datetime import datetime,timedelta
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
D=os.path.expanduser('~/.claude/projects/E--Me-5-Claude-Transcriber-v2')
def lt(ts): return (datetime.fromisoformat(ts.replace('Z','+00:00'))+timedelta(hours=7)).strftime('%m%d %H:%M')
for f in sorted(os.listdir(D)):
    if not f.endswith('.jsonl') or f.startswith('d44afd2e'): continue
    raw=open(os.path.join(D,f),encoding='utf-8').read()
    if 'โหนกระแส' not in raw and 'HKS' not in raw: continue
    out=[]
    for line in raw.splitlines():
        try:o=json.loads(line)
        except:continue
        if o.get('type')!='user' or o.get('isMeta') or o.get('isCompactSummary'): continue
        c=o.get('message',{}).get('content'); ts=o.get('timestamp')
        items=[('text',c)] if isinstance(c,str) else [(x.get('type'),x) for x in c or [] if isinstance(x,dict)]
        for kind,x in items:
            if kind=='text':
                t=x if isinstance(x,str) else x.get('text','')
                if not t or t.startswith('This session is being continued') or t.startswith('[Request interrupted'): continue
                if t.startswith('<'):
                    m=re.search(r'<command-name>(.*?)</command-name>.*?<command-args>(.*?)</command-args>',t,re.S)
                    if m and m.group(2).strip(): t=f'[{m.group(1)}] {m.group(2)}'
                    else: continue
                if len(t)>6000: t=t[:6000]+f' …[+{len(t)-6000} chars]'
                out.append(f'{lt(ts)} {t!r}')
            elif kind=='tool_result':
                s=x.get('content'); s=s if isinstance(s,str) else ' '.join(y.get('text','') for y in s or [] if isinstance(y,dict))
                if 'has answered your question' in s or 'User has answered' in s:
                    out.append(f'{lt(ts)} [AskUserQuestion answer] {s[:3000]!r}')
    if out:
        print(f'=== {f[:8]} ({len(out)} msgs)'); print('\n'.join(out))
