"""No-candidate preservation baseline and same-input timing; not a recall study."""
import hashlib,json,pathlib,statistics,subprocess,time,os
R=pathlib.Path(__file__).resolve().parents[3];E=R/'experiments/E021';O=E/'results'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,data):(O/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
old=R/'build/baseline/text_clean.exe';new=R/'build/current/text_clean.exe'
empty=E/'config/empty.lexicon';empty.write_text('# Empty candidate baseline\n',encoding='utf8')
old_args=['--lexicon',str(empty),'--pinyin-dict',str(R/'data/old/pinyin_dict.txt'),'--word-file',str(R/'data/raw/AC_word.txt'),'--word-freq',str(R/'data/old/word_freq.txt'),'--char-freq',str(R/'data/old/dict.txt'),'--vocabulary',str(R/'data/old/dict.txt')]
def run(exe,args,body):
    start=time.perf_counter();p=subprocess.run([str(exe),*args],input=body,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=R,check=True)
    return p.stdout,time.perf_counter()-start,p.stderr
corpus=[];bodies=[]
for path in sorted((R/'asr').glob('*.gt.jsonl')):
    rows=[json.loads(l) for l in path.read_text('utf8').splitlines() if l.strip()]
    assert not any(r.get('pending') for r in rows),path
    kept=[r for r in rows if not r.get('discard')]
    body=('\n'.join(r['text'] for r in kept)+'\n').encode()
    expected=body
    timings={}
    for name,exe,args in [('before',old,old_args),('after',new,['--no-candidates'])]:
        output,elapsed,_=run(exe,args,body);assert output==expected,(path,name)
        timings[name]=elapsed
        (O/f'{path.stem}.{name}.output').write_bytes(output)
    corpus.append(dict(video=path.stem,truth_sha256=sha(path),kept_cues=len(kept),discard=[r['index'] for r in rows if r.get('discard')],input_characters=sum(len(r['text']) for r in kept),output_equals_input=True,corrected_edits=0,false_edits=0,remaining_errors='all original errors retained; no recall claim',seconds=timings))
    bodies.append(body)
    print(path.stem,'unchanged in both',flush=True)
save('no_candidate_baseline.json',corpus)
unit=b''.join(bodies);large=unit*(3*1024*1024//len(unit)+1)
perf={}
for name,exe,args in [('before',old,old_args),('after',new,['--no-candidates'])]:
    starts=[];large_runs=[]
    for i in range(5):
        output,elapsed,_=run(exe,args,b'');starts.append(elapsed)
    for i in range(3):
        output,elapsed,_=run(exe,args,large);assert output==large;large_runs.append(elapsed)
    perf[name]=dict(startup_seconds=starts,median_startup_seconds=statistics.median(starts),large_bytes=len(large),large_seconds=large_runs,median_end_to_end_MB_s=len(large)/1e6/statistics.median(large_runs))
save('performance.json',perf)
# Enabled candidate integration is a mechanical replay only: its candidates
# contain these videos' human labels, so it is NOT an independent accuracy test.
cache=O/'integration_index.bin'
cache.write_bytes(b'cold-cache probe') # disposable experiment artifact, force rebuild
args=['--word-freq',str(R/'data/old/word_freq.txt'),'--char-freq',str(R/'data/old/dict.txt')]
sample=bodies[0]
plain,t0,_=run(new,args+['--no-index-cache'],sample)
cold,t1,_=run(new,args+['--index-cache',str(cache)],sample)
warm,t2,_=run(new,args+['--index-cache',str(cache)],sample)
assert plain==cold==warm
save('cache_integration.json',dict(output_identical=True,no_cache_seconds=t0,first_cache_seconds=t1,warm_cache_seconds=t2,cache_bytes=cache.stat().st_size,quality_scored=False))
before=json.loads((E/'config/before.json').read_text('utf8'))['hashes']
changed=[]
for name,h in before.items():
    if name.startswith(('data','asr')) and sha(R/name)!=h:changed.append(name)
assert changed==['data\\correction\\candidates.tsv'] or changed==['data/correction/candidates.tsv'],changed
save('manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),binaries={str(p.relative_to(R)):sha(p) for p in [old,new]},data={str(p.relative_to(R)):sha(p) for p in (R/'data').rglob('*.tsv')},approved_data_change=changed,truth_unchanged=True,parameters=dict(lambda_value=.65,mu=.7,max_distance=2,domain_counts=False,candidates_in_baseline=False),scoring_formula_changed=False))
print('baseline, cache parity and protected input checks passed',flush=True)
