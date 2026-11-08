#!/usr/bin/env python3
"""E022/E023/E024 指标口径的可复用副本。

本文件第 4 行起的内容从 experiments/E024/scripts/arms.py 第 16-81 行逐字复制，未作任何修改；E024 原脚本保持原样以便复核历史结果。
"""
import collections, decimal, re


D = {c: i for i, c in enumerate('零一二三四五六七八九')}; D.update({'〇': 0, '两': 2})
U = {'十': 10, '百': 100, '千': 1000, '万': 10000, '亿': 100000000}


def number(s):
    scale = 1
    if ('.' in s or '点' in s) and s[-1:] in ('万', '亿'): scale = U[s[-1]]; s = s[:-1]
    if '.' in s or '点' in s:
        a, b = re.split('[.点]', s)
        v = decimal.Decimal(number(a) + '.' + ''.join(str(D.get(c, c)) for c in b)) * scale
        return format(v, 'f').rstrip('0').rstrip('.') if '.' in format(v, 'f') else str(v)
    if not any(c in U for c in s): return str(int(''.join(str(D.get(c, c)) for c in s)))
    total = section = n = 0
    for c in s:
        if c not in U: n = n * 10 + int(D.get(c, c)); continue
        u = U[c]
        if u < 10000: section += (n or 1) * u; n = 0
        else:
            section += n
            if u == 100000000: total = (total + section) * u
            else: total += section * u
            section = n = 0
    return str(total + section + n)


NUM = re.compile('[0-9零〇一二两三四五六七八九十百千万亿]+(?:[.点][0-9零〇一二两三四五六七八九]+)?[万亿]?')


def tokens(s):
    out = []; i = 0
    while i < len(s):
        m = NUM.match(s, i)
        if m and (len(m[0]) > 1 or m[0].isascii() or m[0] in U): out.append(('#' + number(m[0]), i, m.end(), True)); i = m.end()
        elif re.match('[一-鿿A-Za-z0-9]', s[i]): out.append((s[i], i, i + 1, False)); i += 1
        else: i += 1
    return out


def align(src, tgt):
    a, b = tokens(src), tokens(tgt); n, m = len(a), len(b)
    def eq(i, j):
        x, y = a[i][0], b[j][0]
        return x == y or (x in D and y == '#' + str(D[x])) or (y in D and x == '#' + str(D[y]))
    f = [[0] * (m + 1) for _ in range(n + 1)]; q = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1): f[i][0] = i; q[i][m] = n - i
    for j in range(m + 1): f[0][j] = j; q[n][j] = m - j
    for i in range(1, n + 1):
        for j in range(1, m + 1): f[i][j] = min(f[i - 1][j] + 1, f[i][j - 1] + 1, f[i - 1][j - 1] + (not eq(i - 1, j - 1)))
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1): q[i][j] = min(q[i + 1][j] + 1, q[i][j + 1] + 1, q[i + 1][j + 1] + (not eq(i, j)))
    labels = {}
    for i, x in enumerate(a):
        if x[3]: continue
        possible = set()
        for j in range(m + 1):
            if f[i][j] + 1 + q[i + 1][j] == f[n][m]: possible.add(None)
            if j < m and f[i][j] + (not eq(i, j)) + q[i + 1][j + 1] == f[n][m]: possible.add(j)
        if len(possible) == 1 and None not in possible:
            y = b[next(iter(possible))]
            if not y[3]: labels[x[1]] = y[0]
    return labels, f[n][m]


# zipfC/zipfO 设为可选：旧次数模式不打印这两个字段，编辑级计数也必须能统计到
rx = re.compile(r'\[(\w+)\] status=\w+ (\d+)\.\.(\d+) "([^"]*)" -> "([^"]*)" entry=\d+ distance=(\d+) '
                r'score=([\d.e+-]+).*?action=replace(?:.*?zipfC=(\S+) zipfO=(\S+))?')
