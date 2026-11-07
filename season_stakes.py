"""Season stakes: how a goal changes a team's season (top 4 / top 6 / relegation).
Simulates the rest of the league season many times with a Poisson model whose team strengths are calibrated
to Polymarket's top-4 / top-6 prices, then compares the table WITH the flip goal against the table WITHOUT it.
Pure Python (no numpy) so it runs in the GitHub Action. Called from pull_all.py: enrich(soccer_games, workdir)."""
import json, math, os, random, subprocess, time, datetime

LEAGUES = {  # league display name -> config
    'Premier League': {'espn': 'eng.1', 'pm': {'top4': 'premier-league-top-4-finishers-2026-27', 'top6': 'premier-league-top-6-finishers-2026-27'},
                       'labels': {'top4': 'Top 4', 'top6': 'Top 6', 'rel': 'Relegation'}, 'rel': 3},
}
PM_NAME = {'Tottenham': 'TOT', 'Tottenham Hotspur': 'TOT', 'Arsenal': 'ARS', 'Liverpool': 'LIV', 'Chelsea': 'CHE', 'Brighton': 'BHA', 'Brighton & Hove Albion': 'BHA',
           'Manchester City': 'MNC', 'Manchester United': 'MAN', 'Brentford': 'BRE', 'Aston Villa': 'AVL', 'Bournemouth': 'BOU', 'AFC Bournemouth': 'BOU',
           'Nottingham Forest': 'NFO', 'Newcastle United': 'NEW', 'Newcastle': 'NEW', 'Leeds United': 'LEE', 'Leeds': 'LEE', 'Everton': 'EVE', 'Fulham': 'FUL',
           'Crystal Palace': 'CRY', 'West Ham United': 'WHU', 'Sunderland': 'SUN', 'Ipswich Town': 'IPS', 'Hull City': 'HUL', 'Coventry City': 'COV', 'Wolves': 'WOL',
           'Wolverhampton Wanderers': 'WOL', 'Burnley': 'BUR', 'Leicester City': 'LEI', 'Southampton': 'SOU'}
N_CAL, N_SIM = 1500, 4000

def _get(url, path):
    for _ in range(3):
        if subprocess.run(['curl', '-sS', '--compressed', '--max-time', '25', url, '-o', path], capture_output=True).returncode == 0: break
    try: return json.load(open(path))
    except Exception: return {}

def _league_data(cfg, work):
    lg = cfg['espn']
    st = _get(f'https://site.api.espn.com/apis/v2/sports/soccer/{lg}/standings', os.path.join(work, f'st_{lg}.json'))
    ent = st['children'][0]['standings']['entries']
    S = lambda e, k: {x['name']: x.get('value') for x in e['stats']}.get(k, 0)
    teams = [dict(id=e['team']['id'], ab=e['team']['abbreviation'], pts=S(e, 'points'), gd=S(e, 'pointDifferential'), gp=S(e, 'gamesPlayed')) for e in ent]
    fx = {}
    for t in teams:
        d = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/teams/{t['id']}/schedule?fixture=true", os.path.join(work, f"fx_{lg}_{t['ab']}.json"))
        for e in d.get('events', []):
            c = e['competitions'][0]
            if c.get('status', {}).get('type', {}).get('completed'): continue
            side = {x['homeAway']: x['team']['abbreviation'] for x in c['competitors']}
            fx[e['id']] = (side['home'], side['away'])
    return teams, fx

def _targets(cfg, work):
    out = {}
    for k, slug in cfg['pm'].items():
        try:
            e = _get(f'https://gamma-api.polymarket.com/events?slug={slug}', os.path.join(work, f'pm_{slug}.json'))[0]
            for m in e['markets']:
                if m.get('closed') or 'outcomePrices' not in m: continue
                ab = PM_NAME.get((m.get('groupItemTitle') or '').strip())
                if ab: out.setdefault(k, {})[ab] = float(json.loads(m['outcomePrices'])[0])
        except Exception: pass
    return out

def _dist(lh, la, G=8):
    ph = [math.exp(-lh) * lh ** i / math.factorial(i) for i in range(G)]; pa = [math.exp(-la) * la ** i / math.factorial(i) for i in range(G)]
    outs, cum, c = [], [], 0.0
    for i in range(G):
        for j in range(G):
            c += ph[i] * pa[j]; outs.append((i, j)); cum.append(c)
    return outs, cum

def _simulate(r, teams, fx, n, seed=11):
    """returns list of per-sim (pts list, gd list) increments for remaining fixtures (common random numbers)"""
    rnd = random.Random(seed); ix = {t['ab']: i for i, t in enumerate(teams)}; K = len(teams)
    P = [[0] * K for _ in range(n)]; G = [[0] * K for _ in range(n)]
    base, home = math.log(1.35), 0.12
    for h, a in fx.values():
        if h not in ix or a not in ix: continue
        hi, ai = ix[h], ix[a]
        outs, cum = _dist(math.exp(base + home + r[hi] - r[ai]), math.exp(base + r[ai] - r[hi]))
        res = rnd.choices(outs, cum_weights=cum, k=n)
        for s, (x, y) in enumerate(res):
            if x > y: P[s][hi] += 3
            elif y > x: P[s][ai] += 3
            else: P[s][hi] += 1; P[s][ai] += 1
            G[s][hi] += x - y; G[s][ai] += y - x
    return P, G

def _probs(teams, P, G, pts, gd, rel_n):
    K = len(teams); n = len(P); c4 = [0] * K; c6 = [0] * K; cr = [0] * K
    for s in range(n):
        order = sorted(range(K), key=lambda i: (-(pts[i] + P[s][i]), -(gd[i] + G[s][i]), i))
        for rank, i in enumerate(order):
            if rank < 4: c4[i] += 1
            if rank < 6: c6[i] += 1
            if rank >= K - rel_n: cr[i] += 1
    return {t['ab']: {'top4': c4[i] / n, 'top6': c6[i] / n, 'rel': cr[i] / n} for i, t in enumerate(teams)}

def _calibrate(teams, fx, tg, rel_n):
    lg = lambda p: math.log(min(max(p, .002), .998) / (1 - min(max(p, .002), .998)))
    r = [(t['gd'] / max(t['gp'], 1)) * .15 for t in teams]
    pts = [t['pts'] for t in teams]; gd = [t['gd'] for t in teams]
    for it in range(30):
        P, G = _simulate(r, teams, fx, N_CAL, seed=100 + it); pr = _probs(teams, P, G, pts, gd, rel_n)
        for i, t in enumerate(teams):
            err = [lg(tg[k][t['ab']]) - lg(pr[t['ab']][k]) for k in ('top4', 'top6') if t['ab'] in tg.get(k, {})]
            if err: r[i] += (.1 if it < 20 else .05) * sum(err) / len(err)
        m = sum(r) / len(r); r = [x - m for x in r]
    return r

def enrich(games, work):
    work = os.path.join(work, 'stakes'); os.makedirs(work, exist_ok=True)
    todo = [g for g in games if g.get('league') in LEAGUES and g.get('state') in ('in', 'post') and g.get('moments')]
    if not todo: return 0
    done = 0
    for lname, cfg in LEAGUES.items():
        gs = [g for g in todo if g['league'] == lname]
        if not gs: continue
        cache = os.path.join(work, f"cal_{cfg['espn']}.json")
        teams, fx = _league_data(cfg, work)
        ix = {t['ab']: i for i, t in enumerate(teams)}
        try:
            c = json.load(open(cache))
            if time.time() - c['t'] > 6 * 3600 or set(c['r']) != set(ix): raise ValueError
            r = [c['r'][t['ab']] for t in teams]
        except Exception:
            tg = _targets(cfg, work)
            if not tg.get('top6'): continue
            r = _calibrate(teams, fx, tg, cfg['rel'])
            json.dump({'t': time.time(), 'r': {t['ab']: x for t, x in zip(teams, r)}}, open(cache, 'w'))
        P, G = _simulate(r, teams, fx, N_SIM)
        base_pts = [t['pts'] for t in teams]; base_gd = [t['gd'] for t in teams]
        for g in gs:
            a, b = g['a'], g['b']
            if a not in ix or b not in ix: continue
            eid = g['id'].split('_')[-1]
            counted = eid not in fx and g['state'] == 'post'   # standings already include a finished game
            fa, fb = int(g['as'] or 0), int(g['bs'] or 0)
            flip = max(g['moments'], key=lambda m: abs(m['after'] - m['before']))
            if (flip.get('cat') or '').lower() != 'goal': continue
            scorer = g['team'] if flip['after'] > flip['before'] else (b if g['team'] == a else a)
            wa, wb = (fa - 1, fb) if scorer == a else (fa, fb - 1)
            if min(wa, wb) < 0: continue
            def table(sa, sb):
                pts, gd = base_pts[:], base_gd[:]
                if counted:  # remove the real result first
                    pa_, pb_ = (3, 0) if fa > fb else (0, 3) if fb > fa else (1, 1)
                    pts[ix[a]] -= pa_; pts[ix[b]] -= pb_; gd[ix[a]] -= fa - fb; gd[ix[b]] -= fb - fa
                pa_, pb_ = (3, 0) if sa > sb else (0, 3) if sb > sa else (1, 1)
                pts[ix[a]] += pa_; pts[ix[b]] += pb_; gd[ix[a]] += sa - sb; gd[ix[b]] += sb - sa
                return pts, gd
            with_p = _probs(teams, P, G, *table(fa, fb), cfg['rel']); without_p = _probs(teams, P, G, *table(wa, wb), cfg['rel'])
            rows = []
            for t in (a, b):
                for k in ('top4', 'top6', 'rel'):
                    d = with_p[t][k] - without_p[t][k]
                    rows.append((abs(d), t, k, round(without_p[t][k] * 100), round(with_p[t][k] * 100)))
            items = []
            for t in (scorer, b if scorer == a else a):   # scoring team first, then the team that conceded
                best = max((r_ for r_ in rows if r_[1] == t), default=None)
                if best and best[0] >= .01:
                    good = (best[4] > best[3]) if best[2] != 'rel' else (best[4] < best[3])
                    items.append({'team': t, 'label': cfg['labels'][best[2]], 'before': best[3], 'after': best[4], 'good': good})
            if not items: continue
            flip['stakes'] = {'items': items, 'vs': f"{wa}-{wb}", 'src': 'Season sim · Flip model'}
            done += 1
    return done

if __name__ == '__main__':
    import sys
    gs = json.load(open(sys.argv[1])); gs = gs.get('games', gs) if isinstance(gs, dict) else gs
    t0 = time.time(); n = enrich(gs, os.path.dirname(os.path.abspath(sys.argv[1])))
    for g in gs:
        for m in g.get('moments', []):
            if m.get('stakes'): print(g['a'], g['as'], g['b'], g['bs'], m['clock'], m['t'][:40], m['stakes'])
    print(n, 'games with stakes in', round(time.time() - t0, 1), 's')
