"""V2 research: bounded N-gram paths + native retrieval propose 2-4 character edits.

No answer-key candidate table or static frequency table is consumed. The existing
G+D/KEEP formula is reused unchanged. Uncalibrated output remains KEEP unless
--research is explicit. Python still owns LM/scoring; retrieval owns no decision.
"""
import argparse
import bisect
import collections
import csv
import functools
import json
import math
import pathlib
import re

from rag_clean import Model, BOS, affected_scores, local_context, posterior, sha
from native_retrieval import NativeRetriever, domain_counts


def table(path):
    with open(path, encoding='utf8') as f:
        return list(csv.DictReader((line for line in f if not line.startswith('#')), delimiter='\t'))


class Proposer:
    def __init__(self, model, readings, beam=8):
        if not 1 <= beam <= 64:
            raise ValueError('beam must be 1-64')
        self.model, self.beam = model, beam
        # No word-frequency / answer-key table. Unknown tones never gain permission.
        self.readings = {c: set(r for r in rs if r and r[-1] in '12345') for c, rs in readings.items()}
        self.bases = {c: {r[:-1] for r in rs} for c, rs in self.readings.items()}
        self.by_base = collections.defaultdict(set)
        for c in model.vocab:
            if '\u4e00' <= c <= '\u9fff':
                for base in self.bases.get(c, ()):
                    self.by_base[base].add(c)
        # Sorted prefix index references existing strings, rather than duplicating a trie.
        self.keys = {n: sorted(model.c[n]) for n in (2, 3, 4)}

    @functools.lru_cache(maxsize=20000)
    def successors(self, history):
        out = set()
        for length in range(min(3, len(history)), 0, -1):
            h = history[-length:]
            keys = self.keys[length + 1]
            begin = bisect.bisect_left(keys, h)
            end = bisect.bisect_left(keys, h + '\U0010ffff')
            out.update(k[-1] for k in keys[begin:end])
        return frozenset(out)

    @functools.lru_cache(maxsize=20000)
    def pool(self, char):
        return frozenset(c for base in self.bases.get(char, ()) for c in self.by_base[base])

    def category(self, source, target):
        if len(source) != len(target) or any(c not in self.model.vocab for c in source + target):
            return None
        tone = False
        for a, b in zip(source, target):
            if a == b:
                continue
            if not self.bases.get(a, set()) & self.bases.get(b, set()):
                return None
            tone |= not bool(self.readings.get(a, set()) & self.readings.get(b, set()))
        return 'tone' if tone else 'same'

    def generate(self, left, source, bos):
        """One traversal produces 2/3/4-char proposals; original prefixes survive pruning."""
        if any(c not in self.model.vocab for c in source):
            return {}
        start = ((BOS * 3 if bos else '') + self.model.encode(left))[-3:]
        beam = [('', 0.)]
        result = {}
        for depth, original in enumerate(source[:4], 1):
            paths = {}
            for prefix, score in beam:
                history = (start + prefix)[-3:]
                pool = self.pool(original)
                next_chars = self.successors(history) & pool if history else pool
                # KEEP's prefix is always reachable, even with unseen histories.
                for c in next_chars | {original}:
                    word = prefix + c
                    paths[word] = score + math.log(self.model.probability(history, c))
            beam = sorted(paths.items(), key=lambda x: (-x[1], x[0]))[:self.beam]
            unchanged = source[:depth]
            if unchanged not in dict(beam):
                beam.append((unchanged, paths[unchanged]))
            if depth >= 2:
                result[depth] = {w: {'ngram'} for w, _ in beam if w != unchanged and self.category(unchanged, w)}
        return result

    def retrieved_index(self, evidence):
        """Index observed corpus strings by first-character sound; no invented joins."""
        result = collections.defaultdict(set)
        for segment in evidence['segments']:
            text = segment['left_context'] + segment['text']
            for run in re.findall(r'[\u4e00-\u9fff]+', text):
                for i in range(len(run)):
                    for length in (2, 3, 4):
                        word = run[i:i+length]
                        if len(word) != length or any(c not in self.model.vocab for c in word):
                            continue
                        for base in self.bases.get(word[0], ()):
                            result[length, base].add(word)
        return result


def resolve(text, proposals):
    """Compatible overlapping edits agree per position; conflicting components KEEP."""
    proposals = sorted(proposals, key=lambda p: (p['begin'], p['end'], p['target']))
    accepted, conflicts = [], set()
    i = 0
    while i < len(proposals):
        end, j = proposals[i]['end'], i + 1
        while j < len(proposals) and proposals[j]['begin'] < end:
            end = max(end, proposals[j]['end']); j += 1
        assignments = collections.defaultdict(set)
        # Include unchanged positions too: one window's KEEP cannot be silently
        # changed by another overlapping window evaluated on the original text.
        for p in proposals[i:j]:
            for pos, c in enumerate(p['target'], p['begin']):
                assignments[pos].add(c)
        if any(len(cs) != 1 for cs in assignments.values()):
            conflicts.update((p['begin'], p['end']) for p in proposals[i:j])
        else:
            accepted.extend(proposals[i:j])
        i = j
    output = list(text)
    for p in accepted:
        output[p['begin']:p['end']] = p['target']
    return ''.join(output), accepted, conflicts


class ProposalCleaner:
    def __init__(self, package, native, data='data', research=False, retrieval=True, beam=8,
                 rag_candidates=True, evidence_scoring=False):
        root = pathlib.Path(package)
        manifest = json.loads((root / 'manifest.json').read_text('utf8'))
        if manifest['format'] != 'tc-evidence-package-2':
            raise ValueError('proposal path requires boundary-aware package v2')
        # Candidate table/old executable are deliberately not dependencies here.
        for name in ('model.json', 'evidence.sqlite', 'parameters.json'):
            if sha(root / name) != manifest['files'][name]:
                raise ValueError('package hash mismatch: ' + name)
        self.model = Model(json.loads((root / 'model.json').read_text('utf8')))
        self.model.validate()
        self.params = json.loads((root / 'parameters.json').read_text('utf8'))
        if not 0 < self.params['alpha'] < .5 or not self.params['kappa'] > 0 or not self.params['rho'] >= 0:
            raise ValueError('invalid risk parameters')
        if any(not math.isfinite(v) for v in (self.params[k] for k in ('alpha', 'kappa', 'rho'))):
            raise ValueError('non-finite parameter')
        for a, beta in self.params['classes'].values():
            if not math.isfinite(a) or not 0 < beta <= 1:
                raise ValueError('invalid class parameter')
        data = pathlib.Path(data)
        readings = {r['char']: r['readings'].split('|') for r in table(data / 'pronunciation/pronunciation_char.tsv')}
        self.proposer = Proposer(self.model, readings, beam)
        self.lock_words = [r['word'] for r in table(data / 'ac/ac_lock.tsv') if r['word']]
        self.store = NativeRetriever(native, root / 'evidence.sqlite') if retrieval else None
        self.research, self.rag_candidates, self.evidence_scoring = research, rag_candidates, evidence_scoring

    def close(self):
        if self.store:
            self.store.close()

    def clean(self, text, title='', description=''):
        locked = set()
        for word in self.lock_words:
            start = text.find(word)
            while start >= 0:
                locked.update(range(start, start + len(word)))
                start = text.find(word, start + 1)
        logs, proposals, retrieval_logs = [], [], []
        for match in re.finditer(r'[^\r\n。？！?!]+', text):
            start, stop = match.span()
            windows = {}
            # Context ranges follow observed cue/punctuation boundaries; windows
            # themselves never cross punctuation, gaps, or AC locks.
            for run in re.finditer(r'[\u4e00-\u9fff]{2,}', match.group()):
                begin, end = start + run.start(), start + run.end()
                for b in range(begin, end - 1):
                    max_end = min(b + 4, end)
                    while max_end > b and any(i in locked for i in range(b, max_end)):
                        max_end -= 1
                    if max_end - b < 2:
                        continue
                    l, _, bos, _ = local_context(text, b, b + 2)
                    generated = self.proposer.generate(l[-3:], text[b:max_end], bos)
                    for length in range(2, max_end - b + 1):
                        e = b + length
                        left, right, bos, eos = local_context(text, b, e)
                        windows[b, e] = dict(targets=generated.get(length, {}),
                            left=left[-3:], right=right[:3], bos=bos, eos=eos)
            if not windows:
                continue
            # At most four paired seeds per cue, selected without truth. KEEP and
            # its alternative have identical query budget; all windows share union.
            seeds = []
            for (b, e), w in windows.items():
                og, _ = affected_scores(self.model, (), self.params['kappa'], w['left'], text[b:e], w['right'], w['bos'], w['eos'])
                for target in w['targets']:
                    g, _ = affected_scores(self.model, (), self.params['kappa'], w['left'], target, w['right'], w['bos'], w['eos'])
                    seeds.append((g-og, b, e, target))
            seeds.sort(key=lambda s: (-s[0], s[1], s[2], s[3]))
            alternatives, used = set(), set()
            for _, b, e, target in seeds:
                if (b, e) in used:
                    continue
                used.add((b, e)); alternatives.update((text[b:e], target))
                if len(used) == 4:
                    break
            context = match.group()
            for word in sorted(alternatives, key=lambda w: (-len(w), w)):
                context = context.replace(word, ' ')
            context += ' ' + title + ' ' + description
            evidence = self.store.retrieve(context, alternatives) if self.store else dict(segments=[], evidence_chars=0)
            domain = domain_counts(self.model, evidence) if self.evidence_scoring else ()
            index = self.proposer.retrieved_index(evidence) if self.rag_candidates else {}
            retrieval_logs.append(dict(begin=start, end=stop, alternatives=sorted(alternatives),
                evidence_chars=evidence['evidence_chars'], segments=[s['id'] for s in evidence['segments']],
                docs=sorted({s['cluster_id'] for s in evidence['segments']})))
            for (b, e), w in windows.items():
                source = text[b:e]
                targets = w['targets']
                for base in self.proposer.bases.get(source[0], ()):
                    for target in index.get((e-b, base), ()):
                        if target != source and self.proposer.category(source, target):
                            targets.setdefault(target, set()).add('rag')
                if not targets:
                    continue
                og, om = affected_scores(self.model, domain, self.params['kappa'], w['left'], source, w['right'], w['bos'], w['eos'])
                scored = []
                for target, origins in sorted(targets.items()):
                    category = self.proposer.category(source, target)
                    if category not in self.params['classes']:
                        continue
                    g, m = affected_scores(self.model, domain, self.params['kappa'], w['left'], target, w['right'], w['bos'], w['eos'])
                    G, D = g-og, (m-om)-(g-og)
                    a, beta = self.params['classes'][category]
                    scored.append(dict(word=target, cls=category, G=G, D=D, S=a+beta*G+D, mix=m, origins=sorted(origins)))
                if not scored:
                    continue
                scored.sort(key=lambda s: (-s['mix'], s['word']))
                probs = posterior([s['S'] for s in scored], self.params['rho'])
                for s, p in zip(scored, probs[1:]):
                    s['p'] = p
                H = scored[:self.params['top_h']]
                best = max(H, key=lambda s: s['p'])
                reason = 'evidence_insufficient' if self.research else 'uncalibrated'
                # Old calibration does not cover this new candidate selector.
                if self.research and best['p'] >= 1-self.params['alpha']:
                    reason = 'proposed'
                    proposals.append(dict(begin=b, end=e, target=best['word'], p=best['p']))
                logs.append(dict(begin=b, end=e, source=source, H=H, targets=sorted(targets),
                    pool_size=len(scored), keep=probs[0], reason=reason,
                    other=sum(probs[len(H)+1:]), context={k: w[k] for k in ('left', 'right', 'bos', 'eos')}))
        output, accepted, conflicts = resolve(text, proposals)
        for log in logs:
            if log['reason'] == 'proposed':
                log['reason'] = 'overlap_abstention' if (log['begin'], log['end']) in conflicts else 'applied'
        return dict(text=output, edits=accepted, windows=logs, retrieval=retrieval_logs,
                    research=self.research, calibrated=False, domain_evidence=self.evidence_scoring,
                    proposal_policy=dict(beam=self.proposer.beam, lengths=[2,3,4],
                        phonetic='same_base', native_segment_limit=300, evidence_chars=8192))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True); ap.add_argument('--native', required=True)
    ap.add_argument('--data', default='data'); ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True); ap.add_argument('--research', action='store_true')
    ap.add_argument('--no-retrieval', action='store_true'); ap.add_argument('--beam', type=int, default=8)
    ap.add_argument('--domain-evidence', action='store_true',
                    help='research ablation: also use retrieved counts in D; default retrieval only proposes')
    ap.add_argument('--title', default=''); ap.add_argument('--description', default='')
    a = ap.parse_args()
    if a.domain_evidence and (not a.research or a.no_retrieval):
        ap.error('--domain-evidence requires --research and retrieval')
    cleaner = ProposalCleaner(a.package, a.native, a.data, a.research, not a.no_retrieval, a.beam,
                              evidence_scoring=a.domain_evidence)
    try:
        result = cleaner.clean(pathlib.Path(a.input).read_text('utf8'), a.title, a.description)
        pathlib.Path(a.output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf8')
    finally:
        cleaner.close()


if __name__ == '__main__':
    main()
