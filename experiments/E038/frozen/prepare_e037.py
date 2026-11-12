"""Build a research package from E033 raw evidence, never from ASR truth.
This adapter is not the Qwen corpus delivery: see docs/RAG_DATA_CONTRACT.md.
"""
import argparse, collections, csv, hashlib, json, pathlib, re, sqlite3
from rag_clean import Model,sha,han_runs

def table(path):
    with open(path,encoding='utf8') as f:return list(csv.DictReader((l for l in f if not l.startswith('#')),delimiter='\t'))

def readings(s,length):
    out=[]
    for form in s.split('|'):
        parts=re.findall('[a-zv:]+[0-5]',form)
        if len(parts)==length and ''.join(parts)==form:out.append(parts)
    return out

def prepare(old_db,out,data,frontend):
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

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-db',required=True);p.add_argument('--output',required=True)
    p.add_argument('--data',default='data');p.add_argument('--frontend',required=True)
    a=p.parse_args();prepare(a.source_db,a.output,a.data,a.frontend)
