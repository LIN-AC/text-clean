"""Frozen open-book comparison. Initial uncalibrated parameters, not tuning."""
import collections,hashlib,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E035/results';O.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'experiments/E024/scripts'))
from rag_clean import Cleaner,sha
from align_lib import align
sources=list((R/'data').rglob('*.tsv'))+list((R/'asr').glob('*.gt.jsonl'))
before={str(p.relative_to(R)):sha(p) for p in sources}
code_paths=list((R/'tools').glob('*rag*.py'))+[R/'src/text_cleaner.cpp',R/'src/main.cpp',pathlib.Path(__file__)]
code_before={str(p.relative_to(R)):sha(p) for p in code_paths}
start=time.perf_counter();c=Cleaner(R/'build/e035_package',R/'build/e035/text_clean.exe',research=True)
load_time=time.perf_counter()-start
res={}
for f in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(l) for l in f.read_text('utf8').splitlines() if l.strip()]
    assert not any(r.get('pending') for r in rows)
    rows=[r for r in rows if not r.get('discard')]
    body='\n'.join(r['text'] for r in rows)+'\n';labels={};offset=0
    for r in rows:
        lab,_=align(r['text'],r['gt']);labels.update({offset+k:v for k,v in lab.items()});offset+=len(r['text'])+1
    t=time.perf_counter();r=c.clean(body);seconds=time.perf_counter()-t
    c.use_retrieval=False;t=time.perf_counter();ng=c.clean(body);ng_seconds=time.perf_counter()-t;c.use_retrieval=True
    # Separate video: no domain count or retrieval cache carried over.
    c.store.cache.clear()
    t=time.perf_counter()
    old=subprocess.run([str(R/'build/e025/text_clean.exe')],input=body.encode(),capture_output=True,check=True).stdout.decode()
    v1_seconds=time.perf_counter()-t
    current=subprocess.run([str(R/'build/e035/text_clean.exe')],input=body.encode(),capture_output=True,check=True).stdout.decode()
    assert old==current,'V1 compatibility changed'
    arms={}
    for name,out in [('noop',body),('V1',old),('new_research',r['text']),('ngram_only',ng['text'])]:
        assert len(out)==len(body)
        counts=collections.Counter()
        for i,v in labels.items():
            if out[i]!=body[i]:counts['TP' if out[i]==v else 'FP' if body[i]==v else 'wrong']+=1
        dist=sum(align(line,row['gt'])[1] for line,row in zip(out.splitlines(),rows))
        arms[name]=dict(counts=counts,distance=dist,remaining_original_errors=sum(body[i]!=v for i,v in labels.items())-counts['TP'])
    (O/(f.stem+'.trace.json')).write_text(json.dumps(r,ensure_ascii=False),encoding='utf8')
    res[f.stem]=dict(arms=arms,seconds=seconds,ngram_seconds=ng_seconds,v1_seconds=v1_seconds,windows=len(r['windows']),edits=len(r['edits']))
    (O/'results.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf8')
    print(f.stem,seconds,len(r['windows']),arms,flush=True)
totals={}
for name in ['noop','V1','new_research','ngram_only']:
    counts=collections.Counter();distance=remaining=0
    for x in res.values():
        v=x['arms'][name];counts.update(v['counts']);distance+=v['distance'];remaining+=v['remaining_original_errors']
    totals[name]=dict(counts=counts,distance=distance,remaining_original_errors=remaining)
assert totals['V1']['counts']==dict(TP=145,FP=83,wrong=25)
assert totals['V1']['distance']==1962
assert all(sha(R/p)==h for p,h in before.items())
assert all(sha(R/p)==h for p,h in code_before.items())
manifest=dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),inputs=before,
              sources=code_before,
              package=sha(R/'build/e035_package/manifest.json'),parameters=c.params,load_seconds=load_time,
              all_formal_data_unchanged=True,command='python experiments/E035/scripts/evaluate.py',
              total_seconds=sum(x['seconds'] for x in res.values()),scope='open-book, uncalibrated research run')
(O/'summary.json').write_text(json.dumps(totals,ensure_ascii=False,indent=2),encoding='utf8')
(O/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print('TOTAL',json.dumps(totals,ensure_ascii=False),flush=True)
