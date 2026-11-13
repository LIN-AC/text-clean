"""Small fixed cross-domain checks; no fitting and no new manual labels."""
import collections
import json
import pathlib
import sys
import time

ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'experiments/E044/scripts'))
from proposal_clean import ProposalCleaner
from rag_clean import sha
from run_arms import score


def main():
    paths=[ROOT/'datasets/CTCDataset'/name for name in
           ['sighan/sighan14_test.jsonl','cscd-ns/test.jsonl','lemon/new.jsonl']]
    groups={}
    for p in paths:
        rows=[json.loads(s) for s in p.read_text('utf8').splitlines() if s.strip()][:30]
        groups[str(p.relative_to(ROOT))]=[dict(text=r['source'],gt=r['target']) for r in rows]
    result=dict(data={str(p.relative_to(ROOT)):sha(p) for p in paths},results={})
    cleaner=ProposalCleaner(ROOT/'build/e044_full',ROOT/'build/astra_v2/tc_retrieve.exe',ROOT/'data',research=True)
    native=cleaner.store
    try:
        for name,rows in groups.items():
            body='\n'.join(r['text'] for r in rows)+'\n'
            item={}
            for arm in ('ngram','rag'):
                cleaner.store=native if arm=='rag' else None
                cleaner.rag_candidates=cleaner.evidence_scoring=arm=='rag'
                t=time.perf_counter();got=cleaner.clean(body)
                item[arm]=dict(score=score(body,got['text'],rows),seconds=time.perf_counter()-t,
                               edits=len(got['edits']))
            result['results'][name]=item
            print(name,item,flush=True)
        # Previously confirmed correct snippets: targeted guards, not a new ASR truth set.
        negative='这个颜色要略微深一点。\n谈话核实。\n谈话人员。\n微星电脑使用英伟达显卡。\n'
        cleaner.store=native;cleaner.rag_candidates=cleaner.evidence_scoring=True
        got=cleaner.clean(negative)
        result['known_negative']=dict(source=negative,output=got['text'],
                                    changed_chars=sum(a!=b for a,b in zip(negative,got['text'])))
        # Check the existing real transcript only for the confirmed phrase; all
        # other edits stay unlabeled (this file has no approved full truth here).
        path=ROOT/'datasets/whisper_txt/BV1ghec66Eau.txt'
        body=path.read_text('utf8');got=cleaner.clean(body)
        phrase='这个颜色要略微深一点';pos=body.index(phrase)
        result['real_asr']=dict(path=str(path.relative_to(ROOT)),sha256=sha(path),
            known_phrase=phrase,phrase_output=got['text'][pos:pos+len(phrase)],
            total_changed_chars_unlabeled=sum(a!=b for a,b in zip(body,got['text'])))
        cleaner.research=False
        protected=cleaner.clean(negative)
        assert protected['text']==negative and not protected['edits']
        result['default_keep']=True
    finally:
        native.close()
    (ROOT/'experiments/E053/results/supplement.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
