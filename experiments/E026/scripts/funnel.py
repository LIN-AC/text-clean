#!/usr/bin/env python3
"""E026 真值漏斗：每个真实错误实例在流水线里第一次死在哪一关。

关卡顺序（首次失败即归类，不重复计数）：
  S1 真值目标词是否在启用候选池
  S2 倒排索引按长度/基音/首音节能否取到该候选
  S3 拼音硬过滤（距离≤2、逐位近音、模糊下限）
  S4 是否进入评分（证据存在性按臂口径判定）
  S5 进入评分但分数≤0（输给 KEEP 准入门）
  S6 分数>0 却没落地（竞争/整组否决/窗口上下文/输出阶段）
S6 用隔离探针拆分：把错串单独成行喂给同一个二进制——
  隔离能改对 → 丢在句子级窗口/上下文；隔离也改不出 → 丢在候选竞争。
另外断言：二进制打印出的拼音编辑一律已落到 stdout（inventory.py 已校验），
所以"已生成却在输出阶段丢失"若存在，必然表现为"未打印"，由 S6 捕获。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E026/results'
sys.path.insert(0, str(R / 'experiments/E026/scripts'))
import replica as RP
sys.stdout.reconfigure(encoding='utf-8')

ARM = (sys.argv[1] if len(sys.argv) > 1 else 'Z2')   # 控制臂 = Z2，另可跑 Z1
EXTRA = {'Z1': [], 'Z2': ['--missing-evidence', 'char', '--missing-cap', '0.6']}
EXE = str(R / 'build/e025/text_clean.exe')
errors = json.loads((O / 'errors.json').read_text(encoding='utf-8'))
applied = json.loads((O / 'applied.json').read_text(encoding='utf-8'))

def index_reachable(o, t):
    """复刻倒排检索的必要条件：等长、存在同基音位置、且首音节相同（gate 开时 require_first）。"""
    if len(o) != len(t):
        return False, '长度不等'
    inp, cand = RP.input_readings(o), RP.candidate_variants(t)
    shared = [k for k, (a, b) in enumerate(zip(inp, cand))
              if {RP.base_of(x) for x in a} & {RP.base_of(y) for y in b}]
    if not shared:
        return False, '无任何同基音位置'
    if 0 not in shared:
        return False, '首音节不符(索引 require_first)'
    return True, ''


FIRST_BASES = {RP.base_of(v[0]) for v in RP.WORD_READS.values() if v}
LOCKS = [l.split('\t')[0] for l in (R / 'data/ac/ac_lock.tsv').read_text(encoding='utf-8').splitlines()
         if l and not l.startswith('#') and l.split('\t')[0] != 'word']


def locked_spans(text):
    out = set()
    for w in LOCKS:
        i = text.find(w)
        while i >= 0:
            out.update(range(i, i + len(w)))
            i = text.find(w, i + 1)
    return out


# ---------- 隔离探针：错串单独成行 ----------
probe_key = sorted({(e['original'], e['truth']) for e in errors if e['truth'] in RP.TARGETS})
probe = {}
for arm in ('Z1', 'Z2'):
    body = '\n'.join(o for o, _ in probe_key) + '\n'
    p = subprocess.run([EXE, '--no-index-cache'] + EXTRA[arm], input=body.encode('utf-8'),
                       capture_output=True, cwd=str(R))
    out = p.stdout.decode('utf-8').splitlines()
    assert len(out) == len(probe_key)
    probe[arm] = {(o, t): out[i].strip() == t.strip() for i, (o, t) in enumerate(probe_key)}
    print('%s 隔离探针: %d 对，能改出 %d 对' % (arm, len(probe_key), sum(probe[arm].values())))

# ---------- 逐条判因 ----------
rows = []
for e in errors:
    o, t = e['original'], e['truth']
    rec = dict(video=e['video'], begin=e['begin'], end=e['end'], o=o, t=t, len=len(o),
               applied=e[ARM]['applied'], overlap=e[ARM]['overlap'],
               iso=probe[ARM].get((o, t)) if t in RP.TARGETS else None)
    if rec['applied']:
        rec.update(stage='S0 已改对', detail='二进制在该区间产出真值')
    elif t not in RP.TARGETS and len(t) == 1:
        rec.update(stage='S1a 单字错误(候选池最短 2 字)', detail='真值只有 1 字，启用目标词最短长度为 2')
    elif t not in RP.TARGETS:
        rec.update(stage='S1b 多字真值不在启用候选池', detail='真值片段从未出现在候选表目标列')
    elif not index_reachable(o, t)[0]:
        rec.update(stage='S2 索引取不到', detail=index_reachable(o, t)[1])
    else:
        d, stage, missing, s, why = RP.score(o, t, ARM)
        first_base_ok = bool({RP.base_of(x) for x in RP.input_readings(o)[0]} & FIRST_BASES)
        lock_hit = bool(locked_spans(e['line_text']) & set(range(e['begin'], e['end'])))
        if d is None or stage.startswith(('长度', '拼音距离', '短于', '近音')):
            rec.update(stage='S3 拼音硬过滤拦截', detail='%s d=%s' % (stage, d))
        elif not first_base_ok:
            rec.update(stage='S3 首音节锚点门拦截', detail='原文首字读音不在候选首音节集 d=%s' % d)
        elif lock_hit:
            rec.update(stage='S3 AC 锁定保护拦截', detail='窗口与 AC 锁定字重叠 d=%s' % d)
        elif stage == '未进入评分':
            rec.update(stage='S4 未进入评分', detail=why)
        elif s is None:
            rec.update(stage='S4 未进入评分', detail='分数无法复算')
        elif s <= 0:
            rec.update(stage='S5 进入评分但≤0(输给 KEEP)', detail='d=%s score=%.3f' % (d, s))
        elif rec['iso']:
            rec.update(stage='S7 隔离可改，句中丢失', detail='d=%s score=%.3f 句中重叠编辑=%s' % (d, s, rec['overlap']))
        else:
            rec.update(stage='S8 分数>0 仍被拒(竞争/整组否决)', detail='d=%s score=%.3f' % (d, s))
        rec['d'], rec['score'] = d, s
    rows.append(rec)

stat = collections.Counter(r['stage'] for r in rows)
chars = collections.Counter()
for r in rows:
    chars[r['stage']] += r['len']
total = len(rows)
print('\n=== 真值漏斗（臂 %s，控制组配置）：实例数 / 字数 / 占全部错误比例 ===' % ARM)
order = ['S0 已改对', 'S1a 单字错误(候选池最短 2 字)', 'S1b 多字真值不在启用候选池', 'S2 索引取不到', 'S3 拼音硬过滤拦截', 'S3 首音节锚点门拦截',
         'S3 AC 锁定保护拦截', 'S4 未进入评分', 'S5 进入评分但≤0(输给 KEEP)',
         'S7 隔离可改，句中丢失', 'S8 分数>0 仍被拒(竞争/整组否决)']
for k in order:
    if stat[k]:
        print('  %-34s %5d 实例 (%5.1f%%)  %5d 字' % (k, stat[k], 100.0 * stat[k] / total, chars[k]))
print('  %-34s %5d 实例 (%5.1f%%)  %5d 字' % ('合计', total, 100.0, sum(c['len'] for c in rows)))
json.dump(rows, (O / ('funnel_%s.json' % ARM)).open('w', encoding='utf-8'), ensure_ascii=False, indent=1)

# ---------- 对照旧次数臂：新版丢在哪一关 ----------
c2hit = {(e['video'], e['begin']) for e in errors if e['C2']['applied'] and not e[ARM]['applied']}
sub = collections.Counter(r['stage'] for r in rows if (r['video'], r['begin']) in c2hit)
print('\n=== 旧次数臂 C2 改对、%s 没改对的实例 = %d 个；它们在 %s 死于哪一关 ===' % (ARM, len(c2hit), ARM))
for k, v in sub.most_common():
    print('  %-34s %d' % (k, v))
json.dump(dict(only_c2=dict(sub), only_c2_total=len(c2hit)), (O / 'c2_only.json').open('w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

# ---------- 典型案例 ----------
print('\n=== 典型案例（每关 3 条）===')
seen = collections.Counter()
for r in sorted(rows, key=lambda x: (x['stage'], -(x['score'] or 0) if x['stage'].startswith('S5') else 0)):
    if seen[r['stage']] >= 3 or r['stage'].startswith('S1'):
        continue
    seen[r['stage']] += 1
    print('  [%s] %s:%d..%d  原文"%s" 真值"%s" 候选"%s" d=%s 复算分=%s 隔离=%s 句中重叠=%s' % (
        r['stage'], r['video'], r['begin'], r['end'], r['o'], r['t'], r['t'],
        r.get('d'), ('%.3f' % r['score']) if r.get('score') is not None else '-', r.get('iso'),
        r['overlap'] or '无'))

# ---------- 疑似真值错误（只上报，不改） ----------
sus = []
for r in rows:
    if not r['stage'].startswith('S1') or r['len'] < 2:
        continue
    zo, zt = RP.ZIPF.get(r['o']), RP.ZIPF.get(r['t'])
    if zo and (zt is None or zt < zo - 1.0) and r['len'] >= 3:
        sus.append(dict(r=r, zo=zo, zt=zt))
sus.sort(key=lambda x: -x['zo'])
print('\n=== 疑似真值错误候选（上报园长确认，本轮不改）：%d 条，列前 12' % len(sus))
for s in sus[:12]:
    r = s['r']
    print('  %s:%d..%d ASR"%s"(zipf %.2f) 真值"%s"(zipf %s)' % (
        r['video'], r['begin'], r['end'], r['o'], s['zo'], r['t'],
        ('%.2f' % s['zt']) if s['zt'] else '查无'))
json.dump(dict(stages=dict(stat), chars=dict(chars), suspected_gt=[dict(begin=s['r']['begin'], video=s['r']['video'],
          original=s['r']['o'], truth=s['r']['t'], zipf_original=s['zo'], zipf_truth=s['zt']) for s in sus]),
          (O / 'funnel_summary.json').open('w', encoding='utf-8'), ensure_ascii=False, indent=1)
