"""Frozen E024 character metrics, seven open-book cues; no truth enters cleaner."""
import argparse
import collections
import importlib.util
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from proposal_clean import ProposalCleaner
from rag_clean import sha

spec = importlib.util.spec_from_file_location('e044', ROOT / 'experiments/E044/scripts/run_arms.py')
metrics = importlib.util.module_from_spec(spec); spec.loader.exec_module(metrics)


class Tape:
    def __init__(self, path, backend=None):
        self.backend = backend
        self.f = open(path, 'w' if backend else 'r', encoding='utf8')

    def retrieve(self, context, alternatives):
        request = [context, sorted(alternatives)]
        if self.backend:
            result = self.backend.retrieve(context, alternatives)
            self.f.write(json.dumps([request, result], ensure_ascii=False) + '\n')
        else:
            expected, result = json.loads(next(self.f))
            assert request == expected, 'replay request differs'
        return result

    def close(self):
        self.f.close()


def coverage(body, rows, windows):
    labels, offset = {}, 0
    for r in rows:
        lab, _ = metrics.align(r['text'], r['gt'])
        labels.update({offset+i:v for i,v in lab.items()})
        offset += len(r['text'])+1
    covered, pool = set(), 0
    for w in windows:
        b, e = w['begin'], w['end']; pool += w['pool_size']
        if not all(i in labels for i in range(b,e)):
            continue
        true = ''.join(labels[i] for i in range(b,e))
        if true in w['targets']:
            covered.update(i for i in range(b,e) if body[i] != labels[i])
    return dict(candidate_reachable_errors=len(covered), candidate_count=pool)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', default='build/e044_full')
    ap.add_argument('--native', default='build/astra_v2/tc_retrieve.exe')
    ap.add_argument('--videos', default='')
    ap.add_argument('--arms', default='ngram,rag,rag_proposals')
    ap.add_argument('--tag', default='seven')
    ap.add_argument('--implementation', default='tools/proposal_clean.py')
    a = ap.parse_args()
    implementation=ROOT/a.implementation
    module_spec=importlib.util.spec_from_file_location('measured_proposals',implementation)
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    out = ROOT / 'experiments/E053/results'; out.mkdir(parents=True, exist_ok=True)
    artifacts = ROOT / 'build/e053'; artifacts.mkdir(parents=True, exist_ok=True)
    inputs = list((ROOT / 'asr').glob('*.gt.jsonl'))
    files = [f for f in sorted(inputs) if not a.videos or f.stem in a.videos.split(',')]
    manifest = dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip(),
        command=sys.argv, data={str(f.relative_to(ROOT)):sha(f) for f in inputs},
        source={str(f):sha(ROOT/f) for f in [pathlib.Path('data/pronunciation/pronunciation_char.tsv'),
            pathlib.Path('data/ac/ac_lock.tsv'),pathlib.Path('data/correction/candidates.tsv'),
            pathlib.Path('tools/proposal_clean.py'),pathlib.Path('tools/native_retrieval.py'),
            pathlib.Path('tools/rag_clean.py'),pathlib.Path('src/retrieval.cpp'),pathlib.Path('src/retrieval_main.cpp')]},
        package=json.loads((ROOT/a.package/'manifest.json').read_text('utf8')),
        native_sha=sha(ROOT/a.native),implementation=dict(path=str(implementation.relative_to(ROOT)),sha256=sha(implementation)),results={})
    t = time.perf_counter()
    cleaner = module.ProposalCleaner(ROOT/a.package, ROOT/a.native, ROOT/'data', research=True)
    native = cleaner.store
    manifest['load_seconds'] = time.perf_counter()-t
    manifest['parameters'] = cleaner.params
    print('loaded', round(manifest['load_seconds'],2), flush=True)
    try:
        for f in files:
            rows=[json.loads(s) for s in f.read_text('utf8').splitlines() if s.strip()]
            rows=[r for r in rows if not r.get('discard')]
            body='\n'.join(r['text'] for r in rows)+'\n'
            item={}
            for arm in a.arms.split(','):
                tape=None
                if arm=='ngram':
                    cleaner.store=None; cleaner.rag_candidates=False; cleaner.evidence_scoring=False
                elif arm=='rag':
                    tape=Tape(artifacts/(f.stem+'.retrieval.jsonl'),native)
                    cleaner.store=tape; cleaner.rag_candidates=True; cleaner.evidence_scoring=True
                elif arm=='rag_proposals':
                    tape=Tape(artifacts/(f.stem+'.retrieval.jsonl'))
                    cleaner.store=tape; cleaner.rag_candidates=True; cleaner.evidence_scoring=False
                else:
                    raise ValueError(arm)
                t=time.perf_counter(); result=cleaner.clean(body); elapsed=time.perf_counter()-t
                if tape:
                    if not tape.backend:
                        assert tape.f.read()=='', 'unconsumed replay evidence'
                    tape.close()
                s=metrics.score(body,result['text'],rows)
                s.update(coverage(body,rows,result['windows']))
                s.update(seconds=elapsed, edits=len(result['edits']), windows=len(result['windows']),
                    rag_only_candidates=sum(h['origins']==['rag'] for w in result['windows'] for h in w['H']),
                    nonzero_D=sum(abs(h['D'])>1e-9 for w in result['windows'] for h in w['H']))
                (artifacts/(a.tag+'.'+f.stem+'.'+arm+'.json')).write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
                item[arm]=s
                manifest['results'][f.stem]=item
                (out/(a.tag+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
                print(f.stem,arm,s,flush=True)
                del result
        assert all(sha(ROOT/name)==digest for name,digest in manifest['data'].items())
    finally:
        native.close()


if __name__=='__main__':
    main()
