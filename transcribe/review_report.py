"""Portable passage review: local audio, alternatives, editable original cues."""
from __future__ import annotations

import json


def render_review(report: dict) -> str:
    # Transcript content is data, never HTML or script markup.
    data = json.dumps(report, ensure_ascii=False).replace('<', '\\u003c')
    return _PAGE.replace('__REPORT_DATA__', data)


_PAGE = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Subtitle passage review</title>
<style>
body{font:17px system-ui,sans-serif;background:#101827;color:#edf2f7;max-width:1050px;margin:40px auto;padding:0 24px}
h1{font-size:30px}p{line-height:1.6;color:#b7c5d9}section{background:#1b283b;padding:24px;border-radius:14px;margin:22px 0}
audio{width:100%;margin:12px 0}.alternative{white-space:pre-wrap;line-height:1.8;background:#101827;padding:14px;border-radius:8px}
textarea{box-sizing:border-box;width:100%;font:18px system-ui;line-height:1.7;background:#101827;color:white;border:1px solid #60758f;border-radius:6px;padding:9px;margin:5px 0 12px}
button{background:#bfe5ca;color:#12241b;border:0;border-radius:7px;padding:12px 18px;font-weight:700;cursor:pointer}
small,label{color:#b7c5d9}header{position:sticky;top:0;background:#101827;padding:12px 0;z-index:1}.tag{color:#ffd992}
</style><body>
<header><h1>Listen, compare, correct</h1><button id="export">Download reviewed SRT</button> <small id="count"></small></header>
<details id="export-panel"><summary>Export text — copy if your browser blocks downloads</summary><textarea id="export-text" aria-label="Exported SRT" readonly rows="8"></textarea></details>
<p>Each pair heard the same audio passage. Alternatives are suggestions, including when both engines agree.
Listen to the clip, then edit the original captions below. Download keeps their original timestamps;
new or missing speech may still require retiming in your editor. Unreviewed captions are preserved.</p>
<main id="windows"></main>
<script>
const report=__REPORT_DATA__;
const cues=report.cues.map(c=>({...c}));
const modified=new Set();
function element(tag,text,parent,cls){const el=document.createElement(tag); if(text!==null)el.textContent=text;
if(cls)el.className=cls; if(parent)parent.appendChild(el); return el;}
function stamp(ms){const h=Math.floor(ms/3600000),m=Math.floor(ms%3600000/60000),s=Math.floor(ms%60000/1000);
return [h,m,s].map(n=>String(n).padStart(2,'0')).join(':')+','+String(ms%1000).padStart(3,'0');}
report.windows.forEach((w,i)=>{const card=element('section',null,document.getElementById('windows'));
element('h2',stamp(w.start_ms)+' – '+stamp(w.end_ms),card);
element('p',w.reasons.join(' · '),card,'tag');
const audio=element('audio',null,card);audio.controls=true;audio.preload='none';audio.src='audio/'+String(i+1).padStart(3,'0')+'.wav';
Object.entries(w.alternatives).forEach(([name,text])=>{element('h3',({'faster_whisper':'Thai Whisper — passage recheck','qwen3_asr':'Qwen — passage recheck'})[name]||name,card);element('div',text||'(no speech returned)',card,'alternative');});
element('h3','Your captions — edit after listening',card);
w.cue_indices.forEach(idx=>{const c=cues[idx];element('label',String(idx+1)+' · '+stamp(c.start_ms)+' – '+stamp(c.end_ms),card);
const input=element('textarea',null,card);input.value=c.text;input.dataset.cue=idx;input.setAttribute('aria-label','Caption '+(idx+1));
input.addEventListener('input',()=>{cues[idx].text=input.value;modified.add(idx);
document.querySelectorAll('textarea[data-cue="'+idx+'"]').forEach(other=>{if(other!==input)other.value=input.value});
document.getElementById('count').textContent=modified.size+' caption'+(modified.size===1?'':'s')+' edited';});});});
document.getElementById('count').textContent=report.windows.length+' passages to review';
document.getElementById('export').onclick=()=>{
const text=cues.map((c,i)=>[i+1,stamp(c.start_ms)+' --> '+stamp(c.end_ms),c.text.trim().replace(/\\n\\s*\\n/g,'\\n'),''].join('\\n')).join('\\n');
document.getElementById('export-text').value=text;document.getElementById('export-panel').open=true;
const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='reviewed.srt';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);};
</script></body></html>'''
