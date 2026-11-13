import collections
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from rag_clean import Model, EvidenceStore, sha
from native_retrieval import NativeRetriever, domain_counts
from proposal_clean import Proposer, ProposalCleaner, resolve

EXE = sys.argv.pop(1) if len(sys.argv) > 1 else 'build/astra_v2/tc_retrieve.exe'


def evidence_db(path, texts):
    db = sqlite3.connect(path)
    db.executescript("""create table meta(key,value);insert into meta values('format','tc-rag-2');
    create table documents(cluster_id primary key,source_family,source_doc_id);
    create table segments(id integer primary key,cluster_id,text,off,left_context,bos,eos,left_class,right_class);
    create table term_docs(term primary key,docs);
    create virtual table search using fts5(tokens);""")
    terms = collections.defaultdict(set)
    for i, (doc, text, prefix) in enumerate(texts):
        db.execute('insert or ignore into documents values(?,?,?)', (doc, '测试', doc))
        db.execute('insert into segments values(?,?,?,?,?,?,?,?,?)',
                   (i, doc, text, 3 if prefix else 0, prefix, not prefix, 1, '真实边界', '句末标点'))
        full = prefix + text
        ts = [full[j:j+2] for j in range(len(full)-1)]
        db.execute('insert into search(rowid,tokens) values(?,?)', (i, ' '.join(ts)))
        for term in ts:
            terms[term].add(doc)
    db.executemany('insert into term_docs values(?,?)', ((t, len(ds)) for t, ds in terms.items()))
    db.commit(); db.close()


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.model = Model.train(['我用微信支付'] * 20 + ['我用位信支付'] * 2 +
                                 ['微星电脑', '微星电脑', '卫星飞行', '卫星飞行', '孤'])
        self.path = self.root / 'evidence.sqlite'
        evidence_db(self.path, [('a', '我用微信支付', ''), ('a', '我用微信支付', ''),
                                ('b', '微星电脑', ''), ('c', '信支付', '我用微')])
        self.native = NativeRetriever(EXE, self.path)

    def tearDown(self):
        self.native.close(); self.tmp.cleanup()

    def test_legacy_parity_selection_counts_and_metadata(self):
        old = EvidenceStore(self.path, self.model)
        for query in ['微信', '支付 微星', '查无', '我用微信支付']:
            expected, docs = old.retrieve(query, 50)
            actual = self.native.retrieve(query, limit=50, legacy=True)
            self.assertEqual(domain_counts(self.model, actual), expected or ({}, {}))
            self.assertEqual(sorted({s['cluster_id'] for s in actual['segments']}), docs)
            self.assertEqual([s['id'] for s in actual['segments']], [s['id'] for s in old.last_retrieval['segments']])
            self.assertEqual(actual['evidence_chars'], old.last_retrieval['evidence_chars'])
        old.db.close()

    def test_doc_clipping(self):
        r = self.native.retrieve('微信', limit=50, legacy=True)
        counts, totals = domain_counts(self.model, r)
        self.assertEqual(counts['我用微', '信'], 2)  # two documents, not three segments
        self.assertEqual(totals['我用微'], sum(n for (h, _), n in counts.items() if h == '我用微'))

    def test_unknown_query_still_recovers_paired_alternatives(self):
        r = self.native.retrieve('不存在', ['微信', '微星'])
        found = ''.join(s['text'] for s in r['segments'])
        self.assertIn('微信', found); self.assertIn('微星', found)
        self.assertEqual(r, self.native.retrieve('不存在', ['微星', '微信', '微信']))

    def test_cut_has_no_eos(self):
        r = self.native.retrieve('微信', limit=50, budget=4, legacy=True)
        self.assertEqual(r['evidence_chars'], 4)
        self.assertTrue(r['budget_cut']); self.assertFalse(r['segments'][-1]['eos'])
        self.assertEqual(r['segments'][-1]['right_class'], '载荷截断')

    def test_bad_request_does_not_kill_worker(self):
        with self.assertRaises(ValueError):
            self.native.retrieve('微信', budget=10000)
        self.assertTrue(self.native.retrieve('微信')['segments'])

    def test_read_only(self):
        before = sha(self.path)
        self.native.retrieve('微信', ['微信', '微星'])
        self.assertEqual(before, sha(self.path))


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.model = Model.train(['我用微信支付'] * 20 + ['我用位信支付'] * 2 +
                                 ['微星电脑', '微星电脑', '卫星飞行', '卫星飞行', '孤'])
        self.chars = {'微':['wei1'], '位':['wei4'], '卫':['wei4'], '信':['xin4'], '星':['xing1'],
                      '我':['wo3'], '用':['yong4'], '支':['zhi1'], '付':['fu4'], '电':['dian4'], '脑':['nao3']}
        self.proposer = Proposer(self.model, self.chars)

    def test_ngram_proposes_without_answer_key(self):
        generated = self.proposer.generate('我用', '位信支付', True)
        self.assertIn('微信', generated[2])
        self.assertIn('微信支', generated[3]); self.assertIn('微信支付', generated[4])
        self.assertNotIn('位信', generated[2]); self.assertNotIn(1, generated)

    def test_phonetic_hard_gate_and_unknown(self):
        self.assertEqual(self.proposer.category('位信', '微信'), 'tone')
        self.assertIsNone(self.proposer.category('微信', '微星'))
        self.assertIsNone(Proposer(self.model, {'位':['wei0'], '微':['wei1']}).category('位信', '微信'))

    def test_retrieved_candidate_not_in_ngram_proposal(self):
        evidence = dict(segments=[dict(left_context='', text='微信电脑')])
        index = self.proposer.retrieved_index(evidence)
        self.assertIn('微信电脑', index[4, 'wei'])
        self.assertNotIn('微信电脑', self.model.c[4])

    def test_never_join_segments(self):
        evidence = dict(segments=[dict(left_context='', text='微'), dict(left_context='', text='信')])
        self.assertNotIn('微信', self.proposer.retrieved_index(evidence).get((2, 'wei'), ()))

    def test_compatible_and_conflicting_overlaps(self):
        a = dict(begin=0, end=2, target='微信')
        b = dict(begin=1, end=3, target='信支')
        self.assertEqual(resolve('位信支', [a,b])[0], '微信支')
        b['target'] = '星支'
        self.assertEqual(resolve('位信支', [a,b])[0], '位信支')
        self.assertEqual(len(resolve('位信支', [a,b])[2]), 2)

    def test_full_pipeline_ac_keep_boundaries_and_missing_table(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'pronunciation').mkdir(); (root / 'ac').mkdir()
            (root / 'pronunciation/pronunciation_char.tsv').write_text('char\treadings\n' +
                ''.join(c+'\t'+'|'.join(rs)+'\n' for c,rs in self.chars.items()), encoding='utf8')
            (root / 'ac/ac_lock.tsv').write_text('word\n微星\n', encoding='utf8')
            (root / 'model.json').write_text(json.dumps(self.model.data), encoding='utf8')
            params = dict(alpha=.01, kappa=10., rho=1., top_h=30, calibrated=False,
                          classes={'same':[0.,1.], 'tone':[0.,1.]})
            (root / 'parameters.json').write_text(json.dumps(params), encoding='utf8')
            evidence_db(root / 'evidence.sqlite', [('a', '我用微信支付', '')])
            manifest = dict(format='tc-evidence-package-2', files={name:sha(root/name) for name in
                            ('model.json', 'evidence.sqlite', 'parameters.json')})
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
            cleaner = ProposalCleaner(root, EXE, root, research=False)
            try:
                self.assertFalse(cleaner.evidence_scoring)
                text = '我用位信支付\n微星电脑。位\n信支付'
                result = cleaner.clean(text)
                self.assertEqual(result['text'], text)
                self.assertFalse(result['domain_evidence'])
                self.assertTrue(result['windows'])
                for w in result['windows']:
                    self.assertNotIn('\n', w['source']); self.assertNotIn('。', w['source'])
                    self.assertNotIn('微星', w['source'])
                    self.assertEqual(w['reason'], 'uncalibrated')
                cleaner.evidence_scoring = True
                self.assertTrue(cleaner.clean(text)['domain_evidence'])
            finally:
                cleaner.close()


if __name__ == '__main__':
    unittest.main()
