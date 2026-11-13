"""Thin transport to tc_retrieve; all search and evidence selection runs in C++."""
import collections
import pathlib
import subprocess
from rag_clean import transition_events


class NativeRetriever:
    def __init__(self, executable, database):
        self.process = subprocess.Popen([str(pathlib.Path(executable).resolve()),
                                         str(pathlib.Path(database).resolve())],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='ascii')

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()

    def retrieve(self, context, alternatives=(), limit=300, budget=8192, legacy=False):
        if not context:
            context = ' '  # Empty hex is a valid field, but avoid a trailing empty field.
        fields = ['L' if legacy else 'Q', str(limit), str(budget), context.encode().hex()]
        fields += [w.encode().hex() for w in sorted(set(alternatives))]
        self.process.stdin.write('\t'.join(fields) + '\n')
        self.process.stdin.flush()
        result = dict(segments=[], evidence_chars=0, budget_cut=False, char_budget=budget)
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError('native retriever stopped: ' + self.process.stderr.read())
            f = line.rstrip('\r\n').split('\t')
            if f[0] == 'X':
                raise ValueError(bytes.fromhex(f[1]).decode())
            if f[0] == 'E':
                return result
            if f[0] == 'B':
                result.update(evidence_chars=int(f[1]), budget_cut=bool(int(f[2])))
            elif f[0] == 'S':
                decode = lambda i: bytes.fromhex(f[i]).decode('utf8')
                result['segments'].append(dict(id=int(f[1]), cluster_id=decode(2), text=decode(3),
                    off=int(f[4]), left_context=decode(5), bos=bool(int(f[6])), eos=bool(int(f[7])),
                    left_class=decode(8), right_class=decode(9), source_family=decode(10),
                    source_doc_id=decode(11)))
            else:
                raise ValueError('invalid native response')


def domain_counts(model, evidence):
    """Document-clipped probability inputs, separate from retrieval ranking."""
    by_doc = collections.defaultdict(set)
    for s in evidence['segments']:
        by_doc[s['cluster_id']].update(transition_events(model, s['text'], s['left_context'], s['bos'], s['eos']))
    counts = collections.Counter()
    for events in by_doc.values():
        counts.update(events)
    totals = collections.Counter()
    for (history, _), count in counts.items():
        totals[history] += count
    return counts, totals
