"""Flip post card renderer (7:8, 1400x1600). Floodlight style: black + gold, gold only for the flip.
usage: python3 flip_card.py spec.json out.png
spec = {
  "eyebrow": "NBA MVP · 2026–27", "eyebrow_gold": true, "live": false,   # live=true shows a red dot (use for JUST IN)
  "right": "NOV 5, 2026",
  "big": "+6", "big_unit": "PTS", "big_gold": true,                      # omit big for a headline-only news card
  "headline": "52 points.<br>24 rebounds. 8 blocks.", "headline_xl": false,
  "sub": "Wemby <b>29.5%</b> → <b class='g'>35.5%</b>.",                  # small HTML allowed: <b>, <b class='g'>, <br>
  "series": [{"pts": [[t, pct], ...], "col": "gold"|"grey"|"white", "label": "WEMBY", "fill": true, "dot": true}],
  "ymax": 45, "mark": null, "mark_label": "", "axis": ["OCT 15", "NOV 5"],
  "stats": [["1st", "ATHLETE PARTNER, EVER"]],                            # optional stat row instead of a chart
  "source": "NBA MVP · Polymarket"
}"""
import json, os, re, sys, base64, subprocess, html
GOLD = '#F5C542'; COLS = {'gold': GOLD, 'grey': '#5a5a5a', 'white': '#DDE1E7'}
CACHE = os.path.expanduser('~/.cache/flip_fonts.css')

def fonts():
    if os.path.exists(CACHE): return open(CACHE).read()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
    css = subprocess.run(['curl', '-sS', '-A', ua, 'https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800&family=Bricolage+Grotesque:opsz,wght@12..96,800&family=Geist:wght@500;600;700&family=Geist+Mono:wght@500;700&display=swap'], capture_output=True, text=True).stdout
    out = []
    for sub, b in re.findall(r'/\* (\S+) \*/\s*(@font-face \{.*?\})', css, re.S):
        if sub != 'latin': continue
        url = re.search(r'url\((.*?)\)', b).group(1)
        data = subprocess.run(['curl', '-sS', url], capture_output=True).stdout
        out.append(b.replace(url, 'data:font/woff2;base64,' + base64.b64encode(data).decode()))
    s = '\n'.join(out); os.makedirs(os.path.dirname(CACHE), exist_ok=True); open(CACHE, 'w').write(s); return s

def chart(series, ymax=None, mark=None, mark_label='', W=636, H=200):
    allp = [p for s in series for p in s['pts']]
    t0, t1 = min(p[0] for p in allp), max(p[0] for p in allp)
    ymax = ymax or max(p[1] for p in allp) * 1.15
    X = lambda t: (t - t0) / ((t1 - t0) or 1) * W
    Y = lambda v: 10 + (1 - v / ymax) * (H - 20)
    o = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="overflow:visible"><defs><linearGradient id="gf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{GOLD}" stop-opacity=".26"/><stop offset="1" stop-color="{GOLD}" stop-opacity="0"/></linearGradient></defs><line x1="0" x2="{W}" y1="{H}" y2="{H}" stroke="#222"/>']
    if mark is not None:
        o.append(f'<line x1="{X(mark):.1f}" x2="{X(mark):.1f}" y1="0" y2="{H}" stroke="#3a3a3a" stroke-dasharray="3 5"/><text x="{X(mark)-8:.1f}" y="16" text-anchor="end" font-family="Geist Mono" font-weight="600" font-size="12" fill="#8A919C">{html.escape(mark_label)}</text>')
    for i, s in enumerate(series):
        c = COLS.get(s.get('col', 'white'), s.get('col'))
        d = 'M' + ' L'.join(f'{X(t):.1f} {Y(v):.1f}' for t, v in s['pts'])
        if s.get('fill'): o.append(f'<path d="{d} L{X(s["pts"][-1][0]):.1f} {H} L{X(s["pts"][0][0]):.1f} {H} Z" fill="url(#gf)"/>')
        o.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{3.4 if c == GOLD else 2.6}" stroke-linejoin="round" stroke-linecap="round"/>')
        t, v = s['pts'][-1]
        if s.get('dot', True): o.append(f'<circle cx="{X(t):.1f}" cy="{Y(v):.1f}" r="6" fill="{c}"/>')
        if s.get('label'): o.append(f'<text x="{X(t)-10:.1f}" y="{Y(v)+(-14 if i == len(series)-1 else 24):.1f}" text-anchor="end" font-family="Geist Mono" font-weight="700" font-size="14" fill="{c}">{html.escape(s["label"])}</text>')
    return ''.join(o) + '</svg>'

def render(spec, out):
    css = fonts() + f"""
*{{box-sizing:border-box;margin:0}}body{{width:700px;height:800px;background:#050505;overflow:hidden}}
.c{{position:relative;width:700px;height:800px;overflow:hidden;color:#F2F4F7;font-family:Geist,sans-serif;padding:30px 32px;display:flex;flex-direction:column;background:radial-gradient(520px 420px at 92% 12%,rgba(245,197,66,.13),transparent 70%),#050505}}
.top{{display:flex;justify-content:space-between;align-items:center;font:700 13px 'Geist Mono';letter-spacing:.12em;color:#8A919C}}.top .l{{display:flex;align-items:center;gap:9px;color:#F2F4F7}}.top .l.g{{color:{GOLD}}}.top .l i{{width:10px;height:10px;border-radius:50%;background:#FF4D4D;box-shadow:0 0 12px #FF4D4D}}
.big{{font:800 200px/0.8 'Barlow Condensed';letter-spacing:-.02em;margin-top:34px;display:flex;align-items:flex-end;gap:12px}}.big.g{{color:{GOLD}}}.big small{{font:700 30px 'Barlow Condensed';color:#8A919C;margin-bottom:14px;letter-spacing:.02em}}
.hl{{font:800 46px/1.02 'Bricolage Grotesque';letter-spacing:-.02em;margin-top:26px}}.hl.xl{{font-size:76px;line-height:.98;margin-top:56px}}
.sub{{font:500 18px/1.42 Geist;color:#B4BAC4;margin-top:18px;max-width:610px}}.sub b{{color:#F2F4F7;font-weight:700}}.sub b.g{{color:{GOLD}}}
.ch{{margin-top:auto;margin-bottom:22px}}.ax{{display:flex;justify-content:space-between;font:600 12px 'Geist Mono';color:#6a6f78;margin-top:8px}}
.stat{{display:flex;gap:26px;margin-top:auto;margin-bottom:26px}}.stat div{{border-left:3px solid #262B33;padding-left:14px}}.stat b{{display:block;font:800 52px/1 'Barlow Condensed'}}.stat span{{font:600 12px 'Geist Mono';color:#8A919C;letter-spacing:.06em}}
.ft{{display:flex;align-items:center;justify-content:space-between;font:600 13px 'Geist Mono';color:#8A919C;border-top:1px solid #1c1c1c;padding-top:16px}}.logo{{font:800 26px 'Bricolage Grotesque';color:#F2F4F7;letter-spacing:-.02em}}.logo i{{color:{GOLD};font-style:normal}}"""
    e = html.escape
    b = [f'<div class="top"><span class="l {"g" if spec.get("eyebrow_gold") else ""}">{"<i></i>" if spec.get("live") else ""}{e(spec.get("eyebrow",""))}</span><span>{e(spec.get("right",""))}</span></div>']
    if spec.get('big'): b.append(f'<div class="big {"g" if spec.get("big_gold") else ""}">{e(spec["big"])}{f"<small>{e(spec.get("big_unit",""))}</small>" if spec.get("big_unit") else ""}</div>')
    b.append(f'<div class="hl {"xl" if spec.get("headline_xl") else ""}">{spec["headline"]}</div>')
    if spec.get('sub'): b.append(f'<div class="sub">{spec["sub"]}</div>')
    if spec.get('series'):
        ax = ''.join(f'<span>{e(a)}</span>' for a in spec.get('axis', []))
        b.append(f'<div class="ch">{chart(spec["series"], spec.get("ymax"), spec.get("mark"), spec.get("mark_label",""))}<div class="ax">{ax}</div></div>')
    elif spec.get('stats'):
        b.append('<div class="stat">' + ''.join(f'<div><b>{e(v)}</b><span>{e(l)}</span></div>' for v, l in spec['stats']) + '</div>')
    else:
        b.append('<div style="margin-top:auto"></div>')
    b.append(f'<div class="ft"><span class="logo">flip<i>.</i></span><span>{e(spec.get("source",""))}</span><span>@flippdodds</span></div>')
    page = f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body><div class="c">{"".join(b)}</div></body></html>'
    tmp = out + '.html'; open(tmp, 'w').write(page)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch(); pg = br.new_page(viewport={'width': 700, 'height': 800}, device_scale_factor=2)
        pg.goto('file://' + os.path.abspath(tmp)); pg.wait_for_timeout(400); pg.screenshot(path=out); br.close()
    os.remove(tmp)

if __name__ == '__main__':
    render(json.load(open(sys.argv[1])), sys.argv[2]); print('wrote', sys.argv[2])
