"""Reproducible same-corpus A/B probe.
Usage: python tools/refactor_benchmark.py EXE RESULT.json [--context]
Recall counts target spans, including configured masking actions; it is not
sentence accuracy. Context mode is deliberately synthetic, not ground truth.
"""
import pathlib, subprocess, time, statistics, json, sys, hashlib, os
os.chdir(pathlib.Path(__file__).resolve().parents[1])
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0,str(pathlib.Path('tools').resolve()))
import v2error_report as corpus
ROOT=pathlib.Path.cwd()
exe=sys.argv[1]; dest=pathlib.Path(sys.argv[2])
context_flags = ['--title', '微信华为转账', '--description', '微信华为转账'] if '--context' in sys.argv else []
def run(text,flags=()):
 p=subprocess.run([exe,*context_flags,*flags],input=text.encode(),capture_output=True,check=True)
 return p.stdout.decode().rstrip('\r\n'),p.stderr.decode()
def stats(path):
 s=path.read_bytes().decode(); out,err=run(s,['-v']); hits=corpus.HIT_RE.findall(err)
 return dict(file=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),chars=len(s.rstrip('\r\n')),changed_chars=sum(a!=b for a,b in zip(s.rstrip('\r\n'),out))+abs(len(s.rstrip('\r\n'))-len(out)),rewrites=[dict(before=h[4],after=h[5],context=s[max(0,int(h[2])-16):int(h[3])+16]) for h in hits if h[4]!=h[5]])
res={'correct':[stats(p) for p in sorted(pathlib.Path('temp_txt').glob('*.txt'))], 'asr':[stats(pathlib.Path('whisper_txt')/n) for n in ['BV162AEzyEiF.txt','BV174421f7Th.txt']]}
res['recall']=[]
for c in corpus.CASES:
 out,err=run(c['text'],['-v']); hits=corpus.HIT_RE.findall(err)
 ok=any(int(h[2])==c['span'][0] and int(h[3])==c['span'][1] and (h[5]==c['canonical'] or (c['canonical'] in corpus.MASK_CANONICALS and h[12]=='mask' and h[5]=='*'*len(c['surface']))) for h in hits)
 res['recall'].append(dict(surface=c['surface'],coverable=c['coverable'],ok=ok,output=out if not ok and len(out)<150 else None))
large='\n'.join(p.read_bytes().decode() for p in sorted(pathlib.Path('temp_txt').glob('*.txt')))*40
for label,s,n in [('startup','',15),('large',large,5)]:
 times=[]
 for _ in range(n):
  t=time.perf_counter();run(s);times.append(time.perf_counter()-t)
 res[label]={'median_ms':statistics.median(times)*1000,'MB_s':len(s.encode())/1e6/statistics.median(times),'bytes':len(s.encode()),'samples':times}
res['executable_sha256']=hashlib.sha256(pathlib.Path(exe).read_bytes()).hexdigest()
res['context_flags']=context_flags
res['data_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in pathlib.Path('data').glob('*.txt') if p.name in ['word_freq.txt','lexicon.txt','word.txt','pinyin_dict.txt','dict.txt']}
dest.parent.mkdir(parents=True,exist_ok=True)
dest.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in res.items() if k not in ['recall','asr']},ensure_ascii=False))
print('recall',sum(c['ok'] for c in res['recall']),len(res['recall']))
