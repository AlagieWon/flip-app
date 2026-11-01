"""Pull today's games across sports into one Flip feed.
- ESPN win probability: college football, NFL, NBA (live + final)
- Flip model: NHL (Poisson on goals), soccer via pull_soccer.py
usage: python3 pull_all.py out.json YYYYMMDD"""
import json, math, os, re, subprocess, sys, datetime
OUT, DATE = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__)); BASE = os.path.dirname(os.path.abspath(OUT))
TMP = os.path.join(BASE, 'live_all'); os.makedirs(TMP, exist_ok=True)

def get(url, name):
    p = os.path.join(TMP, name)
    for _ in range(3):
        if subprocess.run(['curl', '-sS', '--max-time', '25', url, '-o', p], capture_output=True).returncode == 0: break
    else: return {}
    try: return json.load(open(p))
    except Exception: return {}

def lighten(hexc):
    try: n = int(hexc, 16); r, g, b = n >> 16, n >> 8 & 255, n & 255
    except Exception: return None
    lum = .299 * r + .587 * g + .114 * b
    if lum < 70:
        f = 70 / max(lum, 1) if lum > 10 else 3; r, g, b = [min(255, int(c * f + 40)) for c in (r, g, b)]
    if lum > 225: return None
    return '#%02x%02x%02x' % (r, g, b)

def thin(path, n=90):
    if len(path) <= n: return path
    step = len(path) / n; keep = {0, len(path) - 1}
    i = 0.0
    while i < len(path): keep.add(int(i)); i += step
    # always keep big jumps
    for k in range(1, len(path)):
        if abs(path[k][1] - path[k - 1][1]) >= 6: keep.add(k); keep.add(k - 1)
    return [path[k] for k in sorted(keep)]

def clockmin(disp):
    m = re.match(r'(\d+):(\d+(?:\.\d+)?)', disp or '')
    if m: return int(m.group(1)) + float(m.group(2)) / 60
    m = re.match(r'(\d+(?:\.\d+)?)', disp or '')
    return float(m.group(1)) / 60 if m else 0

SPORTS = [  # path, league label, kind, period minutes, threshold
    ('football/college-football', 'College Football', 'fb', 15, 12),
    ('football/nfl', 'NFL', 'fb', 15, 12),
    ('basketball/nba', 'NBA', 'bk', 12, 9),
]

def comp_teams(ev):
    c = ev['competitions'][0]
    H = [x for x in c['competitors'] if x['homeAway'] == 'home'][0]; A = [x for x in c['competitors'] if x['homeAway'] == 'away'][0]
    return H, A

def base(ev, sport_label, league, kind, H, A, team, path, moments, log, src, ticks, wpsrc):
    st = ev['status']['type']
    return {'id': f"{kind}_{ev['id']}", 'sport': sport_label, 'league': league, 'a': A['team']['abbreviation'], 'an': A['team'].get('shortDisplayName') or A['team']['abbreviation'],
            'b': H['team']['abbreviation'], 'bn': H['team'].get('shortDisplayName') or H['team']['abbreviation'], 'as': int(A.get('score') or 0), 'bs': int(H.get('score') or 0),
            'state': st['state'], 'clock': 'Final' if st['state'] == 'post' else st.get('shortDetail', ''), 'team': team, 'kind': kind, 'wpsrc': wpsrc,
            'ac': lighten(A['team'].get('color', '')), 'bc': lighten(H['team'].get('color', '')), 'ticks': ticks, 'path': path, 'moments': moments, 'missed': [],
            'log': log, 'date': 'Today', 'source': src, 'start': ev.get('date')}
def pre_game(ev, sport_label, league, kind, url):
    comp = ev['competitions'][0]
    H = [c for c in comp['competitors'] if c['homeAway'] == 'home'][0]; A = [c for c in comp['competitors'] if c['homeAway'] == 'away'][0]
    g = base(ev, sport_label, league, kind, H, A, H['team']['abbreviation'], [], [], [], {'name': 'ESPN', 'url': url}, [], 'espn' if kind != 'hk' else 'model')
    g['as'] = g['bs'] = ''; g['clock'] = ev['status']['type'].get('shortDetail', '')
    g['pre_wp'] = pre_odds(comp, H, A); return g
def pre_odds(comp, H, A):
    # de-vigged pre-game win chance from the posted moneyline (home/away[/draw])
    try:
        ml = ((comp.get('odds') or [{}])[0].get('moneyline') or {})
        def p(side):
            o = ((ml.get(side) or {}).get('close') or (ml.get(side) or {}).get('open') or {}).get('odds')
            if o in (None, '', 'OFF'): return None
            o = float(str(o).replace('EVEN', '100')); return 100 / (o + 100) if o > 0 else -o / (-o + 100)
        ph, pa, pd = p('home'), p('away'), p('draw')
        if ph is None or pa is None: return None
        t = ph + pa + (pd or 0); ph, pa = ph / t, pa / t
        fav = 'home' if ph >= pa else 'away'
        return {'team': (H if fav == 'home' else A)['team']['abbreviation'], 'p': round(100 * max(ph, pa)), 'draw': round(100 * pd / t) if pd else None}
    except Exception: return None

def tidy(t):
    t = re.sub(r'^\(\s*\d+:\d+\s*\)\s*', '', t)
    t = re.sub(r'^(No Huddle-)?Shotgun\s+|^No Huddle\s+', '', t)
    t = re.sub(r'#\d+\s+', '', t)
    t = re.split(r',\s*clock\s|\s*\((?:H|Holder):', t)[0]
    t = re.sub(r'\s*\([^)]*\)\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t
NONPLAY = re.compile(r'^(Timeout|End of|End Quarter|Two-Minute|Official|Kickoff|Start of)', re.I)
def espn_game(sp, league, kind, pmin, thr, ev):
    s = get(f"https://site.api.espn.com/apis/site/v2/sports/{sp}/summary?event={ev['id']}", f"{kind}_{ev['id']}.json")
    wp = s.get('winprobability') or []; plays = {str(p.get('id')): p for p in (s.get('plays') or [])}
    if not plays and s.get('drives'):
        for d in (s['drives'].get('previous') or []) + ([s['drives']['current']] if s['drives'].get('current') else []):
            for p in d.get('plays', []): plays[str(p.get('id'))] = p
    if len(wp) < 5: return None
    H, A = comp_teams(ev); hs, as_ = int(H.get('score') or 0), int(A.get('score') or 0)
    home_persp = hs >= as_
    team = H['team']['abbreviation'] if home_persp else A['team']['abbreviation']
    pts = []; prev = None; cands = []; log = []; lastreal = None
    hv = [w.get('homeWinPercentage', .5) for w in wp]
    for k in range(1, len(hv) - 1):   # remove one-entry spikes in ESPN's feed
        if abs(hv[k] - hv[k - 1]) > .2 and abs(hv[k + 1] - hv[k - 1]) < .08: hv[k] = hv[k - 1]
    for k, w in enumerate(wp): w['homeWinPercentage'] = hv[k]
    for i, w in enumerate(wp):
        p = plays.get(str(w.get('playId')), {})
        per = (p.get('period') or {}).get('number') or 1; clk = (p.get('clock') or {}).get('displayValue', '')
        if per <= 4: x = ((per - 1) * pmin + (pmin - clockmin(clk))) / (4 * pmin)
        else: x = .975 + .02 * min(1, (per - 4) / 2)
        x = round(max(0, min(1, x)), 4)
        v = 100 * (w['homeWinPercentage'] if home_persp else 1 - w['homeWinPercentage'])
        if pts and x < pts[-1][0]: x = pts[-1][0]
        pts.append([x, round(v, 1)])
        if prev is not None and p:
            d = v - prev
            lab = f"Q{per} {clk}" if per <= 4 else f"OT {clk}"
            txt = (p.get('text') or '').strip()
            if kind == 'fb': txt = tidy(txt)
            nonplay = bool(NONPLAY.search(txt)) or not txt
            if nonplay and lastreal and abs(v - lastreal['b']) >= thr:
                ex = next((c for c in cands if c['id'] == lastreal['id']), None)
                if ex: ex['after'] = round(v)
                else: cands.append({'id': lastreal['id'], 'x': lastreal['x'], 'clock': lastreal['lab'], 'cat': lastreal['cat'], 't': lastreal['t'], 'd': lastreal['t'], 'before': round(lastreal['b']), 'after': round(v), 'src': 'auto'})
            elif not nonplay and abs(d) >= thr and not (kind == 'bk' and (x < .12 or (abs(d) > 25 and x < .85))):
                cat = (p.get('type') or {}).get('text') or 'Big play'
                cands.append({'id': f"{kind}{ev['id']}_{i}", 'x': x, 'clock': lab, 'cat': cat[:22], 't': txt[:110], 'd': txt,
                              'before': round(prev), 'after': round(v), 'src': 'auto'})
            if not nonplay:
                lastreal = {'id': f"{kind}{ev['id']}_{i}", 'x': x, 'lab': lab, 'cat': ((p.get('type') or {}).get('text') or 'Big play')[:22], 't': txt[:110], 'b': prev}
            if txt and (abs(d) >= 3 or p.get('scoringPlay')):
                log.append({'id': f"l{kind}{ev['id']}_{i}", 'x': x, 'c': lab, 'txt': txt[:160], 'cat': 'Play', 'sw': round(d)})
        prev = v
    DECISIVE = re.compile(r'TOUCHDOWN|TD\b|Yd (?:pass|run|rush)|FUMBLE|INTERCEPT|field goal|FG|SAFETY|punt|BLOCKED|downs|kick|return', re.I)
    if kind == 'fb': cands = [c for c in cands if abs(c['after'] - c['before']) <= 35 or DECISIVE.search(c.get('d') or c['t'])]
    cands.sort(key=lambda m: -abs(m['after'] - m['before'])); moments = sorted(cands[:6], key=lambda m: m['x'])
    ticks = [[0, 'Q1'], [.25, 'Q2'], [.5, 'Q3'], [.75, 'Q4']]
    url = f"https://www.espn.com/{'college-football' if 'college' in sp else sp.split('/')[1]}/game/_/gameId/{ev['id']}"
    return base(ev, 'Football' if kind == 'fb' else 'Basketball', league, kind, H, A, team, thin(pts), moments, log[-60:],
                {'name': 'ESPN win probability', 'url': url}, ticks, 'espn')

def pois(l, k): return math.exp(-l) * l ** k / math.factorial(k)
def hockey_wp(lh, la, gh, ga, r):
    w = t = 0
    for i in range(10):
        for j in range(10):
            p = pois(lh * r, i) * pois(la * r, j)
            if gh + i > ga + j: w += p
            elif gh + i == ga + j: t += p
    return w + t * (lh / (lh + la) if lh + la else .5)

def nhl_game(ev):
    s = get(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event={ev['id']}", f"nhl_{ev['id']}.json")
    plays = s.get('plays') or []
    if not plays: return None
    H, A = comp_teams(ev); hs, as_ = int(H.get('score') or 0), int(A.get('score') or 0)
    lh, la = 3.1, 2.9
    try:
        o = (s.get('pickcenter') or [])[0]
        def ml2p(m): return 100 / (m + 100) if m > 0 else -m / (-m + 100)
        ph, pa = ml2p(o['homeTeamOdds']['moneyLine']), ml2p(o['awayTeamOdds']['moneyLine']); ph = ph / (ph + pa)
        tot = 6.0; lh = tot * (.5 + (ph - .5) * .9); la = tot - lh
    except Exception: pass
    home_persp = hs >= as_
    team = H['team']['abbreviation'] if home_persp else A['team']['abbreviation']
    hid = str(H['team']['id'])
    gh = ga = 0; pts = []; moments = []; log = []
    def val(e):
        r = max(0, (60 - e) / 60); w = hockey_wp(lh, la, gh, ga, r) if r > 0 else (1.0 if gh > ga else 0.0 if gh < ga else .5)
        return 100 * (w if home_persp else 1 - w)
    last = -1
    for i, p in enumerate(plays):
        per = (p.get('period') or {}).get('number') or 1; clk = (p.get('clock') or {}).get('displayValue', '20:00')
        e = min(60, (per - 1) * 20 + (20 - clockmin(clk))) if per <= 3 else 60
        while last < int(e):
            last += 1; pts.append([round(last / 60 * .97, 4), round(val(last), 1)])
        if (p.get('type') or {}).get('text') == 'Goal' or p.get('scoringPlay'):
            before = val(e)
            if str((p.get('team') or {}).get('id')) == hid: gh += 1
            else: ga += 1
            after = val(e); x = round(min(.97, e / 60 * .97), 4) if per <= 3 else .985
            pts.append([x, round(before, 1)]); pts.append([x, round(after, 1)])
            txt = (p.get('text') or 'Goal').strip(); lab = f"P{per} {clk}" if per <= 3 else ('OT' if per == 4 else 'SO')
            moments.append({'id': f"hk{ev['id']}_{i}", 'x': x, 'clock': lab, 'cat': 'Shootout' if lab == 'SO' else ('OT winner' if lab == 'OT' else 'Goal'), 't': txt[:110], 'd': txt, 'before': round(before), 'after': round(after), 'src': 'auto'})
            log.append({'id': f"lhk{ev['id']}_{i}", 'x': x, 'c': lab, 'txt': txt[:160], 'cat': 'Goal', 'sw': round(after - before)})
    if ev['status']['type']['state'] == 'post': pts.append([1, 100.0 if (hs > as_) == home_persp and hs != as_ else 0.0])
    moments = [m for m in moments if abs(m['after'] - m['before']) >= 8]
    return base(ev, 'Hockey', 'NHL', 'hk', H, A, team, pts, moments, log, {'name': 'ESPN play-by-play · Flip model', 'url': f"https://www.espn.com/nhl/game/_/gameId/{ev['id']}"},
                [[0, 'P1'], [.323, 'P2'], [.647, 'P3']], 'model')

games = []
for sp, league, kind, pmin, thr in SPORTS:
    sb = get(f"https://site.api.espn.com/apis/site/v2/sports/{sp}/scoreboard?dates={DATE}", f"sb_{kind}_{league[:3]}.json")
    for ev in sb.get('events', []):
        if ev['status']['type']['state'] == 'pre':
            if kind == 'fb' and league == 'College Football': continue  # 60+ pre-game CFB games would swamp the Lounge
            games.append(pre_game(ev, {'fb': 'Football', 'bk': 'Basketball'}[kind], league, kind, f"https://www.espn.com/{sp.split('/')[1]}/game/_/gameId/{ev['id']}")); continue
        try:
            g = espn_game(sp, league, kind, pmin, thr, ev)
            if g: games.append(g)
        except Exception as e: print('skip', league, ev['id'], e)
sb = get(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={DATE}", 'sb_nhl.json')
for ev in sb.get('events', []):
    if ev['status']['type']['state'] == 'pre':
        games.append(pre_game(ev, 'Hockey', 'NHL', 'hk', f"https://www.espn.com/nhl/game/_/gameId/{ev['id']}")); continue
    try:
        g = nhl_game(ev)
        if g: games.append(g)
    except Exception as e: print('skip nhl', ev['id'], e)
# soccer
soc_out = os.path.join(BASE, f'soc_{DATE}.json')
subprocess.run([sys.executable, os.path.join(HERE, 'pull_soccer.py'), soc_out, DATE], capture_output=True)
soc = json.load(open(soc_out)) if os.path.exists(soc_out) else []
for g in soc: g['date'] = 'Today'
extra = os.path.join(BASE, 'mlb_sample.json')
if os.path.exists(extra):
    try: games_x = json.load(open(extra)); games_x = games_x.get('games', games_x)
    except Exception: games_x = []
else: games_x = []
json.dump({'updatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'games': games + soc + games_x}, open(OUT, 'w'), separators=(',', ':'))
for g in games:
    if g['state'] == 'pre': print(g['league'][:6], 'pre', g['a'], '@', g['b'], g['clock']); continue
    top = max(g['moments'], key=lambda m: abs(m['after'] - m['before']), default=None)
    print(g['league'][:6], g['state'], g['a'], g['as'], '@', g['b'], g['bs'], g['clock'], '| flip', (top['clock'], top['before'], '->', top['after'], top['t'][:60]) if top else None)
print(len(games), 'us games +', len(soc), 'soccer')
