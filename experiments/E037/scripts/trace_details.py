"""Inspect saved regression evidence and independently probe newline boundaries."""
import collections,json,pathlib,re,sqlite3,sys
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E037/results'
sys.path.insert(0,str(R/'tools'))
from rag_clean import sha
counts=collections.Counter();examples=[];case=None
for f in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(s) for s in f.read_text('utf8').splitlines() if s.strip()]
    body='\n'.join(r['text'] for r in rows if not r.get('discard'))+'\n'
    trace=O/('train_RAG.'+f.stem+'.trace.json')
    if not trace.exists():continue
    r=json.loads(trace.read_text('utf8'))
    for w in r['windows']:
        b=w['begin'];prefix=body[:b]
        actual=re.search('[一-鿿]*$',prefix)[0]
        j=len(prefix)
        while j and '一'<=prefix[j-1]<='鿿':j-=1
        expected=prefix[j:];counts['windows']+=1
        if actual!=expected:
            counts['newline_context_mismatch']+=1
            if len(examples)<5:examples.append(dict(video=f.stem,begin=b,source=w['source'],actual_left=actual,expected_left=expected))
        if w['reason']=='applied' and actual!=expected:counts['applied_with_context_mismatch']+=1
        if f.stem=='BV1uUak6pEdK.gt' and w['source']=='魏清获取':case=(body,w)
assert case is not None
body,w=case;db=sqlite3.connect((R/'build/e037_package_train/evidence.sqlite').as_uri()+'?mode=ro',uri=True)
support=[]
for cid in w['docs']:
    for txt,url,fam in db.execute("select s.text,d.url,d.source_family from segments s join documents d on d.cluster_id=s.cluster_id where s.cluster_id=? and instr(s.text,'霍去病击破')>0",(cid,)):
        pos=txt.index('霍去病击破');support.append(dict(cluster=cid,url=url,source_family=fam,excerpt=txt[max(0,pos-15):pos+30]))
db.close()
result=dict(counts=counts,newline_examples=examples,extra_repair_suffix_support=support,
            consumer_sha256=sha(R/'tools/rag_clean.py'),script_sha256=sha(pathlib.Path(__file__)),
            note='Independent literal backward scan vs current consumer regex; no algorithm or parameters changed.')
(O/'trace_details.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False,indent=2))
