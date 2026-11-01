"""Shrink a pull_all feed. usage: compact.py in.json out.json [maxbytes]"""
import json, sys
src, out = sys.argv[1], sys.argv[2]; cap = int(sys.argv[3]) if len(sys.argv) > 3 else 600000
d = json.load(open(src))
def shrink(g, nlog, tl, dl, step=1):
    g = dict(g)
    P = g['path']; P = (P[:-1:step] + P[-1:]) if step > 1 and len(P) > 40 else P
    g['path'] = [[round(x, 3), round(v)] for x, v in P]
    g['moments'] = [{**m, 't': m['t'][:tl], 'd': (m.get('d') or '')[:dl]} for m in g['moments']]
    g['missed'] = [{**m, 'ctx': (m.get('ctx') or '')[:dl], 'end': (m.get('end') or '')[:dl]} if isinstance(m.get('ctx'), str) else m for m in g.get('missed', [])]
    log = g.get('log') or []
    if g.get('kind') == 'bb' and g.get('sport') == 'Baseball': keep = log  # the MLB replay game needs its full log
    else:
        keep = sorted(log, key=lambda q: (q.get('cat', 'Play') == 'Play', -abs(q.get('sw') or 0)))[:nlog]
        keep.sort(key=lambda q: q.get('x') or 0)
    g['log'] = [{**q, 'txt': str(q.get('txt', ''))[:tl + 20]} for q in keep]
    return g
for nlog, tl, dl, st in [(60, 120, 200, 1), (40, 110, 140, 1), (24, 100, 100, 1), (14, 90, 80, 1), (8, 80, 0, 1), (4, 70, 0, 2), (2, 64, 0, 3), (0, 60, 0, 4)]:
    games = [shrink(g, nlog if g.get('state') == 'in' else nlog // 2, tl, dl, st) for g in d['games']]
    js = json.dumps({'updatedAt': d['updatedAt'], 'games': games}, separators=(',', ':'), ensure_ascii=False)
    if len(js.encode()) <= cap: break
open(out, 'w').write(js); print(out, len(js.encode()), 'bytes', nlog)
