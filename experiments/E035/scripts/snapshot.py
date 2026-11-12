"""Bind final implementation/test artifacts without rewriting the run manifest."""
import hashlib,json,pathlib,subprocess
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E035/results'
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
m=json.loads((O/'manifest.json').read_text('utf8'))
for p,h in {**m['inputs'],**m['sources']}.items():assert sha(R/p)==h,p
paths=['CMakeLists.txt','include/text_clean/text_cleaner.h','src/main.cpp','src/text_cleaner.cpp',
       'tests/test_zipf_scoring.cpp','tests/test_rag_clean.py','tools/rag_clean.py','tools/prepare_rag_package.py',
       'build/e025/text_clean.exe','build/e035/text_clean.exe','build/e035/tests_final.txt',
       'build/e035_package/manifest.json','docs/RAG_DATA_CONTRACT.md','README.md','experiments/E035/README.md']
paths+=[str(p.relative_to(R)) for p in (R/'experiments/E035/scripts').glob('*.py')]
paths+=[str(p.relative_to(R)) for p in O.glob('*.json') if p.name!='artifact_manifest.json']
report=dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            files={p:sha(R/p) for p in paths},all_run_inputs_and_sources_unchanged=True,
            note='Final supplementary snapshot; manifest.json remains the original run record.')
(O/'artifact_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('Final snapshot saved; all formal data, truth and executed sources unchanged.')
