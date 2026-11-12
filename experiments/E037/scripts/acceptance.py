"""Independent read-only acceptance of E036 v2 inputs and delivered packages."""
import collections,csv,hashlib,json,math,pathlib,re,sqlite3,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E037/results';O.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(R/'tools'))
from rag_clean import Model,sha
def ro(p):return sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)
def dump(name,x):(O/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
full=R/'build/e036_corpus/corpus.sqlite';train=R/'build/e036_corpus/corpus_train.sqlite'
holdpath=R/'build/e036_corpus/holdout.json'
paths=[full,train,holdpath,R/'data/raw/cedict_ts.u8',R/'experiments/E036/scripts/build_corpus.py',
       R/'experiments/E036/scripts/make_holdout.py',R/'experiments/E036/scripts/verify_v2.py',
       R/'tools/prepare_rag_package.py',R/'tools/rag_clean.py',pathlib.Path(__file__)]
paths+=list((R/'data').rglob('*.tsv'))+list((R/'asr').glob('*.gt.jsonl'))
for name in ['train','full']:paths+=list((R/f'build/e037_package_{name}').glob('*'))
before={str(p.relative_to(R)):sha(p) for p in paths if p.is_file()}
start=time.perf_counter();db=ro(full);tdb=ro(train);held=set(json.loads(holdpath.read_text('utf8'))['holdout_clusters'])
# Independent implementation of the declared normalization, without importing build_corpus.
translation={}
for line in (R/'data/raw/cedict_ts.u8').read_text('utf8').splitlines():
    if line.startswith('#'):continue
    parts=line.split(' ',2)
    if len(parts)<3 or not parts[2].startswith('[') or len(parts[0])!=len(parts[1]):continue
    for a,b in zip(parts[0],parts[1]):
        if a!=b and 0x4e00<=ord(a)<=0x9fff:translation.setdefault(a,b)
def normalized(raw):
    return ''.join(translation.get(c,c) if 0x4e00<=ord(c)<=0x9fff else c
                   if 0x3400<=ord(c)<=0x4dbf or ord(c)>0x20000 else ' ' for c in raw)
docs={};bad=collections.Counter();examples=collections.defaultdict(list);units=collections.defaultdict(collections.Counter)
clusters=collections.defaultdict(set);punct=collections.defaultdict(collections.Counter)
for i,dom,c,f,raw,txt,mp,kind in db.execute('select doc_id,domain,cluster_id,source_family,text_raw,text_norm,normalization_map_json,boundary_kind from docs'):
    docs[i]=(dom,c,f,raw,txt)
    clusters[c].add(i);units[dom]['docs']+=1;units[dom]['han_chars']+=len(re.findall('[一-鿿]',txt))
    bad['normalization']+=normalized(raw)!=txt
    bad['mapping']+=json.loads(mp)!=list(range(len(raw))) or len(raw)!=len(txt)
    punct[f]['docs']+=1;punct[f]['no_Chinese_sentence_stop_docs']+=not any(x in raw for x in '。？！')
    punct[f]['declared_no_punctuation_docs']+=kind.startswith('来源无句读')
    if '^' in raw or '$' in raw:punct[f]['raw_contains_reserved_sentinel']+=1
for dom in units:units[dom]['clusters']=len({c for d,c,f,raw,txt in docs.values() if d==dom})
train_ids={r[0] for r in tdb.execute('select doc_id from docs')}
expected_ids={i for i,(d,c,f,raw,txt) in docs.items() if c not in held}
train_clusters={r[0] for r in tdb.execute('select distinct cluster_id from docs')}
isolation=dict(train_docs=len(train_ids),train_clusters=len(train_clusters),holdout_clusters=len(held),
               cluster_intersection=len(train_clusters&held),unexpected_docs=len(train_ids-expected_ids),
               missing_docs=len(expected_ids-train_ids),unknown_holdout_clusters=len(held-clusters.keys()))
tdb.execute('attach database ? as original',(full.resolve().as_uri()+'?mode=ro',))
isolation['changed_doc_rows']=tdb.execute('select count(*) from (select * from main.docs except select * from original.docs)').fetchone()[0]
isolation['changed_seg_rows']=tdb.execute('select count(*) from (select * from main.segs except select * from original.segs)').fetchone()[0]
isolation['training_orphan_segments']=tdb.execute('select count(*) from segs s left join docs d on s.doc_id=d.doc_id where d.doc_id is null').fetchone()[0]
# Offsets/edge characters are checked independently; boundary semantic ambiguities are reported, not silently fixed.
edge_counts=collections.Counter();edge_samples=[];class_conflicts=collections.Counter();gap_counts=collections.Counter()
for sid,i,off,txt,n,le,ri,lc,rc,ls,rs in db.execute('select seg_id,doc_id,off,text_norm,chars,left_edge,right_edge,left_class,right_class,left_is_stop,right_is_stop from segs'):
    dom,c,f,raw,fulltext=docs[i];end=off+len(txt)
    units[dom]['segments']+=1
    bad['offset']+=off<0 or fulltext[off:end]!=txt or n!=len(txt)
    bad['edge_character']+=le!=(raw[off-1] if off else '^') or ri!=(raw[end] if end<len(raw) else '$')
    edge_counts[dom+'/'+rc]+=1
    stop=set('。？！')|({'?','!'} if dom=='现代' else set())
    bad['stop_flags']+=ls!=int(le in stop) or rs!=int(ri in stop)
    if (lc=='句末标点')!=bool(ls):class_conflicts[dom+'/left']+=1
    if (rc=='句末标点')!=bool(rs):class_conflicts[dom+'/right']+=1
    if rc=='换行或空白' and ri not in ' \t\r\n\u3000':
        gap_counts[ri]+=1
        if len(edge_samples)<8:edge_samples.append(dict(seg=sid,edge=ri,context=raw[max(0,end-8):end+8]))
expected_train_segments=sum(v['segments'] for v in units.values())-db.execute('select count(*) from segs where doc_id not in ('+','.join(map(str,train_ids))+')').fetchone()[0]
isolation['missing_train_segments']=expected_train_segments-tdb.execute('select count(*) from segs').fetchone()[0]
packages={}
with open(R/'data/correction/candidates.tsv',encoding='utf8') as f:
    targets={r['canonical'] for r in csv.DictReader((s for s in f if not s.startswith('#')),delimiter='\t') if r['status']=='1'}
for name,ids in [('train',train_ids),('full',set(docs))]:
    root=R/f'build/e037_package_{name}';manifest=json.loads((root/'manifest.json').read_text('utf8'))
    package_db=ro(root/'evidence.sqlite');data=json.loads((root/'model.json').read_text('utf8'))
    representatives={}
    for i in sorted(ids):representatives.setdefault(docs[i][1],i)
    actual_clusters={r[0] for r in package_db.execute('select cluster_id from documents')}
    model=Model(data);mass=model.validate(64)
    # Rebuild counts from the frozen input corpus; hash/equality tests the claimed training inputs.
    sentences=[s for i in representatives.values() if docs[i][0]=='现代' for s in re.findall('[一-鿿]+',docs[i][4])]
    retrained=Model.train(sentences)
    held_mod=[docs[min(grp)][4] for c,grp in clusters.items() if c in held and docs[min(grp)][0]=='现代']
    unk=chars=events=0;loss=0.
    for txt in held_mod:
        for s in re.findall('[一-鿿]+',txt):
            unk+=sum(ch not in model.vocab for ch in s);chars+=len(s);h='^^^'
            for w in model.encode(s)+'$':loss-=math.log(model.probability(h,w));events+=1;h=(h+w)[-3:]
    fams=dict(package_db.execute('select cluster_id,source_family from documents'))
    packages[name]=dict(files_hash_valid=all(sha(root/p)==h for p,h in manifest['files'].items()),
        source_db_hash_valid=manifest['source_db_sha256']==sha(train if name=='train' else full),
        extra_clusters=len(actual_clusters-representatives.keys()),missing_clusters=len(representatives.keys()-actual_clusters),
        holdout_overlap=len(actual_clusters&held),model_exactly_reproduced=json.loads(json.dumps(retrained.data))==data,
        model_sentences=len(sentences),vocab_size=len(model.vocab),targets=len(targets),
        targets_all_chars_known=sum(set(t)<=model.vocab for t in targets),mass_error=mass,
        source_family_mismatch_clusters=sum(fams.get(c)!=docs[i][2] for c,i in representatives.items()),
        runtime_segment_columns=[r[1] for r in package_db.execute('pragma table_info(segments)')],
        heldout_modern_docs=len(held_mod),heldout_han_chars=chars,heldout_unknown_chars=unk,
        heldout_unknown_rate=unk/chars,heldout_NLL_per_event=loss/events,
        heldout_note='train: within-source held-out language-model diagnostic; full: contaminated reference, not independent validation')
    package_db.close();del model,retrained,data
result=dict(isolation=isolation,structural_errors=bad,units=units,punctuation_by_family=punct,
            boundary_counts=edge_counts,class_flag_conflicts=class_conflicts,
            non_whitespace_classed_as_whitespace=gap_counts,edge_examples=edge_samples,packages=packages,
            elapsed=time.perf_counter()-start,scope='structure/model input acceptance; not ASR generalization')
assert all(sha(R/p)==h for p,h in before.items()),'Inputs changed during acceptance'
dump('acceptance.json',result)
dump('acceptance_manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
     command='python experiments/E037/scripts/acceptance.py',inputs=before,all_inputs_unchanged=True))
print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
