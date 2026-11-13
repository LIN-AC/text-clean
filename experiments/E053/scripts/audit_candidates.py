"""Diagnose selected edits; this is NOT a replay of a changed decision policy."""
import codecs
import collections
import json
import pathlib
import re
import sys

ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'experiments/E024/scripts'))
from proposal_clean import table
from align_lib import align
from rag_clean import sha


def main():
    chars={r['char']:r['readings'].split('|') for r in table(ROOT/'data/pronunciation/pronunciation_char.tsv')}
    words=set()
    # Edit lists are sufficient; scoring is not rerun or approximated here.
    for path in (ROOT/'build/e053').glob('seven.*.ngram.json'):
        d=json.loads(path.read_text('utf8'));words.update(e['target'] for e in d['edits']);del d
    seen=set();decoder=codecs.getincrementaldecoder('utf8')();tail=''
    with open(ROOT/'build/e044_full/model.json','rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            s=tail+decoder.decode(block)
            seen.update(w for w in re.findall(r'"([\u4e00-\u9fff]{2,4})"',s) if w in words)
            tail=s[-64:]
    records={}
    for path in sorted((ROOT/'build/e053').glob('seven.*.ngram.json')):
        video=path.name.removeprefix('seven.').removesuffix('.ngram.json')
        rows=[json.loads(s) for s in (ROOT/'asr'/(video+'.jsonl')).read_text('utf8').splitlines() if s.strip()]
        rows=[r for r in rows if not r.get('discard')]
        body='\n'.join(r['text'] for r in rows)+'\n';labels={};offset=0
        for r in rows:
            lab,_=align(r['text'],r['gt']);labels.update({offset+i:v for i,v in lab.items()});offset+=len(r['text'])+1
        d=json.loads(path.read_text('utf8'));unsupported=set();secondary=set();examples=[]
        for e in d['edits']:
            b,eend=e['begin'],e['end'];target=e['target'];source=body[b:eend]
            if target not in seen:
                unsupported.update(b+i for i,(a,c) in enumerate(zip(source,target)) if a!=c)
                if len(examples)<5:examples.append(dict(source=source,target=target,begin=b))
            for i,(a,c) in enumerate(zip(source,target),b):
                if a==c:continue
                ra,rc=chars.get(a,[]),chars.get(c,[])
                if ra and rc and ra[0].rstrip('012345')!=rc[0].rstrip('012345'):
                    secondary.add(i)
        def count(positions):
            c=collections.Counter(TP=0,FP=0,wrong=0)
            for i in positions:
                if i in labels:
                    c['TP' if d['text'][i]==labels[i] else 'FP' if body[i]==labels[i] else 'wrong']+=1
            return dict(c)
        records[video]=dict(involved_unobserved_string=count(unsupported),
                            differing_first_reading=count(secondary),examples=examples)
    result=dict(scope='selected-edit attribution only; cannot infer the result of removing candidates',
                model_sha=sha(ROOT/'build/e044_full/model.json'),records=records)
    (ROOT/'experiments/E053/results/candidate_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
