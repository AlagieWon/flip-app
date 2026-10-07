"""Pull live NFL + MLB games from ESPN's public scoreboard/summary JSON and auto-detect turning points.
Writes livefeed.json: {updatedAt, games:[...]}."""
import json, re, sys, subprocess, datetime, os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from wpmodel import wp_bat, code as bcode, single as bsingle
OUT=sys.argv[1]
TMP=os.path.join(os.path.dirname(OUT),'live'); os.makedirs(TMP,exist_ok=True)
def get(url,name):
    p=os.path.join(TMP,name)
    for k in range(3):
        if subprocess.run(['curl','-sS','--max-time','20',url,'-o',p]).returncode==0: break
    else: raise SystemExit('fetch failed: '+url)
    return json.load(open(p))
# Human editor layer: hand-written headlines for auto-detected plays (keyed by ESPN play id)
EDITOR=json.load(open(os.path.join(os.path.dirname(OUT),'editor.json'))) if os.path.exists(os.path.join(os.path.dirname(OUT),'editor.json')) else {}
ROUTINE=('Delay of Game','False Start','Encroachment','Illegal Formation','Neutral Zone')
def first(s): return re.split(r'(?<!\b[A-Z])(?<!\bJr)(?<!\bSt)\.(?=\s|$)',s)[0].strip()
def nfl_head(t,cat):
    if cat=='Replay':
        m=re.search(r'(\w[\w ]*?) challenged the (.*?) ruling, and the play was (REVERSED|Upheld)',t,re.I)
        if m: return f"{m.group(1)} challenge {'overturns' if m.group(3).upper()=='REVERSED' else 'fails on'} the {m.group(2)} call"
        return 'Replay review changes the call'
    if cat=='Flag':
        m=re.search(r'PENALTY on (\w+)-([\w\.\' -]+?), ([A-Za-z \-/]+?), (\d+) yards',t)
        if m: return f"{m.group(3)} on {m.group(2)} ({m.group(1)})"+(' wipes out the play' if 'No Play' in t else '')
        m=re.search(r'PENALTY on (\w+), ([A-Za-z \-/]+?), (\d+) yards',t)
        if m: return f"{m.group(2)} on {m.group(1)}"
    if cat=='Turnover':
        if 'INTERCEPT' in t: return first(t)
        m=re.search(r'FUMBLES \(([^)]+)\), RECOVERED by (\w+)-([\w\. ]+)',t)
        if m: return f"Fumble forced by {m.group(1)}, recovered by {m.group(3)} ({m.group(2)})"
    return first(re.sub(r'^\([^)]*\)\s*','',t))[:110]
def pick(cands,n=12):
    [c.__setitem__('i',i) for i,c in enumerate(cands)]; cands.sort(key=lambda c:-c['score']); top=cands[:n]; top.sort(key=lambda c:(c['x'],c['i']))
    for c in top: c.pop('score',None); c.pop('i',None)
    return top
def nfl(ev):
    d=get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={ev['id']}",f"nfl_{ev['id']}.json")
    comp=ev['competitions'][0]; home=[c for c in comp['competitors'] if c['homeAway']=='home'][0]; away=[c for c in comp['competitors'] if c['homeAway']=='away'][0]
    wp={w['playId']:w['homeWinPercentage'] for w in d.get('winprobability',[])}
    dr=d.get('drives',{}); seen=set(); plays=[]
    for x in dr.get('previous',[])+([dr['current']] if dr.get('current') else []):
        for p in x.get('plays',[]):
            if p['id'] in seen: continue
            seen.add(p['id']); plays.append(p)
    plays.sort(key=lambda p:int(p.get('sequenceNumber',0)))
    path=[[0,round(100-100*d['winprobability'][0]['homeWinPercentage'],1)]] if d.get('winprobability') else [[0,50]]
    cands=[]; prev=path[0][1]; log=[]; slopes=[]
    ids={c['team']['id']:c['team']['abbreviation'] for c in comp['competitors']}
    for p in plays:
        per=p['period']['number']; mm,ss=(p['clock']['displayValue']+':0').split(':')[:2]
        x=min(1,((per-1)*15+15-(int(mm)+int(ss)/60))/60)
        w=wp.get(p['id'])
        if w is None: continue
        after=round(100-100*w,1); before=prev; prev=after; path.append([round(x,4),after]); sw=after-before
        t=p['text']; tl=t.lower(); cat=None; score=abs(sw)
        if 'challenged' in tl or 'reversed' in tl or 'upheld' in tl: cat='Replay'; score+=8
        elif 'replay' in tl: cat='Replay'; score+=3
        elif 'INTERCEPT' in t or ('FUMBLES' in t and 'RECOVERED by' in t and not re.search(r'RECOVERED by (\w+)',t).group(1) in (p.get('start',{}).get('team',{}).get('abbreviation',''),)): cat='Turnover'; score+=4
        elif 'PENALTY' in t and (('No Play' in t and not any(r in t for r in ROUTINE)) or abs(sw)>=3): cat='Flag'; score+=5
        elif 'field goal is no good' in tl or 'blocked' in tl: cat='Missed kick'; score+=3
        elif p.get('scoringPlay') or abs(sw)>=8: cat='Big play'
        if p.get('type',{}).get('text') not in ('Official Timeout','End Period','End of Half','Two-minute warning'): log.append({'id':p['id'],'c':f"Q{per} · {p['clock']['displayValue']}",'txt':re.sub(r'^\([^)]*\)\s*','',t)[:170],'x':round(x,4),'sw':round(sw,1),'cat':cat or '','b':round(before,1),'a':round(after,1),'yd':p.get('statYardage',0),'pos':ids.get(str(p.get('start',{}).get('team',{}).get('id','')),''),'dd':p.get('start',{}).get('downDistanceText','')})
        yd=p.get('statYardage') or 0
        if abs(yd)>=3 and not p.get('scoringPlay') and p.get('type',{}).get('text') in ('Rush','Pass Reception','Sack','Penalty'): slopes.append(abs(sw)/abs(yd))
        if not cat or (cat=='Big play' and abs(sw)<6): continue
        ed=EDITOR.get(p['id'],{})
        cands.append({'id':p['id'],'x':round(x,4),'clock':f"Q{per} · {p['clock']['displayValue']}",'cat':ed.get('cat',cat),'t':ed.get('t',nfl_head(t,cat)),'d':ed.get('d',t[:260]),'before':round(before),'after':round(after),'src':'editor' if ed else 'auto','score':score})
    st=ev['status']
    return {'id':'nfl_'+ev['id'],'sport':'Football','league':'NFL · '+('MNF' if datetime.datetime.fromisoformat(ev['date'].replace('Z','+00:00')).weekday()==0 or True else 'NFL'),
     'a':away['team']['abbreviation'],'an':away['team']['shortDisplayName'],'b':home['team']['abbreviation'],'bn':home['team']['shortDisplayName'],
     'as':int(away.get('score',0)),'bs':int(home.get('score',0)),'state':st['type']['state'],'clock':st['type']['shortDetail'],
     'team':away['team']['abbreviation'],'kind':'fb','ticks':[[0,'Q1'],[.25,'Q2'],[.5,'Q3'],[.75,'Q4']],
     'path':thin(path),'moments':pick(cands),'log':log[::-1][:70],'ypp':round(min(2.5,max(.15,sorted(slopes[-20:])[len(slopes[-20:])//2] if slopes else .5)),3),'source':{'name':'ESPN play-by-play','url':f"https://www.espn.com/nfl/game/_/gameId/{ev['id']}"}}
def thin(path,n=140):
    if len(path)<=n: return path
    step=len(path)/n; return [path[int(i*step)] for i in range(n)]+[path[-1]]
def statcast(ev):
    """MLB Stats API (free): hit data per plate appearance, keyed by (half, inning) -> list of dicts."""
    try:
        dt=datetime.datetime.fromisoformat(ev['date'].replace('Z','+00:00'))-datetime.timedelta(hours=5)
        sch=get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={dt.date().isoformat()}",'mlb_sched.json')
        names={c['team']['displayName'] for c in ev['competitions'][0]['competitors']}
        pk=None
        for d in sch.get('dates',[]):
            for g in d['games']:
                if {g['teams']['away']['team']['name'],g['teams']['home']['team']['name']}==names: pk=g['gamePk']
        if not pk: return {}
        f=get(f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live",f"mlbsc_{pk}.json")
    except SystemExit: return {}
    out={}
    for p in f['liveData']['plays']['allPlays']:
        a=p['about'];hd=None;lp=None
        for e in p.get('playEvents',[]):
            if e.get('hitData'): hd=e['hitData']
            if e.get('isPitch'): lp=e
        fn=p['matchup']['batter']['fullName'].replace(' Jr.','').replace(' II','').split();last=fn[-1]
        out.setdefault(('Bot' if a['halfInning']=='bottom' else 'Top',a['inning']),[]).append({'last':last,'ini':fn[0][0],'event':p['result'].get('event',''),'hd':hd,'lp':lp,'desc':p['result'].get('description',''),'outs':p['count']['outs'],'on':[bool(p['matchup'].get('postOnFirst')),bool(p['matchup'].get('postOnSecond')),bool(p['matchup'].get('postOnThird'))],'as':p['result'].get('awayScore',0),'hs':p['result'].get('homeScore',0),'used':False})
    return out
def bname(t):
    m=re.match(r'^((?:[A-Z]\. )?[^ ]+(?: Jr\.)?)',t); return m.group(1) if m else t.split()[0]
def sc_match(SC,half,inn,t):
    m=re.match(r'^([A-Z])\. ',t)
    for c in SC.get((half,inn),[]):
        if not c['used'] and c['last'].lower() in t.lower() and (not m or m.group(1)==c['ini']): c['used']=True; return c
    return None
def zone_miss(lp):
    """Inches outside (+) or inside (-) the rulebook zone for a pitch, using Statcast location. Ball radius included."""
    try:
        pd=lp['pitchData'];co=pd['coordinates'];x,z=co['pX'],co['pZ'];top,bot=pd['strikeZoneTop'],pd['strikeZoneBottom']
    except (KeyError,TypeError): return None
    r=0.121;out=max(abs(x)-(0.7083+r),z-(top+r),(bot-r)-z)
    if out<0: out=max(out,-min((0.7083+r)-abs(x),(top+r)-z,z-(bot-r)))
    return out*12
def suggest(c,t):
    """Returns (tag, context line). Only fires when the text undersells the play."""
    tl=t.lower();hd=(c or {}).get('hd') or {};lp=(c or {}).get('lp')
    ev=(c or {}).get('event','').lower(); dist=hd.get('totalDistance') or 0; spd=hd.get('launchSpeed') or 0;la=hd.get('launchAngle') or 0
    if ('flyout' in ev or 'lineout' in ev or 'flied out' in tl or 'lined out' in tl) and dist>=330 and spd>=97 and 20<=la<=40:
        return 'Robbed',f"{spd:.1f} mph · {dist:.0f} ft · caught near the wall"
    code=((lp or {}).get('details') or {}).get('call',{}).get('code')
    chal=' challenged' in ((c or {}).get('desc','')).lower()
    if lp and code=='C' and ('strikeout' in ev or 'struck out looking' in tl):
        m=zone_miss(lp)
        if m is not None and m>=1.0: return 'Missed call',f"Strike 3 was {m:.1f} in. off the zone"+(" · challenge lost" if chal else "")
        if m is not None and m>-1.5: return None,f"Strike 3 caught the edge by {abs(m):.1f} in."+(" · challenge upheld" if chal else "")
    if lp and code=='B' and ev=='walk':
        m=zone_miss(lp)
        if m is not None and m<=-1.0: return 'Missed call',f"Ball 4 was {abs(m):.1f} in. inside the zone"
    if ' error' in tl: return 'Error',None
    return None,None
def mlb(ev):
    d=get(f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={ev['id']}",f"mlb_{ev['id']}.json")
    comp=ev['competitions'][0]; home=[c for c in comp['competitors'] if c['homeAway']=='home'][0]; away=[c for c in comp['competitors'] if c['homeAway']=='away'][0]
    wp={w['playId']:w['homeWinPercentage'] for w in d.get('winprobability',[])}
    SC=statcast(ev)
    w0=(d.get('winprobability') or [{}])[0].get('homeWinPercentage',.5); path=[[0,round(100-100*w0,1)]]; prev=path[0][1]; cands=[]; log=[]
    for p in d.get('plays',[]):
        inn=p.get('period',{}).get('number',1); bot=p.get('period',{}).get('type','Top')=='Bottom'
        outs=p.get('outs',0) or 0; x=min(1,((inn-1)*2+(1 if bot else 0)+min(outs,3)/3)/18)
        t=p.get('text',''); tl=t.lower(); w=wp.get(p['id'])
        before=prev
        if w is not None: after=round(100-100*w,1); prev=after; path.append([round(x,4),after])
        else: after=prev
        sw=after-before; cat=None; score=abs(sw)
        if 'challenged' in tl or 'overturned' in tl or 'confirmed' in tl and 'call' in tl: cat='Replay'; score+=8
        elif 'ejected' in tl: cat='Argument'; score+=8
        elif "interference" in tl or 'balk' in tl or 'obstruction' in tl: cat='Rule'; score+=5
        elif ' error by ' in tl: cat='Error'; score+=4
        elif p.get('scoringPlay') or abs(sw)>=10: cat='Big play'
        if p.get('type',{}).get('text')!='Play Result' and cat!='Argument': continue
        c=sc_match(SC,'Bot' if bot else 'Top',inn,t); hd=(c or {}).get('hd') or {}; sug,ctx=suggest(c,t)
        ent={'id':p['id'],'c':('Bot ' if bot else 'Top ')+str(inn),'txt':t[:170],'x':round(x,4),'sw':round(sw,1),'cat':cat or '','b':round(before,1),'a':round(after,1)}
        if hd.get('totalDistance'): ent['hd']={'ft':round(hd['totalDistance']),'mph':round(hd.get('launchSpeed') or 0,1),'la':round(hd.get('launchAngle') or 0)}
        if sug: ent['sug']=sug
        if ctx: ent['ctx']=ctx
        log.append(ent)
        if sug=='Robbed' and not cat:
            cat='Near-homer'; score+=10
            ed=EDITOR.get(p['id'],{})
            cands.append({'id':p['id'],'x':round(x,4),'clock':('Bot ' if bot else 'Top ')+str(inn),'cat':'Near-homer','t':ed.get('t',bname(t)+"'s "+str(ent['hd']['ft'])+"-ft drive is caught"),'d':ed.get('d',f"{t} {ent['hd']['mph']} mph off the bat, {ent['hd']['la']}° launch, {ent['hd']['ft']} ft. A few more feet and it's gone."),'before':round(before),'after':round(after),'src':'data','sug':'Robbed','ctx':ctx,'hd':ent['hd'],'score':score})
            continue
        if not cat or (cat=='Big play' and abs(sw)<6 and not p.get('scoringPlay')): continue
        ed=EDITOR.get(p['id'],{})
        cands.append({'id':p['id'],'x':round(x,4),'clock':('Bot ' if bot else 'Top ')+str(inn),'cat':ed.get('cat',cat),'t':ed.get('t',first(t)[:110]),'d':ed.get('d',t[:260]),'before':round(before),'after':round(after),'src':'editor' if ed else 'auto','score':score,**({'sug':sug} if sug else {}),**({'ctx':ctx} if ctx else {})})
    # ---- missed opportunities: a half-inning where the batting team had the tying/go-ahead run in scoring position and stranded it
    missed=[]
    for (half,inn),pas in SC.items():
        ents=[e for e in log if e['c']==f"{half} {inn}"]
        if not pas or not ents: continue
        bat_home=half=='Bot'; done=pas[-1]['outs']>=3
        if not done: continue
        start=(pas[0]['as'],pas[0]['hs']) if False else None
        peak=None;pk=-1
        for k,pa in enumerate(pas):
            if pa['outs']>=3: continue
            on=pa['on'];risp=on[1]+on[2];n=sum(on)
            mine=pa['hs'] if bat_home else pa['as'];theirs=pa['as'] if bat_home else pa['hs'];deficit=theirs-mine
            if risp==0 or deficit<0 or n+1<deficit: continue   # need tying run on base or at the plate, team not already ahead
            score=risp*2+n+(3 if n==3 else 0)-pa['outs']*1.5
            if score>pk: pk=score;peak=(k,pa,deficit,n,risp)
        if not peak or pk<3: continue
        k,pa,deficit,n,risp=peak
        end=pas[-1];endmine=end['hs'] if bat_home else end['as'];endtheirs=end['as'] if bat_home else end['hs']
        if endmine-endtheirs>=(0 if deficit>0 else 1): continue   # reached the goal (tie when behind, lead when tied): not missed
        left=sum(pas[-2]['on']) if len(pas)>1 else 0
        team_ab=home['team']['abbreviation'] if bat_home else away['team']['abbreviation']
        persp=lambda v: v if team_ab==away['team']['abbreviation'] else round(100-v,1)   # path is away-team perspective
        wps=[persp(e['b']) for e in ents]+[persp(ents[-1]['a'])]
        peakwp=max(wps[:-1]); endwp=wps[-1]
        state=("Bases loaded" if n==3 else " & ".join(b for b,o in zip(["1st","2nd","3rd"],pa['on']) if o).join(["Runners on ",""]) if n>1 else f"Runner on {['1st','2nd','3rd'][pa['on'].index(True)]}")+f", {pa['outs']} out"+("" if pa['outs']==1 else "s")
        what="tying run" if deficit>=1 and n>=deficit else "go-ahead run" if deficit==0 else "tying run"
        what_on="at the plate" if n+1==deficit else ("on base" if n>=deficit else "")
        x_end=max(e['x'] for e in ents)
        # what could have been (estimate): a clean single at the peak state, as a delta on ESPN's real number
        runs,on2,o2=bsingle(pa['on'],pa['outs'])
        base=wp_bat(inn,half,pa['outs'],bcode(pa['on']),-deficit); alt=wp_bat(inn,half,o2,bcode(on2),-deficit+runs)
        wi=max(1,min(99,round(peakwp+(alt-base)*100))); nd=runs-deficit
        wdesc=(f"{'A '+str(runs)+'-run' if runs>1 else 'An RBI' if runs==1 else 'A'} single "+("takes the lead" if nd>0 else "ties it" if nd==0 else f"cuts it to {abs(nd)}"))
        missed.append({'id':'miss_'+half+str(inn),'x':round(x_end,4),'clock':f"{half} {inn}",'team':team_ab,'state':state,'left':left,
            't':f"{team_ab} strand {'the bases loaded' if n==3 else str(left)+' on'} in the {inn}{'st' if inn==1 else 'nd' if inn==2 else 'rd' if inn==3 else 'th'}",
            'ctx':f"{state} · {what} {('in scoring position' if risp else what_on)}".strip(),
            'end':ents[-1]['txt'][:120],'peak':peakwp,'endwp':endwp,'whatif':{'wp':wi,'desc':wdesc,'est':True}})
    st=ev['status']; note=(d.get('header',{}).get('gameNote') or 'MLB')
    # merge duplicate catcher-interference style pairs (same x, same cat)
    ded={}; 
    for c in cands: ded.setdefault((c['x'],c['cat']),c) if c['src']=='auto' else ded.__setitem__((c['x'],c['cat']),c)
    return {'id':'mlb_'+ev['id'],'sport':'Baseball','league':'MLB · '+note,'a':away['team']['abbreviation'],'an':away['team']['shortDisplayName'],'b':home['team']['abbreviation'],'bn':home['team']['shortDisplayName'],
     'as':int(away.get('score',0)),'bs':int(home.get('score',0)),'state':st['type']['state'],'clock':st['type']['shortDetail'],'team':away['team']['abbreviation'],'kind':'bb',
     'ticks':[[0,'1st'],[1/3,'4th'],[2/3,'7th'],[8/9,'9th']],'path':thin(path),'moments':pick(list(ded.values())),'missed':missed,'log':log[::-1][:70],
     'source':{'name':'ESPN play-by-play','url':f"https://www.espn.com/mlb/game/_/gameId/{ev['id']}"}}
games=[]
WANT=set(sys.argv[2:])  # optional: event ids to keep even after final
for sport,fn in (('football/nfl',nfl),('baseball/mlb',mlb)):
    sb=get(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/scoreboard",sport.replace('/','_')+'.json')
    for ev in sb.get('events',[]):
        if ev['status']['type']['state']=='in' or ev['id'] in WANT:
            games.append(fn(ev))
    # pinned games that rolled off today's scoreboard: check the previous 2 days
    have={g['id'].split('_',1)[1] for g in games}
    for back in (1,2):
        miss=[w for w in WANT if w not in have]
        if not miss: break
        day=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=back)).strftime('%Y%m%d')
        sb2=get(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/scoreboard?dates={day}",sport.replace('/','_')+f'_{day}.json')
        for ev in sb2.get('events',[]):
            if ev['id'] in miss: games.append(fn(ev)); have.add(ev['id'])
if not games and WANT:
    sys.exit('no games found - not overwriting '+OUT)
json.dump({'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),'games':games},open(OUT,'w'))
for g in games:
    print(g['id'],g['a'],g['as'],g['b'],g['bs'],g['clock'],g['state'],'path',len(g['path']))
    for m in g['moments']: print('   ',m['clock'],m['cat'],m['src'],m['before'],'->',m['after'],'|',m['t'],'| id',m['id'])
    for m in g.get('missed',[]): print('   MISSED',m['clock'],m['t'],'|',m['ctx'],'| peak',m['peak'],'end',m['endwp'],'| what-if',m['whatif'],'|',m['end'])
print(os.path.getsize(OUT),'bytes')
