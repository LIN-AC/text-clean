"""Explain evidence/data gaps from the completed run, without changing decisions."""
import collections,csv,json,pathlib
R=pathlib.Path(__file__).resolve().parents[3];O=R/'experiments/E035/results'
model=json.loads((R/'build/e035_package/model.json').read_text('utf8'));v=set(model['vocab'])
with open(R/'data/correction/candidates.tsv',encoding='utf8') as f:
    targets={r['canonical'] for r in csv.DictReader((s for s in f if not s.startswith('#')),delimiter='\t') if r['status']=='1'}
competitors=json.loads((R/'build/e035_package/competitors.json').read_text('utf8'))
words={e['word'] for e in competitors['entries']}
coverage=dict(vocab_size=len(v),targets=len(targets),targets_in_competitors=len(targets&words),
              targets_all_characters_known=sum(set(t)<=v for t in targets),
              missing_target_readings=sorted(targets-words),discount_fallback_orders=model['discount_fallback_orders'])
(O/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf8')
counts=collections.Counter();chars=collections.Counter()
for p in O.glob('*.trace.json'):
    r=json.loads(p.read_text('utf8'))
    for w in r['windows']:
        counts['windows']+=1
        counts['no_retrieved_documents']+=not bool(w['docs'])
        counts['empty_H']+=not bool(w['H'])
        counts['source_has_unknown_character']+=not set(w['source'])<=v
        counts['some_target_has_unknown_character']+=any(not set(t)<=v for t in w['targets'])
        counts['no_executable_target_in_H']+=not any(h['executable'] for h in w['H'])
        counts[w['reason']]+=1
        for t in w['targets']:
            chars.update(set(t)-v)
    counts['applied_edits']+=len(r['edits'])
results=json.loads((O/'results.json').read_text('utf8'))
times={k:sum(x[k] for x in results.values()) for k in ['seconds','ngram_seconds','v1_seconds']}
report=dict(counts=counts,missing_target_character_occurrences=chars,times=times,
            note='Window counts overlap; not independent errors or mutually exclusive causes.')
(O/'diagnostics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
