"""Read-only audits of E033 artifacts against formula.md; no production changes."""
import collections, hashlib, importlib.util, json, math, pathlib, sqlite3, subprocess, sys
R=pathlib.Path(__file__).resolve().parents[3]; O=R/'experiments/E034/results'; O.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(R/'experiments/E033/scripts'))
sys.path.insert(0,str(R/'experiments/E024/scripts'))
from lm_score import LM
import control_arms as C
from build_kb import norm,TS
from retrieve import reliable_runs,terms
from align_lib import align
def save(n,x): (O/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
inputs=list((R/'data').rglob('*.tsv'))+list((R/'asr').glob('*.gt.jsonl'))+list((R/'build/e033_lm').rglob('*.tsv'))+[R/'build/e033_kb/kb.sqlite',R/'agents/formula.md']
before={str(p.relative_to(R)):sha(p) for p in inputs}
save('manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),inputs=before,command='python experiments/E034/scripts/audit.py',scope='artifact/math/retrieval audit; not production correction evaluation'))
report={}
for name in ['modern','history']:
    lm=LM(name); vocab=list(lm.c[1]); contexts=['^^^','的','我们','财政','汉武帝']
    contexts+=sorted(lm.c[3],key=lambda x:(-lm.c[3][x],x))[:10]
    masses={h:sum(math.exp(lm.logp(h[-3:]+w)) for w in vocab) for h in contexts}
    report[name]=dict(vocab=len(vocab),mass=masses,has_eos=any('$' in g or '</s>' in g for g in lm.c[1]),
                      has_unk='<unk>' in lm.c[1],start_denominators={h:lm.c[len(h)].get(h,0) for h in ['^','^^','^^^']})
save('lm_normalization.json',report);print('LM probability audit complete',flush=True)
# Exact mathematical identities and a counterexample to per-candidate denominators.
p=[.2,.3,.5]; counts=[2,3,0]; kappa=4
mix=[(n+kappa*q)/(sum(counts)+kappa) for n,q in zip(counts,p)]
assert abs(sum(mix)-1)<1e-12
assert all((0+kappa*q)/kappa==q for q in p)
G=.7; M=1.2; beta=.8
assert abs(beta*G+(M-G)-(M+(beta-1)*G))<1e-12
# Same history occurs in 3 docs; continuation counts may sum to 5, not 3.
wrong_mass=sum((n+kappa*q)/(3+kappa) for n,q in zip(counts,p))
save('formula_checks.json',dict(normalized_mix=sum(mix),wrong_unique_history_denominator_mass=wrong_mass,
  zero_domain_D=0,identity='beta*G+D=M+(beta-1)*G',
  inconsistent_class_rho_total=1/3+1/3+1/12+9/12,
  correct_shared_normalizer_total=(1+1+1+9)/12,
  threshold_99pct_single_candidate_log_odds=math.log(99),threshold_99pct_with_rho9=math.log(990)))
db=sqlite3.connect('file:'+str(R/'build/e033_kb/kb.sqlite').replace('\\','/')+'?mode=ro',uri=True)
schemas={t:[r[1] for r in db.execute('pragma table_info('+t+')')] for t in ['docs','segs','kb']}
dup=db.execute('select count(*),sum(n-1) from (select count(distinct doc_id) n from segs group by text_norm having n>1)').fetchone()
# Retrieve a small shared set to demonstrate document-clipped h,w denominators.
ids=[r[0] for r in db.execute('select distinct segs.doc_id from kb join segs on segs.seg_id=kb.rowid where kb match ? limit 20',('"汉武" OR "盐铁"',))]
trans=collections.Counter(); histories=collections.Counter()
for doc in ids:
    grams=set(); hs=set()
    for (txt,) in db.execute('select text_norm from segs where doc_id=?',(doc,)):
        for run in txt.split():
            s='^^^'+run+'$'
            for i in range(3,len(s)):
                h=s[i-3:i];grams.add((h,s[i]));hs.add(h)
    trans.update(grams);histories.update(hs)
den=collections.Counter()
for (h,w),n in trans.items():den[h]+=n
examples=[dict(h=h,unique_docs=histories[h],sum_continuation_docs=n) for h,n in den.most_common(8)]
save('kb_schema.json',dict(schemas=schemas,duplicate_text_groups_across_docs=dup,selected_docs=len(ids),denominator_examples=examples,
  note='Reconstructed within selected segments/doc IDs; overlapping segment edges are not valid sentence boundaries. A full-document source map is needed.'))
# Align each actual source position using existing unique-optimal-path labels.
maps={}
for f in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(l) for l in f.read_text('utf8').splitlines() if l.strip()]
    assert not any(r.get('pending') for r in rows)
    raw=''; labels={}
    for row in rows:
        if row.get('discard'):continue
        lab,_=align(row['text'],row['gt']);labels.update({len(raw)+i:v for i,v in lab.items()});raw+=row['text']
    chars=[]; mapping=[]
    for i,ch in enumerate(raw):
        v=TS.get(ch,ch) if '一'<=ch<='鿿' else ' '
        if v==' ' and (not chars or chars[-1]==' '):continue
        chars.append(v);mapping.append(i)
    if chars and chars[-1]==' ':chars.pop();mapping.pop()
    assert ''.join(chars)==norm(raw)
    maps[f.stem[:-3]]=(raw,labels,mapping)
sites=C.sites(db);details=[];stats=collections.Counter()
for i,s in enumerate(sites):
    raw,lab,mp=maps[s['stem']]; pos=s['pos']; changed=[j for j,(a,b) in enumerate(zip(s['alias'],s['target'])) if a!=b]
    truth=[lab.get(mp[pos+j]) for j in changed]
    label='unjudged' if None in truth else 'TP' if all(TS.get(v,v)==s['target'][j] for j,v in zip(changed,truth)) else 'FP' if all(TS.get(v,v)==s['alias'][j] for j,v in zip(changed,truth)) else 'wrong'
    stats['sites_'+label]+=1
    n_asr=norm(C.asr_and_truth(s['stem'])[0]); flags=C.agree_map(s['stem'])
    lo=max(0,pos-90);hi=pos+len(s['alias']); left=n_asr[lo:pos];right=n_asr[hi:hi+90]
    old=C.q_terms(db,s)
    new=terms(reliable_runs(left,flags[lo:pos])+reliable_runs(right,flags[hi:hi+90]),lambda g:C.df(db,g))
    if old!=new:stats['changed_query_terms']+=1
    row=dict(stem=s['stem'],alias=s['alias'],target=s['target'],label=label,old_terms=len(old),fixed_terms=len(new))
    for tag,tk in [('old',old),('fixed',new)]:
        segs=C.retrieve(db,tk,s['domain']);dt=C.docs_with(db,segs,s['target']);da=C.docs_with(db,segs,s['alias'])
        yes=dt>=2 and dt>=2*max(1,da)
        stats[tag+'_support_'+label]+=int(yes);row[tag]=[dt,da,yes]
    details.append(row)
    if (i+1)%50==0:print('retrieval audit',i+1,'/',len(sites),flush=True)
save('retrieval_audit.json',dict(summary=stats,sites=details))
(O/'phonetic_input.txt').write_text(''.join(r['alias']+'\n' for r in details),encoding='utf8')
assert all(sha(R/p)==h for p,h in before.items())
save('unchanged.json',dict(checked_inputs=len(before),all_unchanged=True))
print(json.dumps(stats,ensure_ascii=False),flush=True)
