"""Frozen same-candidate complete-pipeline regression for the delivered packages."""
import collections,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E037/results';O.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'experiments/E024/scripts'))
from rag_clean import Cleaner,sha
from align_lib import align
def dump(name,x):(O/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
paths=list((R/'data').rglob('*.tsv'))+list((R/'asr').glob('*.gt.jsonl'))
paths += [R/'tools/rag_clean.py',R/'tools/prepare_rag_package.py',R/'experiments/E024/scripts/align_lib.py',pathlib.Path(__file__),R/'build/e035/text_clean.exe']
for p in ['train','full']:paths+=list((R/f'build/e037_package_{p}').glob('*'))
before={str(p.relative_to(R)):sha(p) for p in paths if p.is_file()};all_results={};totals={};loads={}
rows_by_video={}
for f in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(l) for l in f.read_text('utf8').splitlines() if l.strip()]
    assert not any(r.get('pending') for r in rows)
    rows_by_video[f.stem]=[r for r in rows if not r.get('discard')]
def score(body,out,rows):
    assert len(out)==len(body) and len(out.splitlines())==len(rows)
    labels={};offset=0
    for row in rows:
        lab,_=align(row['text'],row['gt']);labels.update({offset+k:v for k,v in lab.items()});offset+=len(row['text'])+1
    counts=collections.Counter(TP=0,FP=0,wrong=0)
    for i,v in labels.items():
        if out[i]!=body[i]:counts['TP' if out[i]==v else 'FP' if body[i]==v else 'wrong']+=1
    return dict(counts=counts,distance=sum(align(line,row['gt'])[1] for line,row in zip(out.splitlines(),rows)),
                remaining_original_errors=sum(body[i]!=v for i,v in labels.items())-counts['TP'])
def save_arm(arm,video,result):
    all_results.setdefault(arm,{})[video]=result;dump('regression.json',all_results)
for video,rows in rows_by_video.items():
    body='\n'.join(r['text'] for r in rows)+'\n'
    save_arm('noop',video,score(body,body,rows))
    start=time.perf_counter();out=subprocess.run([str(R/'build/e035/text_clean.exe'),'--no-index-cache'],
        input=body.encode(),capture_output=True,check=True,cwd=R).stdout.decode()
    result=score(body,out,rows);result['seconds']=time.perf_counter()-start;save_arm('V1',video,result)
for pkg in ['train','full']:
    start=time.perf_counter();c=Cleaner(R/f'build/e037_package_{pkg}',R/'build/e035/text_clean.exe',research=True)
    loads[pkg]=time.perf_counter()-start
    for video,rows in rows_by_video.items():
        body='\n'.join(r['text'] for r in rows)+'\n';previous=None
        for retrieval in [True,False]:
            arm=pkg+('_RAG' if retrieval else '_no_retrieval');c.use_retrieval=retrieval;c.store.cache.clear()
            start=time.perf_counter();r=c.clean(body);seconds=time.perf_counter()-start
            result=score(body,r['text'],rows);result.update(seconds=seconds,windows=len(r['windows']),edits=len(r['edits']))
            if previous is not None:result['same_output_as_RAG']=previous==r['text']
            previous=r['text'];save_arm(arm,video,result)
            dump(arm+'.'+video+'.trace.json',r)
            print(arm,video,json.dumps(result,ensure_ascii=False),flush=True)
    c.store.db.close();del c
for arm,values in all_results.items():
    counts=collections.Counter();distance=remaining=0
    for v in values.values():counts.update(v['counts']);distance+=v['distance'];remaining+=v['remaining_original_errors']
    totals[arm]=dict(counts=counts,distance=distance,remaining_original_errors=remaining,
                    seconds=sum(v.get('seconds',0) for v in values.values()))
assert totals['noop']['distance']==2024 and totals['V1']['counts']==dict(TP=145,FP=83,wrong=25)
assert all(sha(R/p)==h for p,h in before.items()),'Inputs changed during regression'
dump('regression_summary.json',totals)
dump('regression_manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
     inputs=before,all_inputs_unchanged=True,load_seconds=loads,parameters=json.loads((R/'build/e037_package_train/parameters.json').read_text('utf8')),
     command='python experiments/E037/scripts/regression.py',scope='seven open-book ASR videos; uncalibrated parameters; no title/description; identical candidate table'))
print('TOTAL',json.dumps(totals,ensure_ascii=False),flush=True)
