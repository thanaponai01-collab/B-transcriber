"""Forensic timeline of a Claude Code session, for HKS rule-break analysis (projects/hks/gates/failure-table.md).

One line per event, local time (+07:00): USER words, READ / SHELLREAD / EDIT of the rule files, CHECK runs
with their RESULT, COMPACT markers and AGENT text. Usage:

    OUT=<dir> python tools/hks_forensics.py <session id prefix> [...]
"""
import json,sys,re,io,os
from datetime import datetime,timedelta
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
D=os.path.expanduser('~/.claude/projects/E--Me-5-Claude-Transcriber-v2')
RULE=re.compile(r'(rules\.md|principles\.md|PRINCIPLES\.md|before-you-cut\.md|hks/memory/[\w-]+\.md|hks/README\.md|build-plan\.md|shorts-rules)')
CHECK=re.compile(r'hks_cut_check|hks_audit|hks_score|cut_check')
def local(ts):
    return (datetime.fromisoformat(ts.replace('Z','+00:00'))+timedelta(hours=7)).strftime('%m%d %H:%M:%S')
def run(sid,out):
    f=[x for x in os.listdir(D) if x.startswith(sid) and x.endswith('.jsonl')][0]
    pending={}
    w=open(out,'w',encoding='utf-8')
    for line in open(os.path.join(D,f),encoding='utf-8'):
        try:o=json.loads(line)
        except:continue
        ts=o.get('timestamp');
        if not ts: continue
        t=local(ts); m=o.get('message',{}); c=m.get('content')
        if o.get('isCompactSummary') or (isinstance(c,str) and c.startswith('This session is being continued')):
            w.write(f'{t} COMPACT\n'); continue
        if o.get('type')=='user':
            if isinstance(c,str):
                if c.startswith('<command') or c.startswith('<local'): 
                    a=re.search(r'<command-name>(.*?)</command-name>',c); w.write(f'{t} CMD {a.group(1) if a else ""}\n'); continue
                w.write(f'{t} USER {c[:3000]!r}\n'); continue
            for x in c or []:
                if x.get('type')=='text':
                    tx=x['text']
                    if tx.startswith('<'): continue
                    w.write(f'{t} USER {tx[:3000]!r}\n')
                elif x.get('type')=='tool_result' and x.get('tool_use_id') in pending:
                    kind=pending.pop(x['tool_use_id'])
                    s=x.get('content'); s=s if isinstance(s,str) else ' '.join(y.get('text','') for y in s or [] if isinstance(y,dict))
                    w.write(f'{t} RESULT[{kind}] {s[:1500]!r}\n')
        elif o.get('type')=='assistant':
            for x in c or []:
                if x.get('type')=='text' and len(x['text'])>40:
                    w.write(f'{t} AGENT {x["text"][:2500]!r}\n')
                elif x.get('type')=='tool_use':
                    inp=x.get('input',{}); s=json.dumps(inp,ensure_ascii=False)
                    name=x['name']
                    if name in('Read','Edit','Write') and RULE.search(inp.get('file_path','')):
                        w.write(f'{t} {name.upper()} {inp.get("file_path")} {inp.get("offset","")}:{inp.get("limit","")}\n')
                        if name=='Edit': w.write(f'{t}   +{inp.get("new_string","")[:400]!r}\n')
                    elif name in('Bash','PowerShell') and RULE.search(inp.get('command','')) and re.search(r'\b(cat|sed|head|Get-Content|grep|rg|type)\b',inp.get('command','')):
                        w.write(f'{t} SHELLREAD {inp["command"][:300]!r}\n')
                    if name in('Bash','PowerShell') and CHECK.search(inp.get('command','')):
                        w.write(f'{t} CHECK {inp["command"][:400]!r}\n'); pending[x['id']]='check'
                    if name in('Grep',) and RULE.search(s): w.write(f'{t} GREP {s[:200]}\n')
                    if name=='Skill': w.write(f'{t} SKILL {s[:200]}\n')
    w.close()
for sid in sys.argv[1:]:
    run(sid,f'{os.environ["OUT"]}/{sid}.log')
