"""New interface contract. No corpus-derived candidates in baseline checks."""
import pathlib,subprocess,sys,csv
root=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tools'))
from bili2md_text_clean import clean_subtitles
exe=sys.argv[1]
def run(*args,text=''):
    return subprocess.run([exe,*args],input=text.encode(),capture_output=True)
audit=run('--check-data')
assert audit.returncode==0,audit.stderr.decode()
with (root/'data/correction/candidates.tsv').open(encoding='utf8') as f:
    rows=list(csv.DictReader((l for l in f if not l.startswith('#')),delimiter='\t'))
enabled=[r for r in rows if r['status']=='1']
assert ('targets='+str(len({r['canonical'] for r in enabled}))).encode() in audit.stdout
assert ('enabled_rows='+str(len(enabled))).encode() in audit.stdout
assert b'domain_counts_loaded=0' in audit.stdout
baseline=run('--no-candidates','--check-data')
assert baseline.returncode==0 and b'targets=0' in baseline.stdout
body='这个颜色要略微深一点\n我买了微星主板\n他她它0123456789，2.9克\n'
assert clean_subtitles(exe,'微信','微信教程',body,extra_args=['--no-candidates'])==body
unsupported=run(text=body)
assert unsupported.returncode==0,unsupported.stderr.decode() # new Zipf default now runs
wrong_unit=run('--word-freq',str(root/'data/frequency/word_freq.tsv'),text=body)
assert wrong_unit.returncode==2
assert run('--no-candidates','--description-file','missing-title-file',text=body).returncode==2
print('New TSV audit, no-candidate adapter, metadata, missing file and frequency-unit rejection: PASS')
