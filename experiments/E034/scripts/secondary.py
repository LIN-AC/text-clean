import collections,csv,json,math,pathlib,sys
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E034/results'
sys.path.insert(0,str(R/'experiments/E033/scripts'))
from lm_score import LM,contexts_of
from control_arms import asr_and_truth
from build_kb import norm
sites=json.loads((O/'retrieval_audit.json').read_text('utf8'))['sites']
stat=collections.Counter(); eligible=collections.defaultdict(set)
for row in csv.DictReader((O/'phonetic.tsv').open(encoding='utf8'),delimiter='\t'):
    site=int(row['site']);r=sites[site];hard=row['hard']=='1';d=int(row['distance']);stat['index_returns']+=1
    if hard:stat['hard_returns']+=1
    if hard and d<=2:stat['hard_and_distance_returns']+=1
    if hard and d>2:stat['extra_without_distance']+=1
    if row['target']==r['target']:
        eligible['index'].add(site)
        if hard:eligible['hard'].add(site)
        if hard and d<=2:eligible['distance'].add(site)
for gate,ids in eligible.items():
    for i in ids:stat[gate+'_'+sites[i]['label']]+=1
(O/'phonetic_summary.json').write_text(json.dumps(stat,ensure_ascii=False,indent=2),encoding='utf8')
# Sensitivity probe only: apply documented 0.4 at every failed backoff step.
# Neither version is normalized MKN; no production decision is made.
class Backoff(LM):
    def logp(self,g):
        penalty=0.
        for n in range(len(g),1,-1):
            s=g[-n:];num=self.c[n].get(s,0);den=self.c[n-1].get(s[:-1],0)
            if num and den:return penalty+math.log(num/den)
            penalty+=math.log(.4)
        return penalty+math.log(max(self.c[1].get(g[-1],0),.1)/self.uni_total)
rows=[]
for name in ['modern','history']:
    lm=LM(name);sb=Backoff(name);cnt=collections.Counter();order=collections.Counter()
    cache={}
    for r in sites:
        if r['stem'] not in cache:cache[r['stem']]=norm(asr_and_truth(r['stem'])[0])
        text=cache[r['stem']];pos=text.find(r['alias']);end=pos+len(r['alias'])
        left=text[:pos].split(' ')[-1][-3:];right=text[end:].split(' ')[0][:3]
        diffs=[]
        for tag,m in [('E033',lm),('alpha_only',sb)]:
            diff=m.score(left,r['target'],right)[0]-m.score(left,r['alias'],right)[0]
            diffs.append(diff);cnt[tag+'_'+r['label']+'_'+('target' if diff>1e-9 else 'keep' if diff< -1e-9 else 'tie')]+=1
        if (diffs[0]>0)!=(diffs[1]>0):cnt['rank_flips']+=1
        for word in [r['alias'],r['target']]:
            ctx=('^^^'+left)[-3:]
            for ch in word+right:
                g=ctx+ch;found=1
                for n in range(len(g),1,-1):
                    if lm.c[n].get(g[-n:],0) and lm.c[n-1].get(g[-n:-1],0):found=n;break
                order[str(found)]+=1;ctx=(ctx+ch)[-3:]
    rows.append(dict(model=name,ranking=cnt,used_order=order))
(O/'backoff_sensitivity.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(phonetic=stat,lm=rows),ensure_ascii=False),flush=True)
