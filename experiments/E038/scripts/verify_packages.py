"""Independent package provenance, block, boundary, holdout and formula checks."""
import collections,csv,hashlib,json,pathlib,re,sqlite3,subprocess,sys
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E038/results'
sys.path.insert(0,str(R/'tools'));from rag_clean import sha,Model
def ro(p):return sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)
held=set(json.loads((R/'build/e036_corpus/holdout.json').read_text('utf8'))['holdout_clusters'])
with open(R/'data/correction/candidates.tsv',encoding='utf8') as f:
    targets={r['canonical'] for r in csv.DictReader((s for s in f if not s.startswith('#')),delimiter='\t') if r['status']=='1'}
params=json.loads((R/'build/e037_package_train/parameters.json').read_text('utf8'))
reports={};paths=[pathlib.Path(__file__),R/'tools/rag_clean.py',R/'tools/prepare_rag_package.py',R/'build/e036_corpus/holdout.json',R/'data/correction/candidates.tsv']
for name,rawname in [('train','corpus_train.sqlite'),('full','corpus.sqlite')]:
    root=R/f'build/e038_{name}_v2';raw=R/'build/e036_corpus'/rawname
    paths+=[raw]+list(root.glob('*'))
    db=ro(raw);pd=ro(root/'evidence.sqlite');manifest=json.loads((root/'manifest.json').read_text('utf8'))
    docs={i:(cluster,family,domain,txt,kind) for i,cluster,family,domain,txt,kind in db.execute('select doc_id,cluster_id,source_family,domain,text_norm,boundary_kind from docs')}
    src_segments={i:(doc,off,txt,lc,rc) for i,doc,off,txt,lc,rc in db.execute('select seg_id,doc_id,off,text_norm,left_class,right_class from segs')}
    pdocs={c:(i,family,domain,kind) for c,i,family,domain,kind in pd.execute('select cluster_id,source_doc_id,source_family,domain,boundary_kind from documents')}
    errors=collections.Counter();counts=collections.Counter();ranges=collections.defaultdict(list)
    for cluster,(i,family,domain,kind) in pdocs.items():
        errors['source_identity']+=(cluster,family,domain,kind)!=(docs[i][0],docs[i][1],docs[i][2],docs[i][4])
    for cid,sid,off,text,left,lc,rc,bos,eos in pd.execute('select cluster_id,source_seg_id,off,text,left_context,left_class,right_class,bos,eos from segments'):
        i,family,domain,kind=pdocs[cid];full=docs[i][3];src_doc,src_off,src_txt,slc,src_rc=src_segments[sid]
        errors['source_segment']+=i!=src_doc or off<src_off or off+len(text)>src_off+len(src_txt)
        errors['offset']+=full[off:off+len(text)]!=text
        errors['left_context']+=bool(left) and full[off-len(left):off]!=left
        errors['oversize']+=len(text)>256 or len(left)>3
        errors['unpunctuated_eos']+=domain=='历史' and kind.startswith('来源无句读') and bool(eos)
        errors['bos_class']+=bool(bos) and not (lc=='句末标点' or (domain=='现代' and lc=='文档头'))
        errors['eos_class']+=bool(eos) and not (rc=='句末标点' or (domain=='现代' and rc=='文档尾'))
        errors['block_bos']+=lc=='检索块边界' and bool(bos)
        errors['block_eos']+=rc=='检索块边界' and bool(eos)
        counts['blocks']+=1;counts['core_chars']+=len(text);counts['bos']+=bos;counts['eos']+=eos
        ranges[cid,sid].append((off-src_off,off-src_off+len(text)))
    # Every retained source Han character occurs in exactly one block core.
    for cid,(i,_,_,_) in pdocs.items():
        for sid,off,txt in db.execute('select seg_id,off,text_norm from segs where doc_id=?',(i,)):
            expected=[(m.start(),m.end()) for m in re.finditer('[一-鿿]+',txt)]
            actual=sorted(ranges.get((cid,sid),[]));merged=[]
            for b,e in actual:
                if merged and b<merged[-1][1]:errors['overlap']+=1
                if merged and b==merged[-1][1]:merged[-1]=(merged[-1][0],e)
                else:merged.append((b,e))
            errors['missing_or_extra_core']+=merged!=expected
    model=Model(json.loads((root/'model.json').read_text('utf8')))
    report=dict(errors=errors,counts=counts,holdout_intersection=len(set(pdocs)&held),
        vocab_size=len(model.vocab),targets_covered=sum(set(t)<=model.vocab for t in targets),
        no_continuation_characters=model.data['no_continuation_characters'],mass_error=model.validate(64),
        formula_parameters_unchanged=json.loads((root/'parameters.json').read_text('utf8'))==params,
        hashes_match=all(sha(root/n)==h for n,h in manifest['files'].items()) and sha(raw)==manifest['source_db_sha256'])
    assert not any(errors.values()),dict(errors)
    assert report['formula_parameters_unchanged'] and report['hashes_match']
    assert report['holdout_intersection']==(0 if name=='train' else len(held))
    reports[name]=report;db.close();pd.close()
data=(R/'data/correction/candidates.tsv').read_bytes()
reports['candidate_LF_repair_only_since_E037']=hashlib.sha256(data.replace(b'\n',b'\r\n')).hexdigest()=='2313abc037a99117054ae8ddcced6492e7f137ffca4af899fdaa9b9b793b37a6'
assert reports['candidate_LF_repair_only_since_E037']
(O/'package_verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
(O/'package_manifest.json').write_text(json.dumps(dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 inputs={str(p.relative_to(R)):sha(p) for p in paths if p.is_file()},command='python experiments/E038/scripts/verify_packages.py'),ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(reports,ensure_ascii=False,indent=2))
