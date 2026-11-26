"""One-off: K1..K27 rows of failure-table.md -> projects/hks/registry/corrections/K<n>.json."""
import re,sys,json
sys.path.insert(0,'.')
from cutdeck.hks_registry import write_correction
SESS={'1123':'eeb22609','1124':None,'1125':None}
MEM={'1123':'projects/hks/memory/yt-20261123-lessons.md','1124':'projects/hks/memory/yt-20261124-draft.md','1125':'projects/hks/memory/yt-20261125-draft.md'}
rows=re.findall(r'^\| (K\d+[a-d]?) \| (\d{4}) ([^|]*?) \| ([^|]+?) \| (.+?) \| (.+?) \| (.+?) \| ([A-F]) \|$',open('projects/hks/gates/failure-table.md',encoding='utf-8').read(),re.M)
print(len(rows))
for k,day,when,src,words,_,_,way in rows:
    m=re.match(r'(\d\d:\d\d)',when.strip())
    words=words.strip()
    quotes=re.findall(r'"([^"]+)"',words)
    s='diff' if 'diff' in src else 'red_marker' if 'red marker' in src else 'verbal'
    ep='2026'+day
    if '(on 1124' in src: ep='20261124'
    write_correction({"id":k,"date":f"2026-{day[:2]}-{day[2:]}","time":m.group(1) if m else None,"episode":ep,
        "session":None,"source":s,"words":words,"way":way,"repeat_of":[],"memory":MEM[day]})
