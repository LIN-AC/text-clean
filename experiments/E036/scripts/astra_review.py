"""Independent read-only review of E036; no rebuild or correction changes."""
import collections,csv,hashlib,json,pathlib,re,sqlite3,subprocess
R=pathlib.Path(__file__).resolve().parents[3]
O=R/'experiments/E036/results/astra_review';O.mkdir(exist_ok=True)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def table(p):
    with open(p,encoding='utf8') as f:return list(csv.DictReader((s for s in f if not s.startswith('#')),delimiter='\t'))
def ro(p):return sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)
raw=R/'build/e036_corpus/corpus.sqlite';db=ro(raw)
package=R/'build/e036_package_v2';ev=ro(package/'evidence.sqlite')
hold=json.loads((R/'build/e036_corpus/holdout.json').read_text('utf8'))
held=set(hold['modern_holdout_docs'])|set(hold['history_holdout_docs'])
docs=list(db.execute('select doc_id,domain,cluster_id,source_family,text_norm from docs order by doc_id'))
modern=collections.Counter();train=collections.Counter();dedup=collections.Counter();seen=set()
split=collections.defaultdict(set);held_clusters=set();held_mod_clusters=set()
for i,dom,cluster,fam,txt in docs:
    split[cluster].add(i in held)
    if i in held:
        held_clusters.add(cluster)
        if dom=='现代':held_mod_clusters.add(cluster)
    if dom!='现代':continue
    chars=re.findall('[一-鿿]',txt);modern.update(chars)
    if i not in held:train.update(chars)
    if cluster not in seen:dedup.update(chars);seen.add(cluster)
old=table(R/'build/e036_corpus/candidates.tsv.before_E036')
current=table(R/'data/correction/candidates.tsv')
def coverage(rows,counts):
    targets={r['canonical'] for r in rows if r['status']=='1'}
    return dict(enabled_rows=sum(r['status']=='1' for r in rows),targets=len(targets),
                min1=sum(set(t)<=counts.keys() for t in targets),
                min2=sum(all(counts[c]>=2 for c in t) for t in targets),
                missing_even_at_min1=sorted(t for t in targets if not set(t)<=counts.keys()))
result=dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            coverage_before=coverage(old,modern),coverage_current=coverage(current,modern),
            modern_char_types=len(modern),modern_dedup_char_types=len(dedup),
            modern_train_only_char_types=len(train),split_crossing_clusters=sum(len(s)>1 for s in split.values()))
present={r[0] for r in ev.execute('select cluster_id from documents')}
result['heldout_clusters_in_package']=len(held_clusters&present)
result['modern_heldout_clusters_in_package']=len(held_mod_clusters&present)
result['heldout_clusters_total']=len(held_clusters)
model=json.loads((package/'model.json').read_text('utf8'))
result['runtime_vocab_size_with_specials']=len(model['vocab'])
result['runtime_vocab_han_only']=sum('一'<=c<='鿿' for c in model['vocab'])
# Reproduce builder's deduplicated modern run count with and without holdout.
seen=set();all_runs=train_runs=0;retained_holdout_docs=0
for i,dom,c,f,txt in docs:
    if c in seen:continue
    seen.add(c)
    if dom=='现代':
        n=len(re.findall('[一-鿿]+',txt));all_runs+=n
        if i not in held:train_runs+=n
        else:retained_holdout_docs+=1
result['model_sentence_count']=model['sentences'];result['all_modern_dedup_runs']=all_runs
result['excluding_holdout_dedup_runs']=train_runs;result['retained_modern_holdout_docs']=retained_holdout_docs
result['source_groups_raw']=db.execute('select domain,count(distinct source_family) from docs group by domain').fetchall()
result['source_groups_runtime']=ev.execute('select domain,count(distinct source_family) from documents group by domain').fetchall()
result['work_family_examples']=db.execute('select work,source_family,count(*) from docs group by work,source_family').fetchall()
runtime_family=dict(ev.execute('select cluster_id,source_family from documents'))
result['runtime_source_family_mismatches']=sum(runtime_family.get(c)!=f for i,dom,c,f,txt in docs if c in present)
result['tones_current']={str(t):sorted({r['canonical'] for r in current if r['status']=='1' and re.search(str(t)+'(?:[a-z]|$)',r['pinyin'])}) for t in [0,5]}
wordrows=table(R/'data/pronunciation/pronunciation.tsv')
readings={r['entry']:r['readings'] for r in wordrows}
targets={r['canonical'] for r in current if r['status']=='1'}
result['runtime_target_multiple_variants']=sorted(t for t in targets if '|' in readings.get(t,''))
result['runtime_long_segments']=ev.execute('select count(*),max(length(text)) from segments where length(text)>1000').fetchone()
result['raw_map_identity_failures']=sum(json.loads(mp)!=list(range(len(txt))) for txt,mp in db.execute('select text_norm,normalization_map_json from docs'))
inputs=[raw,R/'build/e036_corpus/holdout.json',R/'build/e036_corpus/verify_report.json',
        R/'build/e036_corpus/candidates.tsv.before_E036',R/'data/correction/candidates.tsv',
        R/'data/pronunciation/pronunciation.tsv',R/'include/text_clean/pinyin_dict.h',
        R/'src/dictionary_bundle.cpp',R/'tools/prepare_rag_package.py',R/'tools/rag_clean.py',
        R/'docs/LEXICON_BUILD_REPORT_E036.md',pathlib.Path(__file__)]
inputs+=list(package.glob('*'))
result['inputs_sha256']={str(p.relative_to(R)):sha(p) for p in inputs if p.is_file()}
result['scope']='read-only structural audit; no TP/FP rerun, no truth modification'
result['command']='python experiments/E036/scripts/astra_review.py'
db.close();ev.close()
(O/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='inputs_sha256'},ensure_ascii=False,indent=2))
