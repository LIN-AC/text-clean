"""Parity, frozen V1 output, input hashes, and old/new retrieval timing."""
import collections
import json
import pathlib
import subprocess
import sys
import time

ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'experiments/E044/scripts'))
from rag_clean import Model,EvidenceStore,sha
from native_retrieval import NativeRetriever,domain_counts
from run_arms import load_rows,score


def main():
    out=ROOT/'experiments/E053/results';out.mkdir(exist_ok=True,parents=True)
    native=NativeRetriever(ROOT/'build/astra_v2/tc_retrieve.exe',ROOT/'build/e044_full/evidence.sqlite')
    # Tiny alphabet suffices for search parity: raw ids, full payload and all
    # boundary fields are independently compared, not just mapped event counts.
    model=Model.train(['微信支付','微信支付','微星电脑','微星电脑','孤'])
    old=EvidenceStore(ROOT/'build/e044_full/evidence.sqlite',model)
    data=load_rows();result=dict(v1={},retrieval=[])
    try:
        for video,rows in data.items():
            text='\n'.join(r['text'] for r in rows)+'\n'
            outputs=[];times=[]
            for exe in ['build/e035/text_clean.exe','build/astra_v2/text_clean.exe']:
                t=time.perf_counter()
                p=subprocess.run([str(ROOT/exe),'--no-index-cache'],input=text.encode(),capture_output=True,check=True,cwd=ROOT)
                outputs.append(p.stdout.decode());times.append(time.perf_counter()-t)
            assert outputs[0]==outputs[1],video
            result['v1'][video]=dict(score=score(text,outputs[1],rows),seconds=times,identical=True)
            # Deterministic four cue queries per video, never looking at corrected text.
            choices=rows[::max(1,len(rows)//4)][:4]
            for row in choices:
                query=row['text'];old.cache.clear()
                t=time.perf_counter();domain,docs=old.retrieve(query,50);py_s=time.perf_counter()-t
                t=time.perf_counter();got=native.retrieve(query,limit=50,legacy=True);cpp_s=time.perf_counter()-t
                assert domain_counts(model,got)==(domain or ({},{}))
                assert docs==sorted({s['cluster_id'] for s in got['segments']})
                assert old.last_retrieval['evidence_chars']==got['evidence_chars']
                assert old.last_retrieval['budget_cut']==got['budget_cut']
                for a,b in zip(old.last_retrieval['segments'],got['segments'],strict=True):
                    for key in ('id','cluster_id','off','source_family','left_class','right_class','bos','eos'):
                        assert a[key]==b[key],(key,a,b)
                    assert str(a['source_doc_id'])==b['source_doc_id']
                    raw=old.db.execute('select text,left_context from segments where id=?',(b['id'],)).fetchone()
                    assert b['text']==raw[0][:a['chars']] and b['left_context']==raw[1]
                result['retrieval'].append(dict(video=video,query=query,python_seconds=py_s,cpp_seconds=cpp_s,
                                                segments=len(got['segments']),identical=True))
            print(video,'V1/queries identical',flush=True)
    finally:
        old.db.close();native.close()
    c=collections.Counter()
    for v in result['v1'].values():c.update(v['score']['counts'])
    result['counts']=dict(c)
    result['distance']=sum(v['score']['distance'] for v in result['v1'].values())
    result['python_seconds']=sum(v['python_seconds'] for v in result['retrieval'])
    result['cpp_seconds']=sum(v['cpp_seconds'] for v in result['retrieval'])
    result['scope']='28 identical queries, warm/read-order affected; not whole-pipeline throughput'
    result['hashes']={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'build/e044_full/evidence.sqlite',
        ROOT/'build/e035/text_clean.exe',ROOT/'build/astra_v2/text_clean.exe',ROOT/'build/astra_v2/tc_retrieve.exe']}
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
