"""Check output equality beyond aggregate counts; reuse frozen RAG traces."""
import json,pathlib,sys,time
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E035/results'
sys.path.insert(0,str(R/'tools'))
from rag_clean import Cleaner,sha
c=Cleaner(R/'build/e035_package',R/'build/e035/text_clean.exe',research=True,use_retrieval=False)
results={}
for f in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(s) for s in f.read_text('utf8').splitlines() if s.strip()]
    body='\n'.join(r['text'] for r in rows if not r.get('discard'))+'\n'
    start=time.perf_counter();r=c.clean(body)
    trace=O/(f.stem+'.trace.json');prior=json.loads(trace.read_text('utf8'))
    results[f.stem]=dict(equal_text=r['text']==prior['text'],edits=r['edits'],
                        seconds=time.perf_counter()-start,truth_sha256=sha(f),trace_sha256=sha(trace))
assert all(v['equal_text'] for v in results.values())
(O/'ablation_equality.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print('All seven no-retrieval outputs exactly equal frozen RAG outputs.')
