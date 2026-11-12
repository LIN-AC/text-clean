"""Build a research package from E033 raw evidence, never from ASR truth.
This adapter is not the Qwen corpus delivery: see docs/RAG_DATA_CONTRACT.md.
"""
import argparse, collections, csv, hashlib, json, pathlib, re, sqlite3
from rag_clean import Model,sha,han_runs,BLOCK_CHARS,EVIDENCE_CHARS

PROJECT=pathlib.Path(__file__).resolve().parents[1]

def table(path):
    with open(path,encoding='utf8') as f:return list(csv.DictReader((l for l in f if not l.startswith('#')),delimiter='\t'))

def readings(s,length):
    out=[]
    for form in s.split('|'):
        parts=re.findall('[a-zv:]+[0-5]',form)
        if len(parts)==length and ''.join(parts)==form:out.append(parts)
    return out

def prepare_legacy(old_db,out,data,frontend):
    out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True);data=pathlib.Path(data)
    if (out/'evidence.sqlite').exists():raise ValueError('use a fresh output directory; never overwrite a corpus')
    source=sqlite3.connect(pathlib.Path(old_db).resolve().as_uri()+'?mode=ro',uri=True)
    dest=sqlite3.connect(out/'evidence.sqlite')
    dest.executescript('''create table meta(key text primary key,value text);
    insert into meta values('format','tc-rag-1');
    create table documents(cluster_id text primary key,source_family text,domain text,url text,license text,source_sha text);
    create table segments(id integer primary key,cluster_id text references documents,ordinal integer,text text);
    create table term_docs(term text primary key,docs integer not null);
    create virtual table search using fts5(tokens);''')
    modern=[];seen=set();docs=segments=duplicates=0;term_docs=collections.Counter()
    grouped=collections.defaultdict(list)
    for doc,off,text in source.execute('select doc_id,off,text_norm from segs order by doc_id,off'):
        grouped[doc].append((off,text))
    columns={r[1] for r in source.execute('pragma table_info(docs)')}
    full_docs={}
    if {'cluster_id','text_norm'}<=columns:
        full_docs={doc:(cluster,txt) for doc,cluster,txt in source.execute('select doc_id,cluster_id,text_norm from docs')}
    for doc,domain,work,url,license_,digest in source.execute('select doc_id,domain,work,url,license,src_sha from docs order by doc_id'):
        chunks=grouped.pop(doc,[])
        if doc in full_docs:
            cluster,full=full_docs[doc]
            if not cluster or not full:raise ValueError('empty corpus document')
        else:
            full=''
            for offset,text in chunks:
                if offset>len(full):raise ValueError('missing original span: '+str(doc))
                overlap=min(len(full)-offset,len(text))
                if full[offset:offset+overlap]!=text[:overlap]:raise ValueError('overlap mismatch')
                full+=text[overlap:]
            cluster=hashlib.sha256(full.encode()).hexdigest()
        if cluster in seen:duplicates+=1;continue
        seen.add(cluster);docs+=1
        term_docs.update({s[i:i+2] for s in han_runs(full) for i in range(len(s)-1)})
        dest.execute('insert into documents values(?,?,?,?,?,?)',(cluster,work,domain,url,license_,digest))
        # Whole sentence/runs, never fixed-length chunk boundaries or overlapping copies.
        for ordinal,run in enumerate(han_runs(full)):
            if domain=='现代':modern.append(run)
            segments+=1
            dest.execute('insert into segments values(?,?,?,?)',(segments,cluster,ordinal,run))
            tokens=' '.join(run[i:i+2] for i in range(len(run)-1))
            dest.execute('insert into search(rowid,tokens) values(?,?)',(segments,tokens))
    dest.executemany('insert into term_docs values(?,?)',term_docs.items())
    dest.commit();dest.close();source.close()
    print('evidence built',docs,segments,'training model',len(modern),flush=True)
    model=Model.train(modern);mass=model.validate()
    (out/'model.json').write_text(json.dumps(model.data,ensure_ascii=False),encoding='utf8')
    chars={r['char']:r['readings'].split('|') for r in table(data/'pronunciation/pronunciation_char.tsv')}
    hot={r['word'] for r in table(data/'ac/ac_lock.tsv')}
    entries={}
    for r in table(data/'pronunciation/pronunciation.tsv'):
        word=r['entry'];ps=readings(r['readings'],len(word))
        if 2<=len(word)<=6 and re.fullmatch('[\u4e00-\u9fff]+',word) and ps:
            entries[word]=dict(word=word,readings=ps,hot=word in hot)
    for r in table(data/'correction/candidates.tsv'):
        if r['status']!='1':continue
        word=r['canonical'];ps=readings(r['pinyin'],len(word))
        if word not in entries and ps:entries[word]=dict(word=word,readings=ps,hot=word in hot)
    (out/'competitors.json').write_text(json.dumps(dict(characters=chars,entries=list(entries.values())),ensure_ascii=False),encoding='utf8')
    params=dict(calibrated=False,classes={'same':[0.,1.],'tone':[0.,1.],'near':[0.,1.]},
                alpha=.01,kappa=10.,rho=1.,top_h=30,retrieval_limit=50,
                note='Engineering initial values, not fitted or validated risk parameters.')
    (out/'parameters.json').write_text(json.dumps(params,indent=2),encoding='utf8')
    paths=['model.json','evidence.sqlite','competitors.json','parameters.json']
    manifest=dict(format='tc-evidence-package-1',files={n:sha(out/n) for n in paths},
                  frontend_sha256=sha(frontend),source_db_sha256=sha(old_db),docs=docs,segments=segments,
                  duplicate_docs_removed=duplicates,competitors=len(entries),mass_error=mass,
                  training='modern domain only; all corpus sentences retained; no truth read',
                  source_limitations=['exact-document dedup only; near-copy clusters not yet supplied',
                  'E033 normalization treats non-Han as boundaries; original punctuation map absent'],
                  source_files={str(p):sha(p) for p in [data/'pronunciation/pronunciation.tsv',data/'pronunciation/pronunciation_char.tsv',data/'correction/candidates.tsv',data/'ac/ac_lock.tsv']})
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['files','source_files']},ensure_ascii=False),flush=True)

def corpus_fragments(source,doc):
    """Validated Han fragments with absolute offsets and explicit edge provenance."""
    full=doc['text_norm'];raw=doc['text_raw'];mapping=json.loads(doc['normalization_map_json'])
    if len(raw)!=len(full) or mapping!=list(range(len(raw))):
        raise ValueError('expected length-preserving corpus mapping')
    for s in source.execute('select * from segs where doc_id=? order by ord',(doc['doc_id'],)):
        off=s['off'];txt=s['text_norm'];end=off+len(txt)
        if off<0 or s['chars']!=len(txt) or full[off:end]!=txt:raise ValueError('corpus offset mismatch')
        for side,pos in [('left',off-1),('right',end)]:
            edge=raw[pos] if 0<=pos<len(raw) else '^' if side=='left' else '$'
            if edge!=s[side+'_edge']:raise ValueError('corpus raw edge mismatch')
            if bool(s[side+'_is_stop'])!=(s[side+'_class']=='句末标点'):raise ValueError('conflicting boundary flags')
        for m in re.finditer('[\u4e00-\u9fff]+',txt):
            lc=s['left_class'] if m.start()==0 else '未支持字符'
            rc=s['right_class'] if m.end()==len(txt) else '未支持字符'
            begin=off+m.start();finish=off+m.end()
            # Literal source ^/$ are symbols, not sentinel document edges.
            if lc=='文档头' and begin!=0:lc='其他符号或标记残留'
            if rc=='文档尾' and finish!=len(full):rc='其他符号或标记残留'
            bos=lc=='句末标点' or (lc=='文档头' and doc['domain']=='现代')
            eos=rc=='句末标点' or (rc=='文档尾' and doc['domain']=='现代')
            yield dict(text=m.group(),off=begin,source_seg_id=s['seg_id'],left_class=lc,right_class=rc,bos=bos,eos=eos)

def blocks(fragment):
    """Nonoverlapping cores; up to three preceding characters preserve transitions."""
    txt=fragment['text']
    for start in range(0,len(txt),BLOCK_CHARS):
        end=min(start+BLOCK_CHARS,len(txt));first=start==0;last=end==len(txt)
        yield dict(text=txt[start:end],off=fragment['off']+start,source_seg_id=fragment['source_seg_id'],
                   left_context=txt[max(0,start-3):start],bos=bool(first and fragment['bos']),
                   eos=bool(last and fragment['eos']),left_class=fragment['left_class'] if first else '检索块边界',
                   right_class=fragment['right_class'] if last else '检索块边界')

def prepare_v2(old_db,out,data,frontend):
    out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True);data=pathlib.Path(data)
    if any(out.iterdir()):raise ValueError('use a fresh empty output directory')
    source=sqlite3.connect(pathlib.Path(old_db).resolve().as_uri()+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
    dest=sqlite3.connect(out/'evidence.sqlite')
    dest.executescript('''create table meta(key text primary key,value text);
    insert into meta values('format','tc-rag-2');
    create table documents(cluster_id text primary key,source_doc_id integer,source_family text,domain text,url text,license text,source_sha text,boundary_kind text);
    create table segments(id integer primary key,cluster_id text references documents,ordinal integer,source_seg_id integer,off integer,text text,left_context text,left_class text,right_class text,bos integer,eos integer);
    create index segment_cluster on segments(cluster_id,ordinal);
    create table term_docs(term text primary key,docs integer not null);
    create virtual table search using fts5(tokens);''')
    modern=[];seen=set();n_docs=n_blocks=duplicates=0;term_docs=collections.Counter();edge_counts=collections.Counter()
    for doc in source.execute('select * from docs order by doc_id'):
        cluster=doc['cluster_id']
        if not cluster or not doc['source_family']:raise ValueError('missing corpus identity')
        if cluster in seen:duplicates+=1;continue
        seen.add(cluster);n_docs+=1
        dest.execute('insert into documents values(?,?,?,?,?,?,?,?)',(cluster,doc['doc_id'],doc['source_family'],
            doc['domain'],doc['url'],doc['license'],doc['src_sha'],doc['boundary_kind']))
        terms=set();ordinal=0
        for fragment in corpus_fragments(source,doc):
            txt=fragment['text'];terms.update(txt[i:i+2] for i in range(len(txt)-1))
            if doc['domain']=='现代':modern.append((txt,fragment['bos'],fragment['eos']))
            for block in blocks(fragment):
                n_blocks+=1;edge_counts['bos']+=block['bos'];edge_counts['eos']+=block['eos']
                if doc['domain']=='历史' and '来源无句读' in doc['boundary_kind']:
                    edge_counts['unpunctuated_history_eos']+=block['eos']
                dest.execute('insert into segments values(?,?,?,?,?,?,?,?,?,?,?)',(n_blocks,cluster,ordinal,
                    block['source_seg_id'],block['off'],block['text'],block['left_context'],block['left_class'],
                    block['right_class'],int(block['bos']),int(block['eos'])))
                # Include the crossing bigram for retrieval without counting it twice in training.
                search_text=block['left_context'][-1:]+block['text']
                tokens=' '.join(search_text[i:i+2] for i in range(len(search_text)-1))
                dest.execute('insert into search(rowid,tokens) values(?,?)',(n_blocks,tokens));ordinal+=1
        term_docs.update(terms)
    if edge_counts['unpunctuated_history_eos']:raise ValueError('fabricated historical EOS')
    dest.executemany('insert into term_docs values(?,?)',term_docs.items());dest.commit();dest.close();source.close()
    print('evidence v2',n_docs,n_blocks,'training model',len(modern),flush=True)
    model=Model.train(modern);mass=model.validate()
    (out/'model.json').write_text(json.dumps(model.data,ensure_ascii=False),encoding='utf8')
    chars={r['char']:r['readings'].split('|') for r in table(data/'pronunciation/pronunciation_char.tsv')}
    hot={r['word'] for r in table(data/'ac/ac_lock.tsv')};entries={}
    for r in table(data/'pronunciation/pronunciation.tsv'):
        word=r['entry'];ps=readings(r['readings'],len(word))
        if 2<=len(word)<=6 and re.fullmatch('[\u4e00-\u9fff]+',word) and ps:
            entries[word]=dict(word=word,readings=ps,hot=word in hot)
    for r in table(data/'correction/candidates.tsv'):
        if r['status']!='1':continue
        word=r['canonical'];ps=readings(r['pinyin'],len(word))
        if word not in entries and ps:entries[word]=dict(word=word,readings=ps,hot=word in hot)
    (out/'competitors.json').write_text(json.dumps(dict(characters=chars,entries=list(entries.values())),ensure_ascii=False),encoding='utf8')
    params=dict(calibrated=False,classes={'same':[0.,1.],'tone':[0.,1.],'near':[0.,1.]},alpha=.01,kappa=10.,rho=1.,top_h=30,retrieval_limit=50,
                note='Engineering initial values, not fitted or validated risk parameters.')
    (out/'parameters.json').write_text(json.dumps(params,indent=2),encoding='utf8')
    paths=['model.json','evidence.sqlite','competitors.json','parameters.json']
    manifest=dict(format='tc-evidence-package-2',files={n:sha(out/n) for n in paths},
        frontend_sha256=sha(frontend),source_db_sha256=sha(old_db),docs=n_docs,segments=n_blocks,
        duplicate_docs_removed=duplicates,competitors=len(entries),mass_error=mass,boundary_counts=edge_counts,
        training='modern fragments only; explicit observed edges; duplicate clusters clipped; no truth read',
        source_capabilities=dict(full_text=True,raw_mapping_validated=True,supplied_clusters=True,source_family=True,segment_edges=True),
        source_limitations=['Unknown/layout/pause boundaries are not joined or treated as sentence stops',
            'Only U+4E00-U+9FFF participates; unsupported characters split fragments',
            'Supplied cluster identities are respected, not proof that all near copies are detected',
            'Document start/end count as sentence boundaries only for modern sentence documents'],
        retrieval_policy=dict(block_chars=BLOCK_CHARS,char_budget=EVIDENCE_CHARS,context_chars=3),
        source_files={str(p.resolve().relative_to(PROJECT)):sha(p) for p in [data/'pronunciation/pronunciation.tsv',data/'pronunciation/pronunciation_char.tsv',data/'correction/candidates.tsv',data/'ac/ac_lock.tsv']})
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['files','source_files']},ensure_ascii=False),flush=True)

def prepare(old_db,out,data,frontend,legacy_boundaries=False):
    db=sqlite3.connect(pathlib.Path(old_db).resolve().as_uri()+'?mode=ro',uri=True)
    cols={r[1] for r in db.execute('pragma table_info(segs)')};db.close()
    if not legacy_boundaries and {'left_class','right_class','left_is_stop','right_is_stop'}<=cols:
        return prepare_v2(old_db,out,data,frontend)
    return prepare_legacy(old_db,out,data,frontend)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-db',required=True);p.add_argument('--output',required=True)
    p.add_argument('--data',default='data');p.add_argument('--frontend',required=True)
    p.add_argument('--legacy-boundaries',action='store_true',help='reproduce the legacy package for controlled research')
    a=p.parse_args();prepare(a.source_db,a.output,a.data,a.frontend,a.legacy_boundaries)
