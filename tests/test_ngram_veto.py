import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"tools"))
from ngram_veto import BoundaryModel
m=BoundaryModel(["他选择了微星主板。她购买了微星主板。他使用微信聊天功能。她使用微信聊天功能。"])
case=dict(text="我买了微星主板",begin=3,end=5,replacement="微信")
assert m.evaluate(case)['veto']
assert BoundaryModel([]).evaluate(case)==dict(delta=0.0,supported=0,veto=False)
good=dict(text="我使用薇信聊天功能",begin=3,end=5,replacement="微信")
assert not m.evaluate(good)['veto']
assert m.evaluate(good)['supported']>=2
try:
    m.evaluate(dict(text="测试",begin=0,end=2,replacement="测"))
    raise AssertionError('length change accepted')
except ValueError: pass
print('Offline ngram: veto / sparse abstention / correct candidate / invalid span PASS')
