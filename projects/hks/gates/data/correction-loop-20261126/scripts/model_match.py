"""Model matcher arm: sonnet maps each correction to the registry rules that state its lesson."""
import json,sys,os
sys.path.insert(0,'.')
from cutdeck.hks_rule_conflicts import _claude,_json_list
S=sys.argv[1]
rules=json.load(open(S+'/rules_nolinks.json',encoding='utf-8'))
cs=json.load(open(S+'/matrix_input.json',encoding='utf-8'))['corrections']
book='\n'.join(f"{r['id']} [{r['status']}] {r['text']}" for r in rules)
out={}; cost=0
for i in range(0,len(cs),20):
    batch=cs[i:i+20]
    items='\n'.join(f"{c['id']}: user's words: {c['words'][:400]} | mistake: {c['mistake']}" for c in batch)
    prompt=f"""A video editor's rule book is below, then a list of corrections the editor's user gave. For each correction, name the rules whose text states the lesson, so that an editor following the rule would not have made the mistake. Name none if no rule states it.

RULE BOOK:
{book}

CORRECTIONS:
{items}

Reply with only a JSON array: [{{"id": "<correction id>", "rules": ["<rule id>", ...]}}], one object per correction."""
    text,st=_claude(prompt,'sonnet'); cost+=st['cost_usd']
    for f in _json_list(text): out[f['id']]=f['rules']
    print(i,st['cost_usd'],st['seconds'],len(out),flush=True)
json.dump({'map':out,'cost_usd':cost},open(S+'/matcher/model_map.json','w',encoding='utf-8'),indent=1)
print('cost',cost)
