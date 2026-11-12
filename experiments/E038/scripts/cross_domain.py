"""Historical video, modern-only retrieval; same current model and complete selection."""
import collections,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E038/results'
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'experiments/E024/scripts'))
from rag_clean import Cleaner,sha
from align_lib import align
pkg=R/'build/e038_train_v2';truth=R/'asr/BV1uUak6pEdK.gt.jsonl'
paths=list(pkg.glob('*'))+[truth,R/'tools/rag_clean.py',pathlib.Path(__file__),R/'data/correction/candidates.tsv']
before={str(p.relative_to(R)):sha(p) for p in paths if p.is_file()}
c=Cleaner(pkg,R/'build/e035/text_clean.exe',research=True)
c.store.db.execute("create temp view segments as select s.* from main.segments s join main.documents d on d.cluster_id=s.cluster_id where d.domain='现代'")
rows=[json.loads(l) for l in truth.read_text('utf8').splitlines() if l.strip()]
assert not any(r.get('pending') for r in rows);rows=[r for r in rows if not r.get('discard')]
body='\n'.join(r['text'] for r in rows)+'\n';labels={};offset=0
for row in rows:
    lab,_=align(row['text'],row['gt']);labels.update({offset+k:v for k,v in lab.items()});offset+=len(row['text'])+1
t=time.perf_counter();result=c.clean(body);seconds=time.perf_counter()-t;counts=collections.Counter(TP=0,FP=0,wrong=0)
for i,v in labels.items():
    if result['text'][i]!=body[i]:counts['TP' if result['text'][i]==v else 'FP' if body[i]==v else 'wrong']+=1
no=json.loads((O/'train_no_retrieval.BV1uUak6pEdK.gt.trace.json').read_text('utf8'))
report=dict(counts=counts,distance=sum(align(line,r['gt'])[1] for line,r in zip(result['text'].splitlines(),rows)),
            seconds=seconds,edits=result['edits'],same_as_no_retrieval=result['text']==no['text'],
            scope='historical video only; retrieved segments restricted to modern domain; query statistics unchanged')
c.store.db.close();assert all(sha(R/p)==h for p,h in before.items())
(O/'cross_domain.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
(O/'cross_domain.trace.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
(O/'cross_domain_manifest.json').write_text(json.dumps(dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 inputs=before,command='python experiments/E038/scripts/cross_domain.py',all_inputs_unchanged=True),ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False),flush=True)
