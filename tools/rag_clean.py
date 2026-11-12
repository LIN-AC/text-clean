"""Retrieval + normalized character MKN + KEEP-aware evidence decision.

No static word frequencies enter this module. Standard library only.
Uncalibrated packages require --research to produce edits.
"""
import argparse
import collections
import csv
import functools
import hashlib
import io
import json
import math
import pathlib
import re
import sqlite3
import subprocess

BOS, EOS, UNK = '^', '$', '?'
BLOCK_CHARS, EVIDENCE_CHARS = 256, 8192

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def han_runs(text):
    return re.findall(r'[\u4e00-\u9fff]+', text)

def local_context(text, begin, end):
    """Literal contiguous Han context. A newline is never consumed by an anchor."""
    left=begin;right=end
    while left and '\u4e00'<=text[left-1]<='\u9fff':left-=1
    while right<len(text) and '\u4e00'<=text[right]<='\u9fff':right+=1
    # Transcript edges are document boundaries; internal cue breaks are unknown.
    bos=left==0 or text[left-1] in '。？！?!'
    eos=right==len(text) or text[right] in '。？！?!'
    return text[left:begin],text[end:right],bos,eos

def transition_events(model,text,left_context='',bos=False,eos=False):
    """Only complete three-character histories; no artificial fragment BOS/EOS."""
    history=(BOS*3 if bos else '')+model.encode(left_context)
    history=history[-3:]
    for char in model.encode(text)+(EOS if eos else ''):
        if len(history)==3:yield history,char
        history=(history+char)[-3:]

class Model:
    """Interpolated modified Kneser-Ney; lower orders use continuation counts."""
    def __init__(self, data):
        if data['format'] != 'tc-mkn-1' or data['order'] != 4:
            raise ValueError('expected tc-mkn-1 character order 4')
        self.data = data
        self.vocab = frozenset(data['vocab'])
        if not {EOS, UNK} <= self.vocab or BOS in self.vocab:
            raise ValueError('invalid prediction alphabet')
        self.c = {n: dict(data['counts'][str(n)]) for n in range(1,5)}
        alphabet=self.vocab|{BOS}
        for n,counts in self.c.items():
            for g,count in counts.items():
                if len(g)!=n or not isinstance(count,int) or count<=0 or g[-1] not in self.vocab or any(ch not in alphabet for ch in g):
                    raise ValueError('invalid ngram count/alphabet')
        for n in range(2,5):
            ds=data['discounts'][str(n)]
            if len(ds)!=3 or not all(math.isfinite(d) and 0<=d<i+1 for i,d in enumerate(ds)):
                raise ValueError('invalid discounts')
        self.total = sum(self.c[1].values())
        if self.total <= 0 or self.c[1].get(UNK,0) <= 0 or self.c[1].get(EOS,0)<=0:
            raise ValueError('training must include mapped unknown characters')
        self.den, self.bo = {}, {}
        for n in range(2,5):
            sums, discounts = collections.Counter(), collections.Counter()
            ds = data['discounts'][str(n)]
            for g,c in self.c[n].items():
                if len(g)!=n or c<=0 or g[-1] not in self.vocab:
                    raise ValueError('invalid ngram')
                sums[g[:-1]] += c
                discounts[g[:-1]] += ds[min(c,3)-1]
            for h,c in sums.items():
                self.den[h]=c; self.bo[h]=discounts[h]/c

    @staticmethod
    def train(sentences, min_char_count=2):
        sentences=list(sentences)
        boundary_aware=any(not isinstance(s,str) for s in sentences)
        fragments=[(s,True,True) if isinstance(s,str) else s for s in sentences]
        freq=collections.Counter(''.join(s for s,_,_ in fragments))
        vocab={c for c,n in freq.items() if n>=min_char_count}|{UNK,EOS}
        unsupported=[]
        if boundary_aware:
            # A character observed only at unknown fragment starts has no observed
            # predecessor type. Map it to UNK instead of assigning zero LM mass.
            supported={c for s,bos,_ in fragments for i,c in enumerate(s) if i or bos}
            unsupported=sorted(vocab-supported-{UNK,EOS})
            vocab.difference_update(unsupported)
        raw={n:collections.Counter() for n in range(1,5)}
        for sentence,bos,eos in fragments:
            prefix=BOS*3 if bos else ''
            s=prefix+''.join(c if c in vocab else UNK for c in sentence)+(EOS if eos else '')
            for i in range(len(prefix),len(s)):
                for n in range(1,min(4,i+1)+1):raw[n][s[i-n+1:i+1]]+=1
        counts={4:raw[4]}
        for n in range(1,4):
            # Each distinct preceding character contributes one continuation.
            counts[n]=collections.Counter(g[1:] for g in raw[n+1])
        discounts={}; fallbacks=[]
        for n in range(2,5):
            nr=collections.Counter(counts[n].values())
            if all(nr[i]>0 for i in range(1,5)):
                y=nr[1]/(nr[1]+2*nr[2])
                ds=[1-2*y*nr[2]/nr[1],2-3*y*nr[3]/nr[2],3-4*y*nr[4]/nr[3]]
                if not all(0<d<i+1 for i,d in enumerate(ds)):
                    ds=[.75]*3; fallbacks.append(n)
            else: ds=[.75]*3; fallbacks.append(n)
            discounts[str(n)]=ds
        data=dict(format='tc-mkn-1',order=4,vocab=sorted(vocab),
                  counts={str(n):sorted(c.items()) for n,c in counts.items()},
                  discounts=discounts,discount_fallback_orders=fallbacks,
                  min_char_count=min_char_count,sentences=len(sentences))
        if boundary_aware:
            data['boundary_policy']='explicit-edges-1'
            data['no_continuation_characters']=unsupported
            if any(counts[1].get(c,0)<=0 for c in vocab):
                raise ValueError('training alphabet has characters without continuation support')
        return Model(data)

    def encode(self, text):
        return ''.join(c if c in self.vocab or c==BOS else UNK for c in text)

    @functools.lru_cache(maxsize=100000)
    def probability(self, history, char):
        if char not in self.vocab: char=UNK
        history=self.encode(history)[-3:]
        if not history: return self.c[1].get(char,0)/self.total
        den=self.den.get(history,0)
        if not den: return self.probability(history[1:],char)
        count=self.c[len(history)+1].get(history+char,0)
        d=self.data['discounts'][str(len(history)+1)][min(count,3)-1] if count else 0
        return max(count-d,0)/den+self.bo[history]*self.probability(history[1:],char)

    def validate(self, limit=32):
        hs=['',BOS*3]+sorted(self.den)[:limit]
        worst=max(abs(sum(self.probability(h,w) for w in self.vocab)-1) for h in hs)
        if worst>1e-8: raise ValueError('model probability mass invalid')
        return worst

class EvidenceStore:
    def __init__(self, path, model):
        self.db=sqlite3.connect(pathlib.Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        self.model=model
        version=self.db.execute("select value from meta where key='format'").fetchone()
        if version not in [('tc-rag-1',),('tc-rag-2',)]: raise ValueError('unsupported evidence DB')
        self.boundary_aware=version==('tc-rag-2',)
        self.char_budget=EVIDENCE_CHARS
        self.cache={}
        self.last_retrieval={}

    def global_terms(self,text):
        counts=collections.Counter(s[i:i+2] for s in han_runs(text) for i in range(len(s)-1))
        # Retrieval-only TF/IDF, never a term in the correction score.
        ranked=[]
        for term,tf in counts.items():
            row=self.db.execute('select docs from term_docs where term=?',(term,)).fetchone()
            if row: ranked.append((math.log1p(tf)/math.log(2+row[0]),term))
        return [term for _,term in sorted(ranked,reverse=True)[:32]]

    def retrieve(self, query, limit):
        tokens=sorted({s[i:i+2] for s in han_runs(query) for i in range(len(s)-1)})
        self.last_retrieval=dict(segments=[],evidence_chars=0,char_budget=self.char_budget,budget_cut=False)
        if not tokens: return (),[]
        key=(tuple(tokens),limit)
        if key in self.cache:
            result,self.last_retrieval=self.cache[key]
            return result
        match=' OR '.join('"'+t+'"' for t in tokens)
        if self.boundary_aware:
            rows=self.db.execute('select s.id,s.cluster_id,s.text,s.off,s.left_context,s.bos,s.eos,'
                's.left_class,s.right_class,d.source_family,d.source_doc_id '
                'from search join segments s on s.id=search.rowid join documents d on d.cluster_id=s.cluster_id '
                'where search match ? order by bm25(search),search.rowid limit ?',(match,limit))
        else:
            rows=self.db.execute('select segments.cluster_id,segments.text from search join segments '
                'on segments.id=search.rowid where search match ? order by bm25(search),search.rowid limit ?',
                (match,limit))
        # Retrieval scores never become confidence or a correction permission.
        by_doc=collections.defaultdict(set)
        for row in rows:
            if self.boundary_aware:
                sid,doc,txt,off,left,bos,eos,lc,rc,family,source_doc=row
                if len(txt)>BLOCK_CHARS or len(left)>3:raise ValueError('oversized evidence block')
                remaining=self.char_budget-self.last_retrieval['evidence_chars']
                if remaining<=len(left):
                    self.last_retrieval['budget_cut']=True;break
                kept=txt[:remaining-len(left)]
                cut=len(kept)<len(txt)
                self.last_retrieval['evidence_chars']+=len(left)+len(kept)
                self.last_retrieval['segments'].append(dict(id=sid,cluster_id=doc,source_doc_id=source_doc,
                    off=off,chars=len(kept),context_chars=len(left),source_family=family,left_class=lc,
                    right_class='载荷截断' if cut else rc,bos=bool(bos),eos=bool(eos and not cut)))
                by_doc[doc].update(transition_events(self.model,kept,left,bos,eos and not cut))
                if cut or self.last_retrieval['evidence_chars']==self.char_budget:
                    self.last_retrieval['budget_cut']=True;break
            else:
                doc,txt=row
                for run in han_runs(txt):by_doc[doc].update(transition_events(self.model,run,bos=True,eos=True))
        rows.close()
        counts=collections.Counter()
        for events in by_doc.values(): counts.update(events)
        totals=collections.Counter()
        for (h,w),n in counts.items(): totals[h]+=n
        docs=sorted(by_doc)
        result=((counts,totals),docs)
        # Bounded, video-local cache. The store is released after a video.
        if len(self.cache)>=256: self.cache.pop(next(iter(self.cache)))
        self.cache[key]=(result,self.last_retrieval)
        return result

def affected_scores(model, domain, kappa, left, word, right, bos=True, eos=True):
    if not math.isfinite(kappa) or kappa<=0: raise ValueError('kappa must be positive')
    counts,totals=domain if domain else ({},{})
    h=((BOS*3 if bos else '')+model.encode(left))[-3:]; general=mixed=0.
    # Include EOS if this is a real sentence boundary, never an artificial window edge.
    tail=right[:3] if len(right)>=3 else right+(EOS if eos else '')
    for w in model.encode(word)+model.encode(tail):
        p=model.probability(h,w)
        q=(counts.get((h,w),0)+kappa*p)/(totals.get(h,0)+kappa)
        if p<=0 or q<=0: raise ValueError('zero probability in shared alphabet')
        general+=math.log(p);mixed+=math.log(q);h=(h+w)[-3:]
    return general,mixed

def posterior(scores,rho):
    if not math.isfinite(rho) or rho<0 or not all(math.isfinite(s) for s in scores):
        raise ValueError('non-finite score or invalid background mass')
    all_scores=[0.]+list(scores)+([math.log(rho)] if rho else [])
    m=max(all_scores);z=sum(math.exp(s-m) for s in all_scores)
    return [math.exp(s-m)/z for s in all_scores]

def edit_one(a,b):
    if abs(len(a)-len(b))>1:return False
    if len(a)==len(b):return sum(x!=y for x,y in zip(a,b))<=1
    if len(a)>len(b):a,b=b,a
    return any(a==b[:i]+b[i+1:] for i in range(len(b)))

def phonetic_class(source, variants, chars):
    best=None
    rank={'same':0,'tone':1,'near':2,'unknown':3}
    for v in variants:
        if len(v)!=len(source):continue
        differences=0;tones=False;unknown=False;valid=True
        for i,(ch,target) in enumerate(zip(source,v)):
            options=chars.get(ch,[]); tb=target.rstrip('012345')
            same=[x for x in options if x.rstrip('012345')==tb]
            if not same:
                if i==0 or not any(edit_one(x.rstrip('012345'),tb) for x in options):valid=False;break
                differences+=1
            else:
                unknown |= not target[-1:].isdigit() or target.endswith('0') or any(not x[-1:].isdigit() or x.endswith('0') for x in same)
                tones |= target not in same
        if not valid or differences>1:continue
        c='unknown' if unknown else 'near' if differences else 'tone' if tones else 'same'
        if best is None or rank[c]<rank[best]:best=c
    return best

class Cleaner:
    def __init__(self, package, executable, research=False, use_retrieval=True):
        if not use_retrieval and not research:raise ValueError('retrieval ablation is research-only')
        self.use_retrieval=use_retrieval
        root=pathlib.Path(package);self.manifest=json.loads((root/'manifest.json').read_text('utf8'))
        if self.manifest['format'] not in ('tc-evidence-package-1','tc-evidence-package-2'):raise ValueError('unsupported package')
        if self.manifest['format']=='tc-evidence-package-2' and self.manifest.get('retrieval_policy')!=dict(
                block_chars=BLOCK_CHARS,char_budget=EVIDENCE_CHARS,context_chars=3):
            raise ValueError('unsupported evidence payload policy')
        for name,digest in self.manifest['files'].items():
            p=(root/name).resolve()
            if root.resolve() not in p.parents or sha(p)!=digest:raise ValueError('package hash mismatch: '+name)
        for required in ['model.json','evidence.sqlite','competitors.json','parameters.json']:
            if required not in self.manifest['files']:raise ValueError('unbound required artifact: '+required)
        self.model=Model(json.loads((root/'model.json').read_text('utf8')));self.model.validate()
        self.store=EvidenceStore(root/'evidence.sqlite',self.model)
        if self.manifest['format']=='tc-evidence-package-2' and (
                not self.store.boundary_aware or self.model.data.get('boundary_policy')!='explicit-edges-1'):
            raise ValueError('package/model boundary policy mismatch')
        self.params=json.loads((root/'parameters.json').read_text('utf8'))
        self.words=json.loads((root/'competitors.json').read_text('utf8'))
        self.chars=self.words['characters']; self.entries=self.words['entries']
        self.readings={e['word']:e['readings'] for e in self.entries}
        self.by_first=collections.defaultdict(list)
        for e in self.entries:
            for base in {v[0].rstrip('012345') for v in e['readings'] if v}:
                self.by_first[len(e['word']),base].append(e)
        self.exe=str(pathlib.Path(executable).resolve());self.research=research
        if sha(self.exe)!=self.manifest['frontend_sha256']:raise ValueError('frontend hash mismatch')
        self.project=pathlib.Path(__file__).resolve().parents[1]
        for name,digest in self.manifest['source_files'].items():
            if sha(self.project/name)!=digest:raise ValueError('candidate/pronunciation source changed: '+name)
        self.params['model_bound']=True
        for key in ['alpha','kappa','rho']:
            if not math.isfinite(self.params[key]):raise ValueError('invalid parameter')
        if not 0<self.params['alpha']<.5 or self.params['kappa']<=0 or self.params['rho']<0:
            raise ValueError('invalid risk parameters')
        for a,b in self.params['classes'].values():
            if not math.isfinite(a) or not 0<b<=1:raise ValueError('invalid class parameters')

    def clean(self,text,title='',description=''):
        if hasattr(self.store,'cache'):self.store.cache.clear()
        global_terms=self.store.global_terms(title+' '+description+' '+text) if self.use_retrieval else []
        p=subprocess.run([self.exe,'--candidate-export','--no-ctx-evidence','--no-index-cache'],
                         input=text.encode('utf8'),capture_output=True,check=True,cwd=self.project)
        windows=collections.defaultdict(set)
        for r in csv.DictReader(io.StringIO(p.stdout.decode('utf8')),delimiter='\t'):
            b,e=int(r['begin']),int(r['end'])
            if text[b:e]!=r['source']:raise ValueError('candidate offset mismatch')
            windows[b,e].add(r['target'])
        logs=[]; proposals=[]
        for (b,e),targets in sorted(windows.items()):
            source=text[b:e]
            l,rr,bos,eos=local_context(text,b,e)
            if not getattr(self.store,'boundary_aware',False):bos=eos=True
            query=title+' '+description+' '+text[max(0,b-180):b]+' '+text[e:e+180]
            # Remove all occurrences, including repeated wrong ASR or target names.
            for term in sorted(targets|{source},key=len,reverse=True):query=query.replace(term,' ')
            query+=' '+' '.join(t for t in global_terms if not any(t in w for w in targets|{source}))
            domain,docs=self.store.retrieve(query,self.params['retrieval_limit']) if self.use_retrieval else ((),[])
            retrieval_audit=dict(getattr(self.store,'last_retrieval',{})) if self.use_retrieval else {}
            og,om=affected_scores(self.model,domain,self.params['kappa'],l,source,rr,bos,eos)
            scored=[];excluded=collections.Counter()
            pool={ent['word']:ent for reading in self.chars.get(source[0],[])
                  for ent in self.by_first[e-b,reading.rstrip('012345')]}
            for ent in pool.values():
                word=ent['word']
                if word==source:continue
                cls=phonetic_class(source,ent['readings'],self.chars)
                if cls is None or cls not in self.params['classes']:
                    excluded['phonetic_or_unknown_class']+=1;continue
                if any(c not in self.model.vocab for c in source+word):
                    excluded['unknown_character']+=1;continue
                g,m=affected_scores(self.model,domain,self.params['kappa'],l,word,rr,bos,eos)
                G=g-og;D=(m-om)-G;a,beta=self.params['classes'][cls]
                scored.append(dict(word=word,cls=cls,G=G,D=D,S=a+beta*G+D,mix=m,
                                   executable=word in targets,hot=ent.get('hot',False)))
            # Form H using P_mix; fold scored, excluded competition mass into OTHER.
            scored.sort(key=lambda x:(-x['mix'],x['word']))
            H=[s for i,s in enumerate(scored) if i<self.params['top_h'] or s['hot']]
            tail=[s for i,s in enumerate(scored) if i>=self.params['top_h'] and not s['hot']]
            # Normalize stably across explicit H and tail; no exp overflow for tail mass.
            probs=posterior([s['S'] for s in H+tail],self.params['rho'])
            for s,pv in zip(H,probs[1:]):s['p']=pv
            tail_p=sum(probs[1+len(H):1+len(H)+len(tail)])
            best=max(H,key=lambda x:x['p']) if H else None
            reason='evidence_insufficient'
            allowed=self.params.get('calibrated',False) or self.research
            if not allowed:reason='uncalibrated'
            elif best and best['executable'] and best['p']>=1-self.params['alpha']:
                reason='proposed';proposals.append(dict(begin=b,end=e,target=best['word'],p=best['p']))
            logs.append(dict(begin=b,end=e,source=source,docs=docs,H=H,keep=probs[0],
                             other=tail_p+(probs[-1] if self.params['rho'] else 0),reason=reason,
                             excluded=excluded,targets=sorted(targets),pool_size=len(pool),tail_size=len(tail),
                             missing_target_readings=sorted(targets-self.readings.keys()),
                             context=dict(left=l[-3:],right=rr[:3],bos=bos,eos=eos),retrieval=retrieval_audit))
        # Conflicting successful windows abstain as a component; never greedily apply.
        accepted=[];i=0
        while i<len(proposals):
            j=i+1;end=proposals[i]['end']
            while j<len(proposals) and proposals[j]['begin']<end:
                end=max(end,proposals[j]['end']);j+=1
            if j==i+1:accepted.append(proposals[i])
            i=j
        out=list(text)
        for p in accepted:out[p['begin']:p['end']]=p['target']
        accepted_spans={(p['begin'],p['end']) for p in accepted}
        for log in logs:
            if log['reason']=='proposed':
                log['reason']='applied' if (log['begin'],log['end']) in accepted_spans else 'overlap_abstention'
        return dict(text=''.join(out),edits=accepted,windows=logs,research=self.research,
                    calibrated=self.params.get('calibrated',False),retrieval=self.use_retrieval)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--package',required=True);ap.add_argument('--executable',required=True)
    ap.add_argument('--input',required=True);ap.add_argument('--output',required=True)
    ap.add_argument('--title',default='');ap.add_argument('--description',default='');ap.add_argument('--research',action='store_true')
    ap.add_argument('--no-retrieval',action='store_true')
    a=ap.parse_args();c=Cleaner(a.package,a.executable,a.research,not a.no_retrieval)
    result=c.clean(pathlib.Path(a.input).read_text('utf8'),a.title,a.description)
    pathlib.Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
