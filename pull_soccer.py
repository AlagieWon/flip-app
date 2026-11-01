"""Pull finished soccer games for a date from ESPN and build Flip games with a model win-probability line.
ESPN has no soccer win probability, so: goal rates from pre-match moneylines (Poisson fit), scaled by time left,
adjusted for red cards; swings on goals / reds / pens; missed chances get a 'what if it went in' estimate.
usage: python3 pull_soccer.py out.json 20261031 [leagues...]"""
import json, math, re, subprocess, sys, os
OUT = sys.argv[1]; DATE = sys.argv[2]
LEAGUES = sys.argv[3:] or ['eng.1', 'esp.1', 'ita.1', 'ger.1', 'fra.1', 'usa.1', 'eng.2']
LNAME = {'eng.1': 'Premier League', 'esp.1': 'LaLiga', 'ita.1': 'Serie A', 'ger.1': 'Bundesliga', 'fra.1': 'Ligue 1', 'usa.1': 'MLS', 'eng.2': 'Championship'}
try: NOTES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'notes.json')))
except Exception: NOTES = {}
TMP = os.path.join(os.path.dirname(os.path.abspath(OUT)), 'live_soc'); os.makedirs(TMP, exist_ok=True)

def get(url, name):
    p = os.path.join(TMP, name)
    for _ in range(3):
        if subprocess.run(['curl', '-sS', '--max-time', '25', url, '-o', p]).returncode == 0: break
    else: raise SystemExit('fetch failed ' + url)
    return json.load(open(p))

def pois(l, k): return math.exp(-l) * l ** k / math.factorial(k)
def outcome(lh, la, gh=0, ga=0, N=11):
    ph = [pois(lh, k) for k in range(N)]; pa = [pois(la, k) for k in range(N)]
    w = d = 0
    for i in range(N):
        for j in range(N):
            p = ph[i] * pa[j]
            if gh + i > ga + j: w += p
            elif gh + i == ga + j: d += p
    return w, d, 1 - w - d
def ml2p(ml): return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)
def fit(pH, pA):
    best = (9, 1.4, 1.1)
    for i in range(20, 300, 4):
        for j in range(20, 300, 4):
            w, d, l = outcome(i / 100, j / 100)
            e = (w - pH) ** 2 + (l - pA) ** 2
            if e < best[0]: best = (e, i / 100, j / 100)
    return best[1], best[2]

def lighten(hexc):
    try:
        n = int(hexc, 16); r, g, b = n >> 16, n >> 8 & 255, n & 255
    except Exception: return None
    lum = .299 * r + .587 * g + .114 * b
    if lum < 70:
        f = 70 / max(lum, 1) if lum > 10 else 3
        r, g, b = [min(255, int(c * f + 40)) for c in (r, g, b)]
    if lum > 225: return None  # white kits read badly as a badge
    return '#%02x%02x%02x' % (r, g, b)

def minute(disp):
    m = re.match(r"(\d+)'(?:\+(\d+)')?", disp or '')
    if not m: return None
    return int(m.group(1)), int(m.group(2) or 0)

def build(ev, lg):
    s = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary?event={ev['id']}", f"{lg}_{ev['id']}.json")
    comp = s['header']['competitions'][0]
    H = [c for c in comp['competitors'] if c['homeAway'] == 'home'][0]; A = [c for c in comp['competitors'] if c['homeAway'] == 'away'][0]
    hn, an_ = H['team']['displayName'], A['team']['displayName']
    hs, as_ = int(H.get('score') or 0), int(A.get('score') or 0)
    # pre-match rates
    lh, la = 1.45, 1.15
    try:
        o = (s.get('pickcenter') or s.get('odds'))[0]
        pH, pA, pD = ml2p(o['homeTeamOdds']['moneyLine']), ml2p(o['awayTeamOdds']['moneyLine']), ml2p(o['drawOdds']['moneyLine'])
        t = pH + pA + pD; lh, la = fit(pH / t, pA / t)
    except Exception: pass
    # timeline from commentary
    com = [c for c in s.get('commentary', []) if c.get('time', {}).get('displayValue')]
    add1 = add2 = 0
    for c in com:
        mm = minute(c['time']['displayValue'])
        if not mm: continue
        if mm[0] == 45 and 'First Half ends' in c.get('text', ''): add1 = max(add1, mm[1])
        if mm[0] == 90: add2 = max(add2, mm[1])
    for c in com:
        mm = minute(c['time']['displayValue'])
        if mm and mm[0] == 45 and mm[1] > add1 and 'Second Half' not in c.get('text', ''): add1 = mm[1]
    TOT = 90 + add1 + add2
    def elapsed(disp, txt=''):
        mm = minute(disp)
        if not mm: return 0
        m, p = mm
        if m < 45: return m
        if m == 45: return 45 + add1 if 'Second Half' in txt else 45 + min(p, add1)
        if m < 90: return add1 + m
        return add1 + 90 + p
    T = 'home' if hs >= as_ else 'away'      # perspective: the winner (home on a draw)
    team = H['team']['abbreviation'] if T == 'home' else A['team']['abbreviation']
    teamname = hn if T == 'home' else an_
    def wp(e, gh, ga, rh, ra):
        r = max(0.0, (TOT - e) / TOT)
        fh = .62 ** rh * 1.22 ** ra; fa = .62 ** ra * 1.22 ** rh
        w, d, l = outcome(lh * r * fh, la * r * fa, gh, ga)
        return 100 * (w if T == 'home' else l)
    def wp_side(side, e, gh, ga, rh, ra):
        r = max(0.0, (TOT - e) / TOT)
        fh = .62 ** rh * 1.22 ** ra; fa = .62 ** ra * 1.22 ** rh
        w, d, l = outcome(lh * r * fh, la * r * fa, gh, ga)
        return 100 * (w if side == 'home' else l)
    def wp_for(side, e, gh, ga, rh, ra):
        v = wp(e, gh, ga, rh, ra); return v if (side == 'home') == (T == 'home') else None
    # events
    gh = ga = rh = ra = 0
    path = []; moments = []; log = []; chances = []
    last_e = -1
    def side_of(txt):
        ih, ia = txt.find(f'({hn})'), txt.find(f'({an_})')
        if ih >= 0 and (ia < 0 or ih < ia): return 'home'
        if ia >= 0: return 'away'
        if txt.startswith(hn) or f'Goal! {hn}' in txt: return 'home'
        return None
    for idx, c in enumerate(com):
        txt = c.get('text', ''); disp = c['time']['displayValue']; e = elapsed(disp, txt); x = round(min(1, e / TOT), 4)
        while last_e < int(e):
            last_e += 1; path.append([round(min(1, last_e / TOT), 4), round(wp(last_e, gh, ga, rh, ra), 1)])
        before = wp(e, gh, ga, rh, ra); cat = None; title = None
        if txt.startswith('Goal!') or txt.startswith('Own Goal'):
            sc = re.search(r'Goal! .*?(\d+), .*? (\d+)\.', txt)
            nh, na = (int(sc.group(1)), int(sc.group(2))) if sc else (gh, ga)
            scorer = re.search(r'\.\s+([^.(]+?)\s+\(', txt); scorer = scorer.group(1).strip() if scorer else 'Goal'
            pen = 'penalty' in txt.lower(); og = txt.startswith('Own Goal')
            gh, ga = nh, na; cat = 'Own goal' if og else ('Penalty' if pen else 'Goal')
            title = f"{scorer} {'scores from the spot' if pen else ('own goal' if og else 'scores')}"
        elif 'red card' in txt.lower() or txt.startswith('Second yellow card'):
            who = re.search(r'(?:to|card to)\s+([^(]+?)\s+\(', txt) or re.search(r'^([^(]+?)\s+\(', txt)
            sd = side_of(txt)
            if sd == 'home': rh += 1
            elif sd == 'away': ra += 1
            cat = 'Red card'; title = f"{who.group(1).strip() if who else 'Player'} sent off"
        elif txt.startswith('Penalty missed') or txt.startswith('Penalty saved'):
            who = re.search(r'\.\s+([^(]+?)\s+\(', txt) or re.search(r'!\s+([^(]+?)\s+\(', txt)
            cat = 'Penalty miss'; title = f"{who.group(1).strip() if who else 'Penalty'} misses a penalty"
        after = wp(e, gh, ga, rh, ra)
        if cat:
            path.append([x, round(before, 1)]); path.append([x, round(after, 1)])
            moments.append({'id': f"s{ev['id']}_{idx}", 'x': x, 'clock': disp, 'cat': cat, 't': title, 'd': txt,
                            'before': round(before), 'after': round(after), 'src': 'auto', 'ctx': f"{gh}–{ga} · {disp}" if False else None})
        # missed chances: shots that could have gone in
        low = txt.lower()
        if (low.startswith('attempt saved') or low.startswith('attempt missed') or 'hits the' in low or cat == 'Penalty miss') and cat != 'Goal':
            sd = side_of(txt) or ('home' if hn in txt else 'away' if an_ in txt else None)
            if sd:
                q = 1.0 if ('hits the' in low or 'saved' in low or cat == 'Penalty miss') else .55
                if 'centre of the box' in low or 'very close' in low or 'six yard' in low or 'close range' in low or cat == 'Penalty miss': q *= 1.25
                if 'outside the box' in low or 'too high' in low or 'long range' in low: q *= .55
                ngh, nga = (gh + 1, ga) if sd == 'home' else (gh, ga + 1)
                cur = wp_side(sd, e, gh, ga, rh, ra); wi = wp_side(sd, e, ngh, nga, rh, ra)
                cur_g = wp(e, gh, ga, rh, ra); wi_g = wp(e, ngh, nga, rh, ra)
                who = re.search(r'\.\s+([^.(]+?)\s+\(', txt) or re.search(r'^([^.(]+?)\s+\(', txt); who = who.group(1).strip() if who else 'Shot'
                verb = 'hits the woodwork' if 'hits the' in low else ('is saved' if 'saved' in low else 'goes wide')
                if cat == 'Penalty miss': verb = 'misses a penalty'
                sab = H['team']['abbreviation'] if sd == 'home' else A['team']['abbreviation']
                down = (ga - gh) if sd == 'home' else (gh - ga)
                sit = 'level' if down == 0 else (f"down {abs(down)}" if down > 0 else f"up {abs(down)}")
                chances.append({'id': f"m{ev['id']}_{idx}", 'x': x, 'clock': disp, 'team': sab, 'state': f"{sit} at {disp}",
                                't': f"{who}'s chance {verb}", 'ctx': f"{'Level' if down == 0 else ('Down ' + str(abs(down)) if down > 0 else 'Up ' + str(abs(down)))} · {disp}",
                                'end': txt, 'peak': round(cur, 1), 'endwp': round(cur, 1),
                                'whatif': {'wp': round(wi), 'desc': 'If it goes in', 'est': True}, 'peak_g': round(cur_g, 1), 'wi_g': round(wi_g, 1), 'score': (wi - cur) * q, 'gain': round(wi - cur)})
        cl = 'Goal' if cat in ('Goal', 'Penalty', 'Own goal') else (cat or ('Chance' if low.startswith('attempt') else 'Play'))
        log.append({'id': f"l{ev['id']}_{idx}", 'x': x, 'c': disp, 'txt': txt, 'cat': cl, 'sw': round(after - before)})
    live = ev['status']['type']['state'] == 'in'
    if live:
        sclock = ev['status'].get('displayClock') or ''
        now_e = elapsed(sclock, 'Second Half' if (ev['status'].get('period') or 1) >= 2 else '') if minute(sclock) else (45 + add1 if 'HT' in (ev['status']['type'].get('shortDetail') or '') else last_e)
        now_e = max(now_e, last_e)
        while last_e < min(now_e, TOT):
            last_e += 1; path.append([round(min(1, last_e / TOT), 4), round(wp(last_e, gh, ga, rh, ra), 1)])
    else:
        while last_e < TOT:
            last_e += 1; path.append([round(min(1, last_e / TOT), 4), round(wp(min(last_e, TOT), gh, ga, rh, ra), 1)])
        path[-1][1] = 100.0 if (gh > ga) == (T == 'home') and gh != ga else (0.0 if gh != ga else path[-1][1])
    if not path: path = [[0, round(wp(0, 0, 0, 0, 0), 1)]]
    for m in moments: m['ctx'] = None
    moments = [m for m in moments if abs(m['after'] - m['before']) >= 5]
    chances.sort(key=lambda c: -c['score'])
    pick = []
    for side in (H['team']['abbreviation'], A['team']['abbreviation']):
        pick += [c for c in chances if c['team'] == side and c['gain'] >= 6][:2]
    pick.sort(key=lambda c: c['x'])
    missed = [dict({k: v for k, v in c.items() if k not in ('score',)}) for c in pick]
    for m in missed: m['left'] = None
    note = NOTES.get(f"soc_{ev['id']}") or {}
    for ed in note.get('moments', []):
        for m in moments:
            if m['clock'] == ed['clock']:
                m['t'] = ed['t']; m['d'] = ed.get('d', m['d']); m['cat'] = ed.get('cat', m['cat']); m['src'] = 'editorial'
    def score_at(e0):
        sh = sa = 0
        for c in com:
            t0 = c.get('text', '')
            if (t0.startswith('Goal!') or t0.startswith('Own Goal')) and elapsed(c['time']['displayValue'], t0) < e0:
                sc = re.search(r'Goal! .*?(\d+), .*? (\d+)\.', t0)
                if sc: sh, sa = int(sc.group(1)), int(sc.group(2))
        return sh, sa
    for k, c in enumerate(note.get('calls', [])):
        e0 = elapsed(c['clock']); sh, sa = score_at(e0); side = 'home' if c['team'] == H['team']['abbreviation'] else 'away'
        ns = (sh + 1, sa) if side == 'home' else (sh, sa + 1); P = c.get('p', .78)
        cur = wp_side(side, e0, sh, sa, 0, 0); exp = P * wp_side(side, e0, *ns, 0, 0) + (1 - P) * cur
        cg = wp(e0, sh, sa, 0, 0); wg = P * wp(e0, *ns, 0, 0) + (1 - P) * cg
        missed.append({'id': f"c{ev['id']}_{k}", 'x': round(min(1, e0 / TOT), 4), 'clock': c['clock'], 'team': c['team'], 'state': c.get('state', f"{sh}–{sa} at {c['clock']}"),
                       't': c['t'], 'ctx': c.get('ctx', ''), 'end': c.get('d', ''), 'peak': round(cur, 1), 'endwp': round(cur, 1),
                       'whatif': {'wp': round(exp), 'desc': "If it's given", 'label': "if it's given", 'est': True}, 'peak_g': round(cg, 1), 'wi_g': round(wg, 1),
                       'gain': round(exp - cur), 'left': None, 'call': True, 'src': 'editorial'})
    missed.sort(key=lambda m: m['x'])
    ht = round((45 + add1) / TOT, 3)
    ac, bc = lighten(A['team'].get('color', '')), lighten(H['team'].get('color', ''))
    return {'id': f"soc_{ev['id']}", 'sport': 'Soccer', 'league': LNAME.get(lg, lg), 'a': A['team']['abbreviation'], 'an': A['team']['shortDisplayName'],
            'b': H['team']['abbreviation'], 'bn': H['team']['shortDisplayName'], 'as': as_, 'bs': hs, 'state': 'in' if live else 'post', 'clock': (ev['status']['type'].get('shortDetail') or ev['status'].get('displayClock') or '') if live else 'FT', 'team': team, 'start': ev.get('date'),
            'kind': 'soc', 'wpsrc': 'model', 'ac': ac, 'bc': bc, 'ticks': [[0, 'KO'], [ht, 'HT'], [1, 'FT']], 'path': path, 'moments': moments,
            'missed': missed, 'log': log[::-1][:400], 'prior': [round(lh, 2), round(la, 2)],
            'source': {'name': 'ESPN match events · Flip model', 'url': f"https://www.espn.com/soccer/match/_/gameId/{ev['id']}"}}

def pre_game(ev, lg):
    comp = ev['competitions'][0]
    H = [c for c in comp['competitors'] if c['homeAway'] == 'home'][0]; A = [c for c in comp['competitors'] if c['homeAway'] == 'away'][0]
    return {'id': f"soc_{ev['id']}", 'sport': 'Soccer', 'league': LNAME.get(lg, lg), 'a': A['team']['abbreviation'], 'an': A['team'].get('shortDisplayName') or A['team']['abbreviation'],
            'b': H['team']['abbreviation'], 'bn': H['team'].get('shortDisplayName') or H['team']['abbreviation'], 'as': '', 'bs': '', 'state': 'pre',
            'clock': ev['status']['type'].get('shortDetail', ''), 'start': ev.get('date'), 'team': H['team']['abbreviation'], 'kind': 'soc', 'wpsrc': 'model',
            'ac': lighten(A['team'].get('color', '')), 'bc': lighten(H['team'].get('color', '')), 'ticks': [[0, 'KO'], [.5, 'HT'], [1, 'FT']], 'path': [], 'moments': [], 'missed': [], 'log': [],
            'source': {'name': 'ESPN', 'url': f"https://www.espn.com/soccer/match/_/gameId/{ev['id']}"}, 'pre_wp': pre_odds(comp, H, A)}
def pre_odds(comp, H, A):
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

games = []
for lg in LEAGUES:
    sb = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={DATE}", f"sb_{lg}_{DATE}.json")
    for ev in sb.get('events', []):
        st = ev['status']['type']['state']
        if st == 'pre':
            try: games.append(pre_game(ev, lg))
            except Exception as e: print('skip pre', lg, ev['id'], e)
            continue
        try: games.append(build(ev, lg))
        except Exception as e: print('skip', lg, ev['id'], e)
json.dump(games, open(OUT, 'w'))
for g in games:
    top = max(g['moments'], key=lambda m: abs(m['after'] - m['before']), default=None)
    mi = g['missed'][0] if g['missed'] else None
    print(g['league'][:4], g['a'], g['as'], '@', g['b'], g['bs'], '| flip', (top['clock'], top['t'], top['before'], '->', top['after']) if top else None,
          '| miss', (mi['clock'], mi['team'], mi['t'][:40], mi['peak'], '->', mi['whatif']['wp']) if mi else None)
print(len(games), 'games')
