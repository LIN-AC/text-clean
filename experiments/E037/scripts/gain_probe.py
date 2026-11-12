"""Trace the additional historical repair; counterfactual modern-only retrieval.
Uses a connection-local TEMP view, leaving the evidence database bytes untouched.
"""
import collections,json,math,pathlib,re,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E037/results'
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'experiments/E024/scripts'))
from rag_clean import Cleaner,sha
from align_lib import align
def dump(n,x):(O/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
path=R/'asr/BV1uUak6pEdK.gt.jsonl';pkg=R/'build/e037_package_train'
paths=[path,pathlib.Path(__file__),R/'tools/rag_clean.py',R/'experiments/E024/scripts/align_lib.py',R/'data/correction/candidates.tsv']+list(pkg.glob('*'))
before={str(p.relative_to(R)):sha(p) for p in paths if p.is_file()}
rows=[json.loads(l) for l in path.read_text('utf8').splitlines() if l.strip()]
rows=[r for r in rows if not r.get('discard')];body='\n'.join(r['text'] for r in rows)+'\n'
rag=json.loads((O/'train_RAG.BV1uUak6pEdK.gt.trace.json').read_text('utf8'))
ng=json.loads((O/'train_no_retrieval.BV1uUak6pEdK.gt.trace.json').read_text('utf8'))
ng_spans={(e['begin'],e['end'],e['target']) for e in ng['edits']}
c=Cleaner(pkg,R/'build/e035/text_clean.exe',research=True)
terms=c.store.global_terms(body);gains=[]
for edit in rag['edits']:
    b,e,target=edit['begin'],edit['end'],edit['target']
    if (b,e,target) in ng_spans:continue
    w=next(x for x in rag['windows'] if x['begin']==b and x['end']==e)
    source=body[b:e];targets=set(w['targets'])
    query='  '+body[max(0,b-180):b]+' '+body[e:e+180]
    for t in sorted(targets|{source},key=len,reverse=True):query=query.replace(t,' ')
    query+=' '+' '.join(t for t in terms if not any(t in x for x in targets|{source}))
    (counts,total),docs=c.store.retrieve(query,c.params['retrieval_limit'])
    assert docs==w['docs']
    left=re.search('[一-鿿]*$',body[:b])[0];right=re.match('[一-鿿]*',body[e:])[0]
    tail=right[:3] if len(right)>=3 else right+'$';events={}
    for name,word in [('original',source),('target',target)]:
        h=('^^^'+c.model.encode(left))[-3:];items=[]
        for ch in c.model.encode(word)+c.model.encode(tail):
            p=c.model.probability(h,ch);q=(counts.get((h,ch),0)+10*p)/(total.get(h,0)+10)
            items.append(dict(history=h,char=ch,document_support=counts.get((h,ch),0),
                              continuation_sum=total.get(h,0),p_general=p,p_mixed=q));h=(h+ch)[-3:]
        events[name]=items
    matches=[]
    for cid in docs:
        for text,url,family in c.store.db.execute('select s.text,d.url,d.source_family from segments s join documents d on d.cluster_id=s.cluster_id where s.cluster_id=? and instr(s.text,?)>0 limit 3',(cid,target)):
            pos=text.index(target);matches.append(dict(cluster=cid,url=url,family=family,excerpt=text[max(0,pos-12):pos+len(target)+12]))
    gains.append(dict(begin=b,end=e,source=source,target=target,context=body[max(0,b-20):e+20],
                      events=events,document_matches=matches,trace_score=next(x for x in w['H'] if x['word']==target)))
dump('gain_evidence.json',gains)
# Only the selected segment population changes; original query/TF-IDF/LM/parameters stay fixed.
c.store.cache.clear()
c.store.db.execute("create temp view segments as select s.* from main.segments s join main.documents d on d.cluster_id=s.cluster_id where d.domain='现代'")
start=time.perf_counter();result=c.clean(body);seconds=time.perf_counter()-start
labels={};offset=0
for r in rows:
    lab,_=align(r['text'],r['gt']);labels.update({offset+k:v for k,v in lab.items()});offset+=len(r['text'])+1
out=result['text'];counts=collections.Counter(TP=0,FP=0,wrong=0)
for i,v in labels.items():
    if out[i]!=body[i]:counts['TP' if out[i]==v else 'FP' if body[i]==v else 'wrong']+=1
summary=dict(counts=counts,distance=sum(align(line,row['gt'])[1] for line,row in zip(out.splitlines(),rows)),
             seconds=seconds,edits=result['edits'],same_output_as_no_retrieval=out==ng['text'],
             scope='historical video only; modern-only retrieved documents; global query terms unchanged')
dump('modern_only_history.trace.json',result);dump('modern_only_history.json',summary)
c.store.db.close();assert all(sha(R/p)==h for p,h in before.items())
dump('gain_probe_manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
     inputs=before,all_inputs_unchanged=True,command='python experiments/E037/scripts/gain_probe.py'))
print(json.dumps(summary,ensure_ascii=False),flush=True)
