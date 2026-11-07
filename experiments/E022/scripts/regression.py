"""Open-book replay. E19 numeric/all-optimal alignment, never writes truth."""
import collections,decimal,hashlib,json,pathlib,re,subprocess
R=pathlib.Path(__file__).resolve().parents[3];E=R/'experiments/E022';O=E/'results'
def save(n,x):(O/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
D={c:i for i,c in enumerate('零一二三四五六七八九')};D.update({'〇':0,'两':2})
U={'十':10,'百':100,'千':1000,'万':10000,'亿':100000000}
def number(s):
    scale=1
    if ('.' in s or '点' in s) and s[-1:] in ('万','亿'):scale=U[s[-1]];s=s[:-1]
    if '.' in s or '点' in s:
        a,b=re.split('[.点]',s);v=decimal.Decimal(number(a)+'.'+''.join(str(D.get(c,c)) for c in b))*scale
        return format(v,'f').rstrip('0').rstrip('.') if '.' in format(v,'f') else str(v)
    if not any(c in U for c in s):return str(int(''.join(str(D.get(c,c)) for c in s)))
    total=section=n=0
    for c in s:
        if c not in U:n=n*10+int(D.get(c,c));continue
        u=U[c]
        if u<10000:section+=(n or 1)*u;n=0
        else:
            section+=n
            if u==100000000:total=(total+section)*u
            else:total+=section*u
            section=n=0
    return str(total+section+n)
NUM=re.compile('[0-9零〇一二两三四五六七八九十百千万亿]+(?:[.点][0-9零〇一二两三四五六七八九]+)?[万亿]?')
def tokens(s):
    out=[];i=0
    while i<len(s):
        m=NUM.match(s,i)
        if m and (len(m[0])>1 or m[0].isascii() or m[0] in U):out.append(('#'+number(m[0]),i,m.end(),True));i=m.end()
        elif re.match('[一-鿿A-Za-z0-9]',s[i]):out.append((s[i],i,i+1,False));i+=1
        else:i+=1
    return out
def align(src,tgt):
    a,b=tokens(src),tokens(tgt);n,m=len(a),len(b)
    def eq(i,j):
        x,y=a[i][0],b[j][0]
        return x==y or (x in D and y=='#'+str(D[x])) or (y in D and x=='#'+str(D[y]))
    f=[[0]*(m+1) for _ in range(n+1)];q=[[0]*(m+1) for _ in range(n+1)]
    for i in range(n+1):f[i][0]=i;q[i][m]=n-i
    for j in range(m+1):f[0][j]=j;q[n][j]=m-j
    for i in range(1,n+1):
        for j in range(1,m+1):f[i][j]=min(f[i-1][j]+1,f[i][j-1]+1,f[i-1][j-1]+(not eq(i-1,j-1)))
    for i in range(n-1,-1,-1):
        for j in range(m-1,-1,-1):q[i][j]=min(q[i+1][j]+1,q[i][j+1]+1,q[i+1][j+1]+(not eq(i,j)))
    labels={}
    for i,x in enumerate(a):
        if x[3]:continue
        possible=set()
        for j in range(m+1):
            if f[i][j]+1+q[i+1][j]==f[n][m]:possible.add(None)
            if j<m and f[i][j]+(not eq(i,j))+q[i+1][j+1]==f[n][m]:possible.add(j)
        if len(possible)==1 and None not in possible:
            y=b[next(iter(possible))]
            if not y[3]:labels[x[1]]=y[0]
    return labels,f[n][m]
assert align('公元前一百一十九年','公元前119年')[1]==0
assert align('税收2.9克','税收二点九克')[1]==0
assert align('八份三册','8份3册')[1]==0
assert align('甲甲','甲')[0]=={}
rx=re.compile(r'\[(\w+)\] status=\w+ (\d+)\.\.(\d+) "([^"]*)" -> "([^"]*)" entry=\d+ distance=(\d+) score=([\d.e+-]+).*?action=replace')
results={};coverage={}
for path in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(l) for l in path.read_text('utf8').splitlines() if l.strip()];assert not any(r.get('pending') for r in rows)
    kept=[r for r in rows if not r.get('discard')];body='\n'.join(r['text'] for r in kept)+'\n'
    labels={};offset=0;distance=0
    for row in kept:
        lab,dist=align(row['text'],row['gt']);labels.update({offset+k:v for k,v in lab.items()});offset+=len(row['text'])+1;distance+=dist
    errors=sum(body[k]!=v for k,v in labels.items())
    coverage[path.stem]=dict(cues=len(kept),labeled_characters=len(labels),substitution_errors=errors,normalized_distance=distance,discard=[r['index'] for r in rows if r.get('discard')])
    arms={}
    for mode in ['noop','counts','zipf']:
        if mode=='noop':output=body;stderr=''
        else:
            exe=R/'build/current/text_clean.exe'
            args=['--no-index-cache','-v']
            if mode=='counts':args+=['--word-freq',str(R/'data/old/word_freq.txt'),'--char-freq',str(R/'data/old/dict.txt')]
            p=subprocess.run([str(exe),*args],input=body.encode(),capture_output=True,check=True,cwd=R)
            if mode=='counts' and (E/'results/before.exe').exists():
                control=subprocess.run([str(E/'results/before.exe'),*args],input=body.encode(),capture_output=True,check=True,cwd=R)
                assert p.stdout==control.stdout # frozen E021 compatibility
            output=p.stdout.decode();stderr=p.stderr.decode()
        assert len(output)==len(body)
        for i,c in enumerate(body):
            if c=='\n' or c in '0123456789０１２３４５６７８９零〇一二两三四五六七八九十百千万亿':assert output[i]==c
        count=collections.Counter();chars=collections.Counter();edits=[]
        for m in rx.finditer(stderr):
            kind,a,b,src,dst,d,score=m.groups();a=int(a);b=int(b);assert body[a:b]==src and output[a:b]==dst
            changed=[k for k in range(len(src)) if src[k]!=dst[k]];truth=[labels.get(a+k) for k in changed]
            label='excluded' if None in truth else 'TP' if all(dst[k]==v for k,v in zip(changed,truth)) else 'FP' if all(src[k]==v for k,v in zip(changed,truth)) else 'wrong'
            count[label]+=1
            edits.append(dict(a=a,b=b,source=src,target=dst,label=label))
        for i,v in labels.items():
            if output[i]!=body[i]:chars['TP' if output[i]==v else 'FP' if body[i]==v else 'wrong']+=1
        after=sum(align(line,row['gt'])[1] for line,row in zip(output.splitlines(),kept))
        arms[mode]=dict(edits=count,characters=chars,remaining_substitution_errors=errors-chars['TP'],normalized_distance_after=after)
        (O/f'{path.stem}.{mode}.output').write_text(output,encoding='utf8');save(f'{path.stem}.{mode}.edits.json',edits)
    results[path.stem]=arms;print(path.stem,arms['zipf'],flush=True)
save('results.json',results);save('coverage.json',coverage)
summary={}
for mode in ['noop','counts','zipf']:
    w=collections.Counter();c=collections.Counter();remaining=dist=0
    for arms in results.values():
        a=arms[mode];w.update(a['edits']);c.update(a['characters']);remaining+=a['remaining_substitution_errors'];dist+=a['normalized_distance_after']
    summary[mode]=dict(edits=w,characters=c,remaining_substitution_errors=remaining,normalized_distance_after=dist)
save('summary.json',summary)
before=json.loads((E/'config/before.json').read_text('utf8'))
for p,h in before.items():
    if p.startswith(('data','asr')):assert hashlib.sha256((R/p).read_bytes()).hexdigest()==h,p
print(summary,flush=True)
