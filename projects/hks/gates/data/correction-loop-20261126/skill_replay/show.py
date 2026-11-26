import json,sys
sys.stdout.reconfigure(encoding='utf-8')
P={'1125':r'E:/Me/5.Claude/Transcriber_v2/test_projects/hks_judge/20261125/v1/20261125/cut.lines.json',
   '1126':r'E:/Me/5.Claude/Transcriber_v2/test_projects/hks_judge/20261126/questions.lines.json'}
day=sys.argv[1]
d=json.load(open(P[day],encoding='utf-8')); L=list(d.values())[0]['lines']
for a,b in zip(sys.argv[2::2],sys.argv[3::2]):
    a,b=float(a),float(b); print(f'--- {a}-{b}')
    for i,s,e,t in L:
        if e>a and s<b: print(i,f'{s:.1f}-{e:.1f}',t)
