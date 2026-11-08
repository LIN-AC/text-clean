"""Read-only human-subset experiment; no algorithm or annotation writes.

Run from repository root: python tools/p_independent_probe.py
Standard library only. Outputs and input hashes in log/p_independent.
"""
import collections, hashlib, json, math, pathlib, re, subprocess, time, random

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'log/p_independent'
BV = 'BV1uUak6pEdK'
DROP = re.compile('[^一-鿿0-9A-Za-z]')
HAN = re.compile('[一-鿿]+')
files = {}
def read(name):
    p = ROOT / name
    files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return p.read_text(encoding='utf-8-sig')
def auc(y, s):
    pos, neg = sum(y), len(y)-sum(y)
    if not pos or not neg: return None
    groups = collections.defaultdict(lambda: [0, 0])
    for a,b in zip(y,s): groups[b][a] += 1
    n = total = 0
    for score,(no,yes) in sorted(groups.items()):
        total += yes*(n+no/2); n += no
    return total/(pos*neg)
def curve(y,s):
    groups=collections.defaultdict(lambda:[0,0])
    for a,b in zip(y,s): groups[b][a]+=1
    points=[(0,0,None)];tp=fp=0
    for v,(n,p) in sorted(groups.items(),reverse=True):
        tp+=p;fp+=n;points.append((tp,fp,v))
    return {'auc':auc(y,s),'n':len(y),'positive':sum(y),
            'at_tp':{str(r):dict(zip(['tp','fp','threshold'],next(x for x in points if x[0]>=math.ceil(sum(y)*r)))) for r in [.9,.95,.99,1]},
            'at_fp':{str(b):dict(zip(['tp','fp','threshold'],max((x for x in points if x[1]<=b),key=lambda x:x[0]))) for b in [0,5,10,20]}}
def model_scores(rows, fields):
    # Five contiguous time blocks; all rows of a segment stay in one fold.
    scores=[0.]*len(rows)
    for fold in range(5):
        train=[r for r in rows if r['fold']!=fold]
        means=[sum(r[k] for r in train)/len(train) for k in fields]
        sd=[max(1e-6,(sum((r[k]-m)**2 for r in train)/len(train))**.5) for k,m in zip(fields,means)]
        def features(r): return [1.]+[(r[k]-m)/s for k,m,s in zip(fields,means,sd)]
        xx=[features(r) for r in train]; yy=[r['y'] for r in train];w=[0.]*(len(fields)+1)
        for _ in range(220):
            grad=[0.]*len(w)
            for x,y in zip(xx,yy):
                z=max(-30,min(30,sum(a*b for a,b in zip(w,x))))
                e=1/(1+math.exp(-z))-y
                for j,v in enumerate(x):grad[j]+=e*v
            for j in range(len(w)):w[j]-=.15*(grad[j]/len(train)+(.01*w[j] if j else 0))
        for i,r in enumerate(rows):
            if r['fold']==fold:
                z=max(-30,min(30,sum(a*b for a,b in zip(w,features(r)))))
                scores[i]=1/(1+math.exp(-z))
    return scores

def main():
    started=time.perf_counter();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'working_tree.patch').write_bytes(subprocess.check_output(['git','diff','HEAD','--','src','include','CMakeLists.txt'],cwd=ROOT))
    for directory in ['src','include']:
        for path in (ROOT/directory).rglob('*'):
            if path.is_file():files[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    segments=json.loads(read(f'asr/{BV}.json'))['transcription']
    items=json.loads(read(f'asr/{BV}.mark.json'))['items']
    decisions=json.loads(read(f'asr/{BV}.decisions.round4.json'))['decisions']
    gt=[json.loads(l) for l in read(f'asr/{BV}.gt.jsonl').splitlines()]
    # Snapshot all human assets, including ones deliberately NOT used as truth.
    for p in (ROOT/'asr').glob(BV+'*'):
        if p.suffix in ('.json','.jsonl','.md','.txt'):read(str(p.relative_to(ROOT)))
    stream=''; positions=[]; texts=[]; counts=collections.Counter(); token_spans={}
    for si,seg in enumerate(segments):
        tokens=[(j,t) for j,t in enumerate(seg['tokens']) if not t['text'].startswith('[_')]
        joined=''.join(t['text'] for _,t in tokens)
        assert joined==seg['text'], ('token concatenation mismatch',si)
        text=DROP.sub('',seg['text']); assert text==gt[si]['text']
        texts.append(text)
        segp=[t['p'] for _,t in tokens if HAN.search(t['text'])]
        for j,t in tokens:
            chars=DROP.sub('',t['text']);counts['text_tokens']+=1
            if len(chars)>1:counts['multi_character_tokens']+=1
            token_spans[(si,j)]=(len(stream),len(stream)+len(chars))
            for c in chars:
                positions.append(dict(cue=si,token=j,p=t['p'],segmin=min(segp) if segp else 1,segmean=sum(segp)/len(segp) if segp else 1))
                stream+=c
    freq={}
    for line in read('data/word_freq.txt').splitlines():
        a=line.split()
        if len(a)>1 and a[1].isdigit():freq[a[0]]=int(a[1])
    vocab={}
    for line in read('data/dict.txt').splitlines():
        a=line.split()
        if len(a)>1 and a[1].isdigit():vocab[a[0]]=int(a[1])
    def features(a,b):
        s=stream[a:b]; cover=[]
        for l in range(max(0,a-15),a+1):
            for e in range(max(l+2,a+1),min(len(stream),b+15,l+16)+1):
                if positions[l]['cue']!=positions[e-1]['cue']:continue
                if stream[l:e] in vocab:cover.append((e-l,vocab[stream[l:e]]))
        return dict(length=b-a,logfreq=math.log1p(freq.get(s,0)),member=float(s in vocab),
                    coverlen=max([x[0] for x in cover],default=0),coverfreq=math.log1p(max([x[1] for x in cover],default=0)))
    labels={}; rows=[]; rejected=collections.Counter()
    for item in items:
        dec=decisions.get(item['id'])
        if not dec:rejected['unreviewed']+=1;continue
        a,b=item['i1'],item['i2'];src=stream[a:b]
        assert src==item['w'],item['id']
        truth=src if dec['d']=='W' else item['a'] if dec['d']=='A' else dec.get('text','')
        if not src or len(src)!=len(truth) or not HAN.fullmatch(src) or not HAN.fullmatch(truth):
            rejected['non_equal_Han_or_unlocatable']+=1;continue
        if positions[a]['cue']!=positions[b-1]['cue']:rejected['cross_cue']+=1;continue
        si=positions[a]['cue'];start=sum(len(t) for t in texts[:si]);g=gt[si]
        # Disputed human decisions / later overrides are not silently resolved.
        if len(g['gt'])!=len(g['text']) or g['gt'][a-start:b-start]!=truth:
            rejected['current_truth_conflict_or_changed_length']+=1;continue
        if any(k in labels and labels[k]!=v for k,v in zip(range(a,b),truth)):
            raise ValueError('contradictory reviewed spans')
        labels.update(zip(range(a,b),truth))
        ps=[positions[k]['p'] for k in range(a,b)]
        # p is token evidence: do not claim exact character attribution inside a multi-char token.
        pure=all(token_spans[(si,positions[k]['token'])][1]-token_spans[(si,positions[k]['token'])][0]==1 for k in range(a,b))
        rows.append(dict(id=item['id'],a=a,b=b,src=src,truth=truth,cue=si,fold=min(4,si*5//len(segments)),
                         y=int(src!=truth),pmin=min(ps),pmean=sum(ps)/len(ps),segmin=positions[a]['segmin'],
                         segmean=positions[a]['segmean'],single_tokens=pure,**features(a,b)))
    fields=['length','logfreq','member','coverlen','coverfreq']
    y=[r['y'] for r in rows]
    models={}
    for name,fs in [('text',fields),('p',['pmin','pmean']),('text+p',fields+['pmin','pmean']),('text+segment_p',fields+['segmin','segmean'])]:
        scores=model_scores(rows,fs);models[name]=curve(y,scores)
        models[name]['fold_auc']=[auc([r['y'] for r in rows if r['fold']==f],[s for r,s in zip(rows,scores) if r['fold']==f]) for f in range(5)]
        for r,s in zip(rows,scores):r[name+'_score']=s
    # Paired block bootstrap of held-out predictions, not an iid character CI.
    rng=random.Random(20261104);blocks=collections.defaultdict(list)
    for r in rows:blocks[r['cue']//210].append(r)
    deltas=[]
    for _ in range(1000):
        sample=[r for key in rng.choices(list(blocks),k=len(blocks)) for r in blocks[key]]
        yy=[r['y'] for r in sample]
        deltas.append(auc(yy,[r['text+p_score'] for r in sample])-auc(yy,[r['text_score'] for r in sample]))
    deltas.sort()
    grouped=[dict(r,fold=int(hashlib.sha256(r['src'].encode()).hexdigest()[:8],16)%5) for r in rows]
    source_group_sensitivity={name:curve(y,model_scores(grouped,fs)) for name,fs in [('text',fields),('text+p',fields+['pmin','pmean'])]}
    bins=[]
    for lo,hi in [(0,.5),(.5,.9),(.9,.99),(.99,1.000001)]:
        rr=[r for r in rows if lo<=r['pmin']<hi];bins.append(dict(lo=lo,hi=hi,n=len(rr),errors=sum(r['y'] for r in rr)))
    # Actual accepted proposals from unchanged executables, using independent existing lexicons.
    cli_text='\n'.join(texts); cli_map=[];st=0
    for t in texts:cli_map.extend(range(st,st+len(t)));cli_map.append(None);st+=len(t)
    (OUT/'input.txt').write_bytes(cli_text.encode('utf8'))
    rx=re.compile(r'\[(\w+)\] status=\w+ (\d+)\.\.(\d+) "([^"]*)" -> "([^"]*)" entry=\d+ distance=(\d+) score=([\d.e+-]+) logR=([\d.e+-]+) fC=([\d.e+-]+) fO=([\d.e+-]+) action=replace')
    experiments={};proposals=[]
    for arm,exe,lex in [('current_default','build-v123/text_clean.exe','data/lexicon.txt'),('current_expanded','build-v123/text_clean.exe','datasets/ctc_probe_lexicon.txt'),('v122_expanded','build-v122-gcc/text_clean.exe','datasets/ctc_probe_lexicon.txt')]:
        for path in [exe,lex]:files[path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        command=[str(ROOT/exe),'--input-file',str(OUT/'input.txt'),'--lexicon',str(ROOT/lex),'-v']
        run=subprocess.run(command,cwd=ROOT,capture_output=True,encoding='utf8',check=True)
        (OUT/(arm+'.stderr')).write_text(run.stderr,encoding='utf8')
        rs=[];skip=collections.Counter()
        for m in rx.finditer(run.stderr):
            kind,a,b,src,dst,dist,score,ratio,fc,fo=m.groups();a=int(a);b=int(b)
            assert cli_text[a:b]==src
            if src==dst:continue
            skip['all_proposals']+=1
            if len(src)!=len(dst):skip['length_change']+=1;continue
            changed=[cli_map[k] for k in range(a,b) if cli_text[k]!=dst[k-a]]
            if any(k is None or k not in labels for k in changed):skip['unlabelled_change']+=1;continue
            indices=cli_map[a:b]
            if None in indices:skip['cross_cue']+=1;continue
            ok=all(dst[k-a]==labels[cli_map[k]] for k in range(a,b) if cli_text[k]!=dst[k-a])
            original_ok=all(stream[k]==labels[k] for k in changed)
            ps=[positions[k]['p'] for k in indices]
            si=positions[indices[0]]['cue']
            rs.append(dict(arm=arm,src=src,dst=dst,y=int(ok),original_correct=original_ok,cue=si,fold=min(4,si*5//len(segments)),
                           fully_reviewed=all(k in labels for k in indices),pmin=min(ps),
                           changed_pmin=min(positions[k]['p'] for k in changed),segmin=positions[indices[0]]['segmin'],
                           score=float(score),distance=int(dist),logratio=float(ratio),fc=math.log1p(float(fc)),fo=math.log1p(float(fo)),**features(indices[0],indices[-1]+1)))
        result=dict(counts=dict(skip),evaluated=len(rs),tp=sum(r['y'] for r in rs),
                    fp_on_correct=sum(r['original_correct'] for r in rs),wrong=sum(not r['y'] and not r['original_correct'] for r in rs),fully_reviewed=sum(r['fully_reviewed'] for r in rs))
        if rs:
            result['curves']={k:curve([r['y'] for r in rs],[sign*r[k] for r in rs]) for k,sign in [('score',1),('pmin',-1),('changed_pmin',-1),('segmin',-1),('coverfreq',-1)]}
            result['high_p_veto']={str(th):{'tp':sum(r['y'] for r in rs if r['changed_pmin']<th),'bad':sum(not r['y'] for r in rs if r['changed_pmin']<th)} for th in [.9,.99,.999]}
            ff=['score','distance','logratio','fc','fo']+fields
            result['model_comparison']={name:curve([r['y'] for r in rs],model_scores(rs,fs)) for name,fs in [('existing',ff),('existing+p',ff+['changed_pmin','pmin']),('existing+segment_p',ff+['segmin'])]}
            strict=[r for r in rs if r['fully_reviewed']]
            result['fully_reviewed_counts']={'tp':sum(r['y'] for r in strict),'bad':sum(not r['y'] for r in strict)}
            # Correct original damaged by a replacement, separately from a wrong-to-wrong edit.
            clean=[r for r in rs if r['y'] or r['original_correct']]
            result['tp_vs_clean_fp']={k:curve([r['y'] for r in clean],[sign*r[k] for r in clean]) for k,sign in [('score',1),('changed_pmin',-1)]}
            result['high_p_clean_fp']={str(th):sum(r['original_correct'] for r in rs if r['changed_pmin']<th) for th in [.9,.99,.999]}
            # Optimistic in-sample envelope, never a validated deployable threshold.
            floor=min(r['score'] for r in rs if r['y']);ceiling=max(r['changed_pmin'] for r in rs if r['y'])
            kept=[r for r in rs if r['score']>=floor and r['changed_pmin']<=ceiling]
            result['oracle_keep_all_tp_combination']={'score_floor':floor,'p_ceiling':ceiling,'tp':sum(r['y'] for r in kept),'bad':sum(not r['y'] for r in kept),'clean_fp':sum(r['original_correct'] for r in kept)}
        experiments[arm]=result;proposals.extend(rs)
    single=[r for r in rows if r['single_tokens']]
    result=dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                alignment=dict(segments=len(segments),characters=len(stream),mismatches=0,**counts),
                rejected=dict(rejected),reviewed_spans=len(rows),reviewed_characters=len(labels),errors=sum(y),
                bins=bins,models=models,p_raw=curve(y,[-r['pmin'] for r in rows]),
                segment_gates={str(t):{'reviewed_spans_kept':sum(r['segmin']<t for r in rows),'errors_kept':sum(r['y'] for r in rows if r['segmin']<t)} for t in [.5,.9,.99]},
                auc_delta_block_bootstrap_95=[deltas[25],deltas[974]],source_group_sensitivity=source_group_sensitivity,
                single_token_sensitivity=dict(n=len(single),auc=auc([r['y'] for r in single],[-r['pmin'] for r in single])),
                experiments=experiments,input_sha256=files,elapsed_seconds=time.perf_counter()-started)
    for path,h in files.items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h,('input changed',path)
    for name,obj in [('results',result),('reviewed_spans',rows),('proposals',proposals)]:
        (OUT/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='input_sha256'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
