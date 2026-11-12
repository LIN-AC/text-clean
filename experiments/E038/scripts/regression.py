"""Full selection reruns, fixed parameters and candidate pool; separate output groups."""
import argparse,collections,hashlib,json,pathlib,re,subprocess,sys,time,types
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E038/results';O.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'experiments/E024/scripts'))
from rag_clean import Cleaner,sha
from align_lib import align
ap=argparse.ArgumentParser();ap.add_argument('--group',choices=['control','new'],required=True);group=ap.parse_args().group
frozen=types.ModuleType('e038_frozen');frozen.__file__=str(R/'tools/rag_clean.py');sys.modules[frozen.__name__]=frozen
snapshot=R/'experiments/E038/frozen/rag_clean_e037.py'
exec(compile(snapshot.read_text('utf8'),str(snapshot),'exec'),frozen.__dict__)
arms=[('old_RAG','e038_legacy_train',frozen.Cleaner,True),('leftfix_RAG','e038_legacy_train',Cleaner,True)] if group=='control' else [
      ('train_RAG','e038_train_v2',Cleaner,True),('train_no_retrieval','e038_train_v2',Cleaner,False),
      ('full_RAG','e038_full_v2',Cleaner,True),('full_no_retrieval','e038_full_v2',Cleaner,False)]
paths=list((R/'data').rglob('*.tsv'))+list((R/'asr').glob('*.gt.jsonl'))+[snapshot,pathlib.Path(__file__),
       R/'tools/rag_clean.py',R/'tools/prepare_rag_package.py',R/'experiments/E024/scripts/align_lib.py',R/'build/e035/text_clean.exe']
for package in {a[1] for a in arms}:paths+=list((R/'build'/package).glob('*'))
before={str(p.relative_to(R)):sha(p) for p in paths if p.is_file()}
rows_by_video={}
for f in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(s) for s in f.read_text('utf8').splitlines() if s.strip()]
    assert not any(r.get('pending') for r in rows)
    rows_by_video[f.stem]=[r for r in rows if not r.get('discard')]
def dump(n,x):(O/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def score(body,out,rows):
    assert len(body)==len(out) and len(out.splitlines())==len(rows)
    labels={};offset=0
    for r in rows:
        lab,_=align(r['text'],r['gt']);labels.update({offset+i:v for i,v in lab.items()});offset+=len(r['text'])+1
    counts=collections.Counter(TP=0,FP=0,wrong=0)
    for i,v in labels.items():
        if out[i]!=body[i]:counts['TP' if out[i]==v else 'FP' if body[i]==v else 'wrong']+=1
    return dict(counts=counts,distance=sum(align(line,r['gt'])[1] for line,r in zip(out.splitlines(),rows)),
                remaining_original_errors=sum(body[i]!=v for i,v in labels.items())-counts['TP'])
results={};loads={}
if group=='control':
    for video,rows in rows_by_video.items():
        body='\n'.join(r['text'] for r in rows)+'\n'
        results.setdefault('noop',{})[video]=score(body,body,rows)
        t=time.perf_counter();out=subprocess.run([str(R/'build/e035/text_clean.exe'),'--no-index-cache'],
            input=body.encode(),capture_output=True,check=True,cwd=R).stdout.decode()
        result=score(body,out,rows);result['seconds']=time.perf_counter()-t;results.setdefault('V1',{})[video]=result
for arm,package,cls,retrieval in arms:
    t=time.perf_counter();c=cls(R/'build'/package,R/'build/e035/text_clean.exe',research=True,use_retrieval=retrieval)
    loads[arm]=time.perf_counter()-t
    for video,rows in rows_by_video.items():
        body='\n'.join(r['text'] for r in rows)+'\n';c.store.cache.clear()
        t=time.perf_counter();r=c.clean(body);seconds=time.perf_counter()-t
        if cls is Cleaner:
            for w in r['windows']:
                assert w['context']['left']==re.search('[一-鿿]*\Z',body[:w['begin']])[0][-3:]
                assert w['retrieval'].get('evidence_chars',0)<=8192
        result=score(body,r['text'],rows);result.update(seconds=seconds,edits=len(r['edits']),windows=len(r['windows']),
            max_evidence_chars=max((w.get('retrieval',{}).get('evidence_chars',0) for w in r['windows']),default=0))
        results.setdefault(arm,{})[video]=result
        dump(arm+'.'+video+'.trace.json',r);dump(group+'.json',results)
        print(arm,video,json.dumps(result,ensure_ascii=False),flush=True)
    c.store.db.close();del c
totals={}
for arm,by_video in results.items():
    counts=collections.Counter()
    for v in by_video.values():counts.update(v['counts'])
    totals[arm]=dict(counts=counts,distance=sum(v['distance'] for v in by_video.values()),
        remaining_original_errors=sum(v['remaining_original_errors'] for v in by_video.values()),
        seconds=sum(v.get('seconds',0) for v in by_video.values()))
if group=='control':
    assert totals['old_RAG']['counts']==dict(TP=10,FP=0,wrong=0)
    assert totals['V1']['counts']==dict(TP=145,FP=83,wrong=25)
assert all(sha(R/p)==h for p,h in before.items()),'Input changed during run'
dump(group+'_summary.json',totals)
dump(group+'_manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),inputs=before,
     command='python experiments/E038/scripts/regression.py --group '+group,all_inputs_unchanged=True,load_seconds=loads,
     scope='seven open-book videos; full candidate selection; same parameters; no title or description'))
print('TOTAL',json.dumps(totals,ensure_ascii=False),flush=True)
