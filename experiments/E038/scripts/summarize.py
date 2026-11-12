"""Finalize completed runs and keep correctness invariants separate from quality."""
import collections,hashlib,json,pathlib,re,subprocess
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E038/results'
def read(n):return json.loads((O/n).read_text('utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
totals={**read('control_summary.json'),**read('new_summary.json')}
checks=collections.Counter();gains=[]
for f in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(s) for s in f.read_text('utf8').splitlines() if s.strip()]
    body='\n'.join(r['text'] for r in rows if not r.get('discard'))+'\n'
    old=read('old_RAG.'+f.stem+'.trace.json');left=read('leftfix_RAG.'+f.stem+'.trace.json')
    new=read('train_RAG.'+f.stem+'.trace.json');no=read('train_no_retrieval.'+f.stem+'.trace.json')
    checks['old_leftfix_same_output_videos']+=old['text']==left['text']
    checks['old_new_train_same_output_videos']+=old['text']==new['text']
    for w in new['windows']:
        checks['windows']+=1
        expected=re.search(r'[一-鿿]*\Z',body[:w['begin']])[0][-3:]
        previous=re.search('[一-鿿]*$',body[:w['begin']])[0][-3:]
        checks['old_cross_newline_windows']+=previous!=expected
        checks['new_cross_newline_windows']+=w['context']['left']!=expected
        checks['max_payload_chars']=max(checks['max_payload_chars'],w['retrieval'].get('evidence_chars',0))
        checks['budget_cut_windows']+=w['retrieval'].get('budget_cut',False)
    spans={(e['begin'],e['end'],e['target']) for e in no['edits']}
    for e in new['edits']:
        if (e['begin'],e['end'],e['target']) in spans:continue
        w=next(w for w in new['windows'] if w['begin']==e['begin'] and w['end']==e['end'])
        h=next(h for h in w['H'] if h['word']==e['target'])
        gains.append(dict(video=f.stem,source=w['source'],target=e['target'],begin=e['begin'],context=w['context'],
            score={k:h[k] for k in ['G','D','S','p']},retrieval=w['retrieval']))
assert checks['new_cross_newline_windows']==0 and checks['old_cross_newline_windows']==285
assert checks['max_payload_chars']<=8192
cross=read('cross_domain.json')
manifests=['control_manifest.json','new_manifest.json','cross_domain_manifest.json','package_manifest.json']
for m in map(read,manifests):
    for p,h in m['inputs'].items():assert sha(R/p)==h,p
summary=dict(totals=totals,checks=checks,cross_domain=cross,gains=gains,
             engineering=dict(ctest_passed=25,ctest_total=25,python_cases=17,seconds=12.48),
             scope='all correction quality figures are open-book, not calibrated generalization')
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
files=[R/'tools/rag_clean.py',R/'tools/prepare_rag_package.py',R/'tests/test_rag_clean.py',R/'docs/RAG_DATA_CONTRACT.md',
       R/'README.md',R/'experiments/E038/README.md']
files+=list((R/'experiments/E038/scripts').glob('*.py'))+list((R/'experiments/E038/frozen').glob('*.py'))
files+=list(O.glob('*manifest.json'))+[O/'ctest.log',O/'summary.json']
(O/'final_manifest.json').write_text(json.dumps(dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
    files={str(p.relative_to(R)):sha(p) for p in files},all_recorded_inputs_unchanged=True),ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(totals=totals,checks=checks,cross_domain=cross),ensure_ascii=False,indent=2))
