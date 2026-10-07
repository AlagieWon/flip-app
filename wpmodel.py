"""Rough MLB win-expectancy model for what-if estimates.
Half-inning run distributions from base-out state (scoring probability + run expectancy, typical 2010s MLB),
remaining half-innings from the league per-inning distribution. Used only as a DELTA on top of ESPN's real
win chance, never on its own: whatif = espn_now + (model(whatif) - model(now))."""
from functools import lru_cache
RE={0:{'---':.48,'1--':.85,'-2-':1.10,'--3':1.35,'12-':1.44,'1-3':1.78,'-23':1.96,'123':2.29},
    1:{'---':.25,'1--':.51,'-2-':.66,'--3':.95,'12-':.88,'1-3':1.13,'-23':1.35,'123':1.52},
    2:{'---':.10,'1--':.22,'-2-':.32,'--3':.36,'12-':.43,'1-3':.48,'-23':.57,'123':.75}}
P1={0:{'---':.27,'1--':.42,'-2-':.62,'--3':.85,'12-':.62,'1-3':.86,'-23':.84,'123':.87},
    1:{'---':.16,'1--':.27,'-2-':.41,'--3':.66,'12-':.43,'1-3':.66,'-23':.68,'123':.67},
    2:{'---':.07,'1--':.13,'-2-':.22,'--3':.26,'12-':.23,'1-3':.28,'-23':.26,'123':.32}}
INN=[.73,.15,.07,.03,.015,.005]   # runs 0..5 in a fresh half-inning
def dist_state(outs,bases,cap=8):
    if outs>=3: return [1.0]
    re,p=RE[outs][bases],P1[outs][bases]
    lam=max(.01,re/p-1)   # runs beyond the first, given at least one scores
    out=[1-p];pk=__import__('math').exp(-lam)
    for k in range(cap): out.append(p*pk); pk*=lam/(k+1)
    s=sum(out); return [x/s for x in out]
def conv(a,b):
    r=[0]*(len(a)+len(b)-1)
    for i,x in enumerate(a):
        for j,y in enumerate(b): r[i+j]+=x*y
    return r
@lru_cache(None)
def fresh(n):
    d=[1.0]
    for _ in range(n): d=conv(d,INN)
    return tuple(d)
def wp_bat(inning,half,outs,bases,diff):
    """Win probability for the batting team. diff = batting runs - fielding runs, now."""
    bot=half=='Bot'
    cur=dist_state(outs,bases)
    # remaining full half-innings after this one (regulation 9; extras approximated as a coin flip)
    if bot: bat_more=max(0,9-inning); fld_more=max(0,9-inning)
    else:   bat_more=max(0,9-inning); fld_more=max(0,9-inning)+1
    bat=conv(list(cur),list(fresh(bat_more))); fld=list(fresh(fld_more))
    w=t=0.0
    for i,x in enumerate(bat):
        for j,y in enumerate(fld):
            d=diff+i-j
            if d>0: w+=x*y
            elif d==0: t+=x*y
    return w+t*.5
def code(on): return ''.join(c if o else '-' for c,o in zip('123',on))
def single(on,outs):
    """A clean single: runners on 2nd and 3rd score, 1st to 2nd, batter to 1st."""
    runs=int(on[1])+int(on[2]); return runs,[True,on[0],False],outs
