import json,math,pathlib,sqlite3,sys,tempfile,unittest,types
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from rag_clean import Model,EvidenceStore,Cleaner,affected_scores,posterior,phonetic_class,BOS,EOS,UNK,local_context,transition_events,BLOCK_CHARS,EVIDENCE_CHARS
from prepare_rag_package import corpus_fragments,blocks

class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=Model.train(['微信支付','微信支付','微信聊天','微星电脑','微星电脑','使用手机','使用手机','孤'])

    def test_normalization_all_histories(self):
        m=self.model
        for h in ['',BOS*3,'没见过']+list(m.den):
            self.assertAlmostEqual(sum(m.probability(h,w) for w in m.vocab),1,places=10)
        self.assertGreater(m.probability('任何史',UNK),0)

    def test_empty_domain_exactly_zero_D(self):
        m=self.model
        for word in ['微信','微星']:
            g,mix=affected_scores(m,(),10,'使用',word,'支付')
            self.assertEqual(g,mix)

    def test_document_denominator_and_fallback(self):
        m=self.model;h='^^微';counts={(h,'信'):2,(h,'星'):1};totals={h:3}
        self.assertAlmostEqual(sum((counts.get((h,w),0)+10*m.probability(h,w))/(totals[h]+10) for w in m.vocab),1)
        with self.assertRaises(ValueError):affected_scores(m,(),0,'','微信','')

    def test_local_equals_full_sentence_ratio(self):
        m=self.model
        def full(s):
            h=BOS*3;v=0
            for w in m.encode(s)+EOS:v+=math.log(m.probability(h,w));h=(h+w)[-3:]
            return v
        a=affected_scores(m,(),10,'使用','微信','支付手机')[0]
        b=affected_scores(m,(),10,'使用','微星','支付手机')[0]
        self.assertAlmostEqual(a-b,full('使用微信支付手机')-full('使用微星支付手机'))

    def test_eos_is_scored(self):
        m=self.model
        a=affected_scores(m,(),10,'','微信','')[0]
        expected=math.log(m.probability('^^^','微'))+math.log(m.probability('^^微','信'))+math.log(m.probability('^微信',EOS))
        self.assertAlmostEqual(a,expected)

    def test_cue_newline_is_not_left_context_or_sentence_stop(self):
        for gap in ['\n','\r\n','，',' ']:
            text='据史书记载'+gap+'魏清获取病\n下一行'
            begin=text.index('魏')
            left,right,bos,eos=local_context(text,begin,begin+4)
            self.assertEqual((left,right,bos,eos),('','病',False,False))
        self.assertEqual(local_context('前句。微信！',3,5),('','',True,True))
        self.assertEqual(local_context('微信',0,2),('','',True,True))

    def test_partial_fragment_has_no_fabricated_sentence_tokens(self):
        base=['微信支付','微信支付','微信聊天','微星电脑','微星电脑','使用手机','使用手机','孤']
        m=Model.train([(s,True,True) for s in base]+[('微信支付',False,False)])
        self.assertEqual(m.c[4]['^^微信'],self.model.c[4]['^^微信'])
        self.assertEqual(m.c[4]['信支付$'],self.model.c[4]['信支付$'])
        self.assertEqual(m.c[4]['微信支付'],self.model.c[4]['微信支付']+1)
        self.assertNotIn(('^^微','信'),set(transition_events(m,'微信支付')))
        self.assertEqual(set(transition_events(m,'微信支付')),{('微信支','付')})
        a=affected_scores(m,(),10,'','微信','',False,False)[0]
        self.assertAlmostEqual(a,math.log(m.probability('','微'))+math.log(m.probability('微','信')))

    def test_partial_local_difference_matches_full_fragment(self):
        m=self.model
        def full(text):
            h='';s=0.
            for ch in m.encode(text):s+=math.log(m.probability(h,ch));h=(h+ch)[-3:]
            return s
        a=affected_scores(m,(),10,'使用','微信','支付手机',False,False)[0]
        b=affected_scores(m,(),10,'使用','微星','支付手机',False,False)[0]
        self.assertAlmostEqual(a-b,full('使用微信支付手机')-full('使用微星支付手机'))

    def test_unsupported_fragment_initial_character_maps_to_unknown(self):
        fragments=[('微信支付',True,True),('微信支付',True,True),('孤',True,True),
                   ('龘微',False,False),('龘微',False,False)]
        m=Model.train(fragments)
        self.assertEqual(m.data['no_continuation_characters'],['龘'])
        self.assertNotIn('龘',m.vocab)
        self.assertGreater(m.probability('','龘'),0)
        self.assertAlmostEqual(sum(m.probability('',c) for c in m.vocab),1)

    def test_blocking_preserves_internal_transitions_without_fake_edges(self):
        fragment=dict(text='微信支付'*150,off=23,source_seg_id=4,left_class='句末标点',right_class='句末标点',bos=True,eos=True)
        bs=list(blocks(fragment));events=set()
        for b in bs:
            self.assertLessEqual(len(b['text']),BLOCK_CHARS)
            self.assertEqual(b['text'],fragment['text'][b['off']-23:b['off']-23+len(b['text'])])
            events.update(transition_events(self.model,b['text'],b['left_context'],b['bos'],b['eos']))
        self.assertEqual(events,set(transition_events(self.model,fragment['text'],bos=True,eos=True)))
        self.assertFalse(bs[1]['bos']);self.assertFalse(bs[0]['eos'])
        self.assertEqual(bs[1]['left_class'],'检索块边界')

    def test_history_document_edges_and_linebreaks_do_not_emit_eos(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute('create table segs(seg_id,doc_id,ord,off,text_norm,chars,left_edge,right_edge,left_class,right_class,left_is_stop,right_is_stop)')
        db.execute("insert into segs values(1,1,0,0,'微信',2,'^',char(10),'文档头','空白或换行',0,0)")
        db.execute("insert into segs values(2,1,1,3,'支付',2,char(10),'$','空白或换行','文档尾',0,0)")
        doc=dict(doc_id=1,text_norm='微信 支付',text_raw='微信\n支付',normalization_map_json='[0,1,2,3,4]',domain='历史')
        fs=list(corpus_fragments(db,doc))
        self.assertEqual([f['off'] for f in fs],[0,3])
        self.assertTrue(all(not f['bos'] and not f['eos'] for f in fs))
        db.execute("update segs set right_class='句末标点' where seg_id=1")
        with self.assertRaises(ValueError):list(corpus_fragments(db,doc))
        db.close()

    def test_retrieval_character_budget_and_trace(self):
        with tempfile.TemporaryDirectory() as d:
            path=pathlib.Path(d)/'e.sqlite';db=sqlite3.connect(path)
            db.executescript("create table meta(key,value);insert into meta values('format','tc-rag-2');create table documents(cluster_id,source_family,source_doc_id);create table segments(id,cluster_id,text,off,left_context,bos,eos,left_class,right_class);create virtual table search using fts5(tokens);")
            for i in range(50):
                db.execute('insert into documents values(?,?,?)',(str(i),'书',i))
                db.execute('insert into segments values(?,?,?,?,?,?,?,?,?)',(i,str(i),'微信支付'*64,7,'使用微',0,1,'检索块边界','句末标点'))
                db.execute('insert into search(rowid,tokens) values(?,?)',(i,'微信'))
            db.commit();db.close()
            store=EvidenceStore(path,self.model);first=store.retrieve('微信',50);audit=store.last_retrieval
            self.assertEqual(audit['evidence_chars'],EVIDENCE_CHARS)
            self.assertTrue(audit['budget_cut']);self.assertFalse(audit['segments'][-1]['eos'])
            self.assertEqual(audit['segments'][-1]['right_class'],'载荷截断')
            self.assertEqual(store.retrieve('微信',50),first)
            self.assertEqual(store.last_retrieval,audit);store.db.close()

    def test_shared_posterior_stable_and_keep(self):
        p=posterior([1000,999],9);self.assertAlmostEqual(sum(p),1)
        self.assertTrue(all(math.isfinite(x) for x in p))
        self.assertLess(p[1],.99)
        self.assertGreater(posterior([-10],1)[0],posterior([-10],1)[1])
        with self.assertRaises(ValueError):posterior([0],-1)
        with self.assertRaises(ValueError):posterior([float('nan')],1)

    def test_competition_reduces_confidence(self):
        self.assertGreater(posterior([8],1)[1],posterior([8,8],1)[1])

    def test_whole_reading_and_near_gate(self):
        chars={'微':['wei1'],'星':['xing1'],'信':['xin4']}
        self.assertEqual(phonetic_class('微信',[['wei1','xin4']],chars),'same')
        self.assertEqual(phonetic_class('微信',[['wei1','xin1']],chars),'tone')
        self.assertEqual(phonetic_class('微星',[['wei1','xin4']],chars),'near')
        self.assertIsNone(phonetic_class('微信',[['mai1','xin4']],chars))
        self.assertIsNone(phonetic_class('微信',[['wei1','zhong4']],chars))

    def test_doc_clipping_with_repeated_segments(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'e.sqlite';db=sqlite3.connect(p)
            db.executescript("create table meta(key,value);insert into meta values('format','tc-rag-1');create table segments(id integer,cluster_id text,text text);create virtual table search using fts5(tokens);")
            for i,doc in enumerate(['A','A','B'],1):
                db.execute('insert into segments values(?,?,?)',(i,doc,'微信支付'))
                db.execute('insert into search(rowid,tokens) values(?,?)',(i,'微信 信支 支付'))
            db.commit();db.close()
            store=EvidenceStore(p,self.model);(counts,total),docs=store.retrieve('微信',50)
            self.assertEqual(counts[('^^微','信')],2)
            self.assertEqual(len(docs),2)
            self.assertEqual(total['^^微'],2)
            store.db.close()

    def test_pipeline_uncalibrated_keep_and_explicit_research(self):
        # Full decision/rewrite path with a fixed eligible frontend hypothesis.
        c=Cleaner.__new__(Cleaner);c.model=self.model;c.project=pathlib.Path('.')
        c.use_retrieval=True;c.readings={'微信':[['wei1','xin4']]}
        c.store=types.SimpleNamespace(global_terms=lambda text:[],retrieve=lambda q,k:((),[]))
        c.chars={'微':['wei1'],'星':['xing1']};c.exe='fixture'
        c.by_first={(2,'wei'):[dict(word='微信',readings=[['wei1','xin4']])]}
        c.params=dict(classes={'near':[100.,1.]},kappa=10.,rho=1.,alpha=.01,top_h=30,retrieval_limit=50,calibrated=False)
        raw=types.SimpleNamespace(stdout='begin\tend\tsource\ttarget\tdistance\n0\t2\t微星\t微信\t2\n'.encode())
        with patch('rag_clean.subprocess.run',return_value=raw):
            c.research=False;r=c.clean('微星')
            self.assertEqual(r['text'],'微星');self.assertEqual(r['windows'][0]['reason'],'uncalibrated')
            c.research=True;r=c.clean('微星')
            self.assertEqual(r['text'],'微信');self.assertEqual(len(r['edits']),1)
            self.assertEqual(r['windows'][0]['reason'],'applied')

if __name__=='__main__':unittest.main()
