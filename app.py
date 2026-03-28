from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import httpx
import json
import logging
import os
from typing import Optional
from datetime import date as _date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

API_KEY    = os.getenv("API_SPORTS_KEY", "")
API_BASE   = "https://v1.basketball.api-sports.io"

SHEETS_ID  = os.getenv("GOOGLE_SHEETS_ID", "")
SHEETS_TAB = os.getenv("GOOGLE_SHEETS_TAB", "h2h_2025_2026")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

# Leagues — alle relevanten Ligen, später filtern
LEAGUES: dict = {
    120: ("TBL",        "2025-2026"),
    4:   ("ACB",        "2025-2026"),
    6:   ("ABA Liga",   "2025-2026"),
    23:  ("LNB Pro A",  "2025-2026"),
    8:   ("Lega A",     "2025-2026"),
    3:   ("EuroLeague", "2025-2026"),
    2:   ("EuroCup",    "2025-2026"),
    15:  ("BBL",        "2025-2026"),
    11:  ("GBL",        "2025-2026"),
    22:  ("BCL",        "2025-2026"),
    12:  ("NBA",        "2025"),
    5:   ("VTB",        "2025-2026"),
    16:  ("Jeep Elite", "2025-2026"),
    19:  ("NBB",        "2025-2026"),
    38:  ("Sueper Lig", "2025-2026"),
}

_h2h_cache:    dict = {}   # matchup_key -> [ht_total, ...]
_ft_h2h_cache: dict = {}   # matchup_key -> [ft_total, ...]
_seen_ft_ids:  set  = set()
_ws = None


# ─── lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app_: FastAPI):
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="HZ / FT Trading", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─── HTML ─────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading · HZ / FT</title>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;900&family=Barlow:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#07080b;--s1:#0d0e13;--s2:#111218;
  --border:#1a1b24;--border2:#22232f;
  --text:#c9cdd8;--dim:#3e4055;--dim2:#555770;
  --under:#00b4d8;--over:#e63946;--green:#2dc653;--gold:#f4a261;--white:#f0f1f5;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;min-height:100vh;}

.topbar{position:sticky;top:0;z-index:200;background:var(--s1);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:48px;}
.logo{font-family:'Barlow Condensed',sans-serif;font-weight:900;font-size:18px;letter-spacing:4px;color:var(--white);}
.logo em{color:var(--green);font-style:normal;}
.topbar-right{display:flex;align-items:center;gap:10px;}
.live-pill{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--dim2);letter-spacing:1px;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--dim);}
.dot.live{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 1.5s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.icon-btn{background:none;border:1px solid var(--border2);color:var(--dim2);padding:5px 12px;
  font-size:11px;letter-spacing:1px;cursor:pointer;font-family:'Barlow',sans-serif;
  text-transform:uppercase;transition:all .15s;}
.icon-btn:hover{border-color:var(--green);color:var(--green);}

/* signal strip */
.signal-strip{background:var(--s1);border-bottom:2px solid var(--border);padding:12px 16px;
  display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:center;transition:border-bottom-color .3s;}
.signal-strip.under{border-bottom-color:rgba(0,180,216,.5);}
.signal-strip.over {border-bottom-color:rgba(230,57,70,.5);}
.signal-strip.glow {box-shadow:0 4px 20px rgba(45,198,83,.1);}
.sig-dir-big{font-family:'Barlow Condensed',sans-serif;font-weight:900;font-size:52px;
  letter-spacing:3px;line-height:1;color:var(--dim);min-width:120px;text-align:center;}
.sig-dir-big.under{color:var(--under);}
.sig-dir-big.over {color:var(--over);}
.sig-body{display:flex;flex-direction:column;gap:8px;}
.sig-top{display:flex;align-items:center;gap:10px;}
.sig-stufe{font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:700;
  letter-spacing:3px;padding:2px 10px;border:1px solid;}
.st-a{color:var(--green);border-color:rgba(45,198,83,.4);}
.st-b{color:var(--gold); border-color:rgba(244,162,97,.4);}
.st-c{color:var(--dim);  border-color:var(--border);}
.sig-tag{font-size:9px;letter-spacing:2px;color:var(--dim2);text-transform:uppercase;
  padding:2px 8px;background:var(--s2);border:1px solid var(--border);}
.sig-reasons{font-size:10px;line-height:1.9;color:var(--dim2);}
.r-ok{color:var(--green);}
.r-warn{color:var(--gold);}
.r-bad{color:var(--over);}
.sig-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;}
.ss{background:var(--s2);border:1px solid var(--border);padding:8px 6px;text-align:center;}
.ss-v{font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:700;color:var(--white);}
.ss-v.pos{color:var(--under);}
.ss-v.neg{color:var(--over);}
.ss-v.gold{color:var(--gold);}
.ss-l{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);margin-top:1px;}

/* tabs */
.tabs{display:flex;border-bottom:1px solid var(--border);background:var(--s1);}
.tab{padding:12px 24px;font-size:11px;letter-spacing:3px;text-transform:uppercase;
  cursor:pointer;color:var(--dim2);border-bottom:2px solid transparent;transition:all .15s;user-select:none;}
.tab:hover{color:var(--text);}
.tab.active{color:var(--white);border-bottom-color:var(--green);}
.tab-content{display:none;}
.tab-content.active{display:block;}

.main-grid{display:grid;grid-template-columns:1fr 1fr;gap:0;}
.panel{padding:14px;border-right:1px solid var(--border);}
.panel:last-child{border-right:none;}
.sec{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--dim);
  margin-bottom:10px;display:flex;align-items:center;gap:8px;}
.sec::after{content:'';flex:1;height:1px;background:var(--border);}

/* manual form */
.manual-toggle{background:none;border:1px dashed var(--border2);color:var(--dim2);width:100%;
  padding:10px;font-size:10px;letter-spacing:2px;text-transform:uppercase;cursor:pointer;
  font-family:'Barlow',sans-serif;margin-bottom:8px;transition:all .15s;}
.manual-toggle:hover{border-color:var(--dim);color:var(--text);}
.manual-form{display:none;background:var(--s2);border:1px solid var(--border);padding:14px;margin-bottom:8px;}
.manual-form.open{display:block;}
.mf-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;}
.mf-inp{display:flex;flex-direction:column;gap:3px;}
.mf-inp label{font-size:9px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.mf-inp input{background:var(--bg);border:1px solid var(--border2);color:var(--white);
  font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:700;padding:6px 8px;outline:none;}
.mf-inp input:focus{border-color:var(--green);}
.checks-row{display:flex;gap:14px;margin-bottom:8px;flex-wrap:wrap;}
.chk{display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none;}
.chk-box{width:14px;height:14px;border:1px solid var(--border2);background:var(--bg);
  display:flex;align-items:center;justify-content:center;font-size:9px;}
.chk.on .chk-box{background:var(--over);border-color:var(--over);color:#fff;}
.chk-lbl{font-size:10px;color:var(--dim2);}
.chk.on .chk-lbl{color:var(--text);}
.btn-calc{width:100%;background:var(--white);border:none;color:var(--bg);
  font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:900;
  letter-spacing:4px;padding:12px;cursor:pointer;text-transform:uppercase;}
.btn-calc:hover{background:#dde1f0;}

/* game cards */
.games-wrap{display:flex;flex-direction:column;gap:2px;}
.game-card{background:var(--s2);border:1px solid var(--border);cursor:pointer;
  display:grid;grid-template-columns:3px 1fr;transition:border-color .15s;}
.game-card:hover{border-color:var(--border2);}
.game-card.selected{border-color:var(--dim2);}
.game-card.sig-under{border-color:rgba(0,180,216,.4);}
.game-card.sig-over {border-color:rgba(230,57,70,.4);}
.game-card.sig-a    {box-shadow:0 0 12px rgba(45,198,83,.1);}
.ft-card{background:var(--s2);border:1px solid var(--border);cursor:pointer;
  display:grid;grid-template-columns:3px 1fr;margin-bottom:2px;transition:border-color .15s;}
.ft-card:hover{border-color:var(--border2);}
.ft-card.selected{border-color:var(--dim2);}
.ft-card.sig-under{border-color:rgba(0,180,216,.4);}
.ft-card.sig-over {border-color:rgba(230,57,70,.4);}
.ft-card.sig-a    {box-shadow:0 0 12px rgba(45,198,83,.1);}
.card-stripe{width:3px;}
.sig-under .card-stripe{background:var(--under);}
.sig-over  .card-stripe{background:var(--over);}
.sig-a     .card-stripe{background:var(--green);}
.card-body,.ft-body{padding:10px 12px;}
.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}
.card-league{font-size:9px;letter-spacing:1.5px;color:var(--dim2);text-transform:uppercase;}
.card-status{font-size:9px;color:var(--gold);}
.card-teams{display:grid;grid-template-columns:1fr auto 1fr;gap:4px;align-items:center;margin-bottom:8px;}
.card-team{font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700;color:var(--white);}
.card-team.away{text-align:right;}
.score-num{font-family:'Barlow Condensed',sans-serif;font-size:20px;font-weight:900;color:var(--white);text-align:center;}
.score-q1{font-size:9px;color:var(--dim2);margin-top:1px;text-align:center;}
.card-stats-row{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;margin-bottom:6px;}
.cs{background:var(--bg);padding:5px 4px;text-align:center;}
.cs-val{font-family:'Barlow Condensed',sans-serif;font-size:14px;font-weight:700;color:var(--text);}
.cs-lbl{font-size:7px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);margin-top:1px;}
.card-bot{display:flex;justify-content:space-between;align-items:center;padding-top:6px;border-top:1px solid var(--border);}
.card-sig-badge{font-size:9px;font-weight:700;letter-spacing:1.5px;padding:2px 7px;border:1px solid;}
.card-sig-badge.under{color:var(--under);border-color:rgba(0,180,216,.3);}
.card-sig-badge.over {color:var(--over); border-color:rgba(230,57,70,.3);}
.card-sig-badge.skip,.card-sig-badge.none{color:var(--dim);border-color:var(--border);}
.card-stufe-badge{font-size:9px;font-weight:700;padding:2px 7px;}
.card-stufe-badge.a{background:var(--green);color:var(--bg);}
.card-stufe-badge.b{background:var(--gold);color:var(--bg);}
.card-stufe-badge.c{color:var(--dim);}
.card-inputs,.ft-card-inputs{display:none;padding:10px 12px;border-top:1px solid var(--border);background:var(--s1);}
.card-inputs.open,.ft-card-inputs.open{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;}
.inp-group{display:flex;flex-direction:column;gap:3px;}
.inp-group label{font-size:8px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.inp-group input{background:var(--bg);border:1px solid var(--border2);color:var(--white);
  font-family:'Barlow Condensed',sans-serif;font-size:16px;font-weight:600;
  padding:5px 7px;outline:none;width:100%;}
.inp-group input:focus{border-color:var(--under);}
.calc-mini{grid-column:1/-1;background:var(--white);border:none;
  font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:900;
  letter-spacing:3px;padding:8px;cursor:pointer;text-transform:uppercase;color:var(--bg);}
.calc-mini:hover{background:#dde1f0;}
.h2h-note{font-size:9px;color:var(--dim2);letter-spacing:.5px;}
.h2h-note.found{color:var(--green);}
.today-card{background:var(--s2);border:1px solid var(--border);display:grid;
  grid-template-columns:3px 1fr;margin-bottom:2px;}
.today-body{padding:8px 12px;}
.today-top{display:flex;justify-content:space-between;margin-bottom:4px;}
.today-league{font-size:9px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.today-status{font-size:9px;}
.today-teams{display:grid;grid-template-columns:1fr auto 1fr;gap:4px;align-items:center;}
.today-team{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;color:var(--white);}
.today-team.away{text-align:right;}
.today-score{text-align:center;font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:900;color:var(--white);}
.today-q{font-size:8px;color:var(--dim2);margin-top:1px;text-align:center;}
.empty{text-align:center;padding:32px 14px;color:var(--dim);border:1px dashed var(--border);font-size:11px;line-height:2.2;}

@media(max-width:700px){
  .main-grid{grid-template-columns:1fr;}
  .panel{border-right:none;border-bottom:1px solid var(--border);}
  .signal-strip{grid-template-columns:1fr;}
  .sig-dir-big{font-size:36px;min-width:unset;}
}
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">HZ / <em>FT</em></div>
  <div class="topbar-right">
    <div class="live-pill"><div class="dot" id="liveDot"></div><span id="liveLabel">OFFLINE</span></div>
    <button class="icon-btn" id="refreshBtn" onclick="loadLive()">⟳ LIVE</button>
  </div>
</div>

<div class="signal-strip" id="signalStrip">
  <div class="sig-dir-big" id="sigDir">—</div>
  <div class="sig-body">
    <div class="sig-top">
      <span class="sig-stufe st-c" id="sigStufe">— —</span>
      <span class="sig-tag" id="sigTag">HZ</span>
    </div>
    <div class="sig-stats">
      <div class="ss"><div class="ss-v" id="ssProj">—</div><div class="ss-l">Proj</div></div>
      <div class="ss"><div class="ss-v" id="ssBuf">—</div><div class="ss-l">Buffer</div></div>
      <div class="ss"><div class="ss-v" id="ssTime">—</div><div class="ss-l">Zeit</div></div>
      <div class="ss"><div class="ss-v" id="ssFouls">—</div><div class="ss-l">Fouls</div></div>
    </div>
    <div class="sig-reasons" id="sigReasons">Spiel wählen oder manuell eingeben</div>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('hz')">HZ</div>
  <div class="tab" onclick="switchTab('ft')">FT</div>
</div>

<!-- HZ TAB -->
<div class="tab-content active" id="tab-hz">
  <div class="main-grid">
    <div class="panel">
      <button class="manual-toggle" onclick="toggleManual('hz')">+ Manuell (HZ)</button>
      <div class="manual-form" id="manualHz">
        <div class="mf-grid">
          <div class="mf-inp"><label>H2H Ø HZ</label><input type="number" id="hH2H" placeholder="96.5" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Bookie Line</label><input type="number" id="hLine" placeholder="91.5" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Q1 Total</label><input type="number" id="hQ1" placeholder="52" inputmode="numeric"></div>
          <div class="mf-inp"><label>Q2 aktuell</label><input type="number" id="hQ2" placeholder="28" inputmode="numeric"></div>
          <div class="mf-inp"><label>Q2 Zeit (Min)</label><input type="number" id="hTimer" placeholder="4" min="0" max="10" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Fouls gesamt</label><input type="number" id="hFouls" placeholder="5" inputmode="numeric"></div>
          <div class="mf-inp"><label>FT% Ø (opt.)</label><input type="number" id="hFT" placeholder="—" inputmode="numeric"></div>
          <div class="mf-inp"><label>FG% (opt.)</label><input type="number" id="hFG" placeholder="—" inputmode="numeric"></div>
        </div>
        <div class="checks-row">
          <div class="chk" id="chkDrop" onclick="this.classList.toggle('on')"><div class="chk-box">✓</div><span class="chk-lbl">Linie fällt drastisch (≥8)</span></div>
          <div class="chk" id="chkRise" onclick="this.classList.toggle('on')"><div class="chk-box">✓</div><span class="chk-lbl">Linie steigt</span></div>
        </div>
        <button class="btn-calc" onclick="calcManualHz()">▶ HZ SIGNAL</button>
      </div>
      <div class="sec">Live · Halbzeit / Q2</div>
      <div class="games-wrap" id="gamesWrap">
        <div class="empty">⟳ Klicke LIVE um Halbzeit-Spiele zu laden</div>
      </div>
    </div>
    <div class="panel">
      <div class="sec">Heute · Alle Spiele</div>
      <div id="todayWrap"><div class="empty" style="font-size:10px">Klicke LIVE</div></div>
    </div>
  </div>
</div>

<!-- FT TAB -->
<div class="tab-content" id="tab-ft">
  <div class="main-grid">
    <div class="panel">
      <button class="manual-toggle" onclick="toggleManual('ft')">+ Manuell (FT)</button>
      <div class="manual-form" id="manualFt">
        <div class="mf-grid">
          <div class="mf-inp"><label>H2H Ø FT</label><input type="number" id="fH2H" placeholder="188" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>FT Bookie Line</label><input type="number" id="fLine" placeholder="182.5" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Q3 Score Heim</label><input type="number" id="fQ3H" placeholder="25" inputmode="numeric"></div>
          <div class="mf-inp"><label>Q3 Score Gast</label><input type="number" id="fQ3A" placeholder="22" inputmode="numeric"></div>
          <div class="mf-inp"><label>HZ Total</label><input type="number" id="fHZ" placeholder="90" inputmode="numeric"></div>
          <div class="mf-inp"><label>Fouls gesamt</label><input type="number" id="fFouls" placeholder="10" inputmode="numeric"></div>
          <div class="mf-inp"><label>FT% Heim (%)</label><input type="number" id="fFTH" placeholder="78" inputmode="numeric"></div>
          <div class="mf-inp"><label>FT% Gast (%)</label><input type="number" id="fFTA" placeholder="75" inputmode="numeric"></div>
        </div>
        <button class="btn-calc" onclick="calcManualFt()">▶ FT SIGNAL</button>
      </div>
      <div class="sec">Q3 Break · FT Kandidaten</div>
      <div class="games-wrap" id="ftGamesWrap">
        <div class="empty">⟳ Klicke LIVE — zeigt Spiele am Q3 Break</div>
      </div>
    </div>
    <div class="panel">
      <div class="sec">Heute · FT Ergebnisse</div>
      <div id="ftTodayWrap"><div class="empty" style="font-size:10px">Klicke LIVE</div></div>
    </div>
  </div>
</div>

<script>
function switchTab(t){
  document.querySelectorAll('.tab').forEach((el,i)=>el.classList.toggle('active',['hz','ft'][i]===t));
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
}
function toggleManual(t){
  document.getElementById(t==='hz'?'manualHz':'manualFt').classList.toggle('open');
}
function setLive(on){
  document.getElementById('liveDot').className='dot'+(on?' live':'');
  document.getElementById('liveLabel').textContent=on?'LIVE':'OFFLINE';
}

async function loadLive(){
  const btn=document.getElementById('refreshBtn');
  btn.textContent='...';btn.disabled=true;
  try{
    const r=await fetch('/api/live');
    const d=await r.json();
    renderHzGames(d.games||[]);
    renderToday(d.today||[]);
    renderFtCandidates(d.q3||[]);
    renderFtToday(d.today||[]);
    setLive(d.source==='live'&&(d.count||0)>0);
  }catch(e){
    document.getElementById('gamesWrap').innerHTML=`<div class="empty">⚠ ${e.message}</div>`;
    setLive(false);
  }
  btn.textContent='⟳ LIVE';btn.disabled=false;
}

// ── HZ Engine ──
function hzEngine({h2h,line,q1,q2,timer,fouls,ft,fg,lineDrop,lineRise}){
  const timeLeft=Math.max(0,10-timer);
  let q2proj=timer>0.5&&q2>0?q2+(q2/timer)*timeLeft:q1;
  const proj=q1+q2proj;
  const buffer=proj-line;
  const h2hBuf=h2h!=null&&h2h>0?h2h-line:null;
  const foulsOC=fouls>=8,ftOC=ft!==null&&ft>=85,lineMC=lineDrop||lineRise;
  const h2hOverCat=h2hBuf!==null&&h2hBuf<=-3;
  const overCat=foulsOC||ftOC||lineMC||h2hOverCat;
  const fgSkip=fg!==null&&fg>60;
  const entryOk=timeLeft>=2.5,entryA=timeLeft>=3.5;
  let dir='SKIP',stufe='C',reasons=[];
  if(buffer>=5&&entryOk&&fouls<8&&!fgSkip){
    dir='UNDER';
    if(entryA){
      if(h2hBuf!==null&&h2hBuf<0){
        stufe='B';reasons=[`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ 5</span>`,`<span class="r-warn">~ H2H ${h2h} &lt; Linie → kontra</span>`];
      }else{
        stufe='A';reasons=[`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ 5</span>`,`<span class="r-ok">✓ Entry ${timeLeft.toFixed(1)}′</span>`,`<span class="r-ok">✓ Fouls ${fouls} &lt; 8</span>`];
        if(h2hBuf!==null&&h2hBuf>=3)reasons.push(`<span class="r-ok">✓ H2H +${h2hBuf.toFixed(1)} bestätigt</span>`);
      }
    }else{stufe='B';reasons=[`<span class="r-warn">~ Buffer +${buffer.toFixed(1)}</span>`,`<span class="r-warn">~ Entry ${timeLeft.toFixed(1)}′ spät</span>`];}
  }else if(buffer<=-3&&entryOk){
    dir='OVER';
    if(overCat){
      stufe='A';
      if(foulsOC)reasons.push(`<span class="r-ok">🔥 Fouls ${fouls} ≥ 8</span>`);
      if(ftOC)reasons.push(`<span class="r-ok">🔥 FT% ${ft}%</span>`);
      if(lineMC)reasons.push(`<span class="r-ok">🔥 Linie bewegt</span>`);
      if(h2hOverCat)reasons.push(`<span class="r-ok">🔥 H2H ${h2hBuf.toFixed(1)} unter Linie</span>`);
    }else{stufe='B';reasons=[`<span class="r-warn">~ ${buffer.toFixed(1)} unter Linie</span>`,`<span class="r-warn">~ Kein Katalysator</span>`];}
    reasons.push(`<span class="r-ok">✓ Entry ${timeLeft.toFixed(1)}′</span>`);
  }else{
    if(fgSkip)reasons.push(`<span class="r-bad">✗ FG% ${fg}% &gt; 60</span>`);
    if(!entryOk)reasons.push(`<span class="r-bad">✗ Entry ${timeLeft.toFixed(1)}′ &lt; 2:30</span>`);
    if(Math.abs(buffer)<3)reasons.push(`<span class="r-bad">✗ Buffer ${buffer.toFixed(1)} &lt; 3</span>`);
    if(fouls>=8&&buffer>0)reasons.push(`<span class="r-warn">⚠ Fouls ≥8 → OVER prüfen</span>`);
    if(!reasons.length)reasons.push(`<span class="r-bad">✗ Kein Signal</span>`);
  }
  return{dir,stufe,proj,buffer,timeLeft,fouls,reasons,type:'HZ'};
}

// ── FT Engine ──
function ftEngine({h2h,line,q3h,q3a,hz,fouls,ftPctH,ftPctA}){
  const q3total=q3h+q3a;
  const current=hz+q3total;
  const gap=Math.abs(q3h-q3a);
  const buffer=current-line;
  const h2hBuf=h2h!=null&&h2h>0?h2h-line:null;
  const ftOK=(ftPctH!=null&&ftPctH>=75)&&(ftPctA!=null&&ftPctA>=75);
  let dir='SKIP',stufe='C',reasons=[];
  if(gap>20){
    reasons.push(`<span class="r-bad">✗ Gap ${gap} &gt; 20 → Garbage Time Skip</span>`);
    return{dir,stufe,proj:current,buffer,timeLeft:null,fouls,reasons,type:'FT'};
  }
  if(buffer>=8&&ftOK){
    dir='UNDER';stufe='A';
    reasons.push(`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ 8</span>`);
    reasons.push(`<span class="r-ok">✓ FT% Heim ${ftPctH}% / Gast ${ftPctA}% ≥ 75</span>`);
    if(h2hBuf!==null&&h2hBuf>=5)reasons.push(`<span class="r-ok">✓ H2H +${h2hBuf.toFixed(1)} bestätigt</span>`);
  }else if(buffer>=10){
    dir='UNDER';stufe=ftOK?'A':'B';
    reasons.push(`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ 10</span>`);
    if(!ftOK)reasons.push(`<span class="r-warn">~ FT% unter 75 → Stufe B</span>`);
  }else if(buffer<=-8&&ftOK){
    dir='OVER';stufe='A';
    reasons.push(`<span class="r-ok">✓ Buffer ${buffer.toFixed(1)} ≤ −8</span>`);
    reasons.push(`<span class="r-ok">✓ FT% Heim ${ftPctH}% / Gast ${ftPctA}% ≥ 75</span>`);
    if(fouls>=10)reasons.push(`<span class="r-ok">🔥 Fouls ${fouls} ≥ 10</span>`);
  }else if(buffer<=-8){
    dir='OVER';stufe='B';
    reasons.push(`<span class="r-warn">~ Buffer ${buffer.toFixed(1)} ≤ −8</span>`);
    reasons.push(`<span class="r-warn">~ FT% nicht erfüllt → Stufe B</span>`);
  }else{
    reasons.push(`<span class="r-bad">✗ Buffer ${buffer.toFixed(1)} — min ±8 für FT</span>`);
  }
  return{dir,stufe,proj:current,buffer,timeLeft:null,fouls,reasons,type:'FT'};
}

// ── Render Signal ──
function renderSignal(sig){
  const sd=document.getElementById('sigDir');
  sd.textContent=sig.dir;
  sd.className='sig-dir-big'+(sig.dir==='UNDER'?' under':sig.dir==='OVER'?' over':'');
  const se=document.getElementById('sigStufe');
  se.textContent=sig.stufe==='C'?'— SKIP —':`STUFE  ${sig.stufe}`;
  se.className=`sig-stufe st-${sig.stufe.toLowerCase()}`;
  document.getElementById('sigTag').textContent=sig.type||'HZ';
  document.getElementById('sigReasons').innerHTML=sig.reasons.join('<br>')||'—';
  document.getElementById('ssProj').textContent=sig.proj.toFixed(1);
  const be=document.getElementById('ssBuf');
  be.textContent=(sig.buffer>=0?'+':'')+sig.buffer.toFixed(1);
  be.className='ss-v'+(sig.buffer>=3?' pos':sig.buffer<=-3?' neg':'');
  const te=document.getElementById('ssTime');
  if(sig.timeLeft!=null){te.textContent=sig.timeLeft.toFixed(1)+'′';te.className='ss-v'+(sig.timeLeft>=3.5?' pos':sig.timeLeft>=2.5?' gold':' neg');}
  else{te.textContent='Q3';te.className='ss-v gold';}
  const fe=document.getElementById('ssFouls');
  fe.textContent=sig.fouls;
  fe.className='ss-v'+(sig.fouls>=8?' neg':'');
  const strip=document.getElementById('signalStrip');
  strip.className='signal-strip'+(sig.dir==='UNDER'?' under':sig.dir==='OVER'?' over':'')+(sig.stufe==='A'?' glow':'');
}

// ── Manual calcs ──
function calcManualHz(){
  const h2h=parseFloat(document.getElementById('hH2H').value)||null;
  const line=parseFloat(document.getElementById('hLine').value);
  if(!line){alert('Bookie Line ist Pflicht!');return;}
  renderSignal(hzEngine({h2h,line,
    q1:parseFloat(document.getElementById('hQ1').value)||0,
    q2:parseFloat(document.getElementById('hQ2').value)||0,
    timer:parseFloat(document.getElementById('hTimer').value)||0,
    fouls:parseFloat(document.getElementById('hFouls').value)||0,
    ft:parseFloat(document.getElementById('hFT').value)||null,
    fg:parseFloat(document.getElementById('hFG').value)||null,
    lineDrop:document.getElementById('chkDrop').classList.contains('on'),
    lineRise:document.getElementById('chkRise').classList.contains('on'),
  }));
  window.scrollTo({top:0,behavior:'smooth'});
}
function calcManualFt(){
  const line=parseFloat(document.getElementById('fLine').value);
  if(!line){alert('FT Bookie Line ist Pflicht!');return;}
  renderSignal(ftEngine({
    h2h:parseFloat(document.getElementById('fH2H').value)||null,
    line,
    q3h:parseFloat(document.getElementById('fQ3H').value)||0,
    q3a:parseFloat(document.getElementById('fQ3A').value)||0,
    hz:parseFloat(document.getElementById('fHZ').value)||0,
    fouls:parseFloat(document.getElementById('fFouls').value)||0,
    ftPctH:parseFloat(document.getElementById('fFTH').value)||null,
    ftPctA:parseFloat(document.getElementById('fFTA').value)||null,
  }));
  window.scrollTo({top:0,behavior:'smooth'});
}

// ── HZ Cards ──
function renderHzGames(games){
  const w=document.getElementById('gamesWrap');
  if(!games.length){w.innerHTML='<div class="empty">Keine HT/Q2 Spiele live<br><span style="font-size:9px">EU-Ligen meist 18–22 Uhr</span></div>';return;}
  w.innerHTML=games.map(g=>hzCard(g)).join('');
}
function hzCard(g){
  const timer=g.timer||0;
  const label=g.status==='HT'?'HALBZEIT':`Q2·${timer}′`;
  return`<div class="game-card" id="gc-${g.id}" onclick="selectHzCard(${g.id},${JSON.stringify(g.home)},${JSON.stringify(g.away)})">
    <div class="card-stripe"></div>
    <div class="card-body">
      <div class="card-top"><span class="card-league">${g.league_name}</span><span class="card-status">${label}</span></div>
      <div class="card-teams">
        <div class="card-team">${g.home}</div>
        <div><div class="score-num">${g.total_home}–${g.total_away}</div><div class="score-q1">Q1:${g.q1_home}–${g.q1_away}</div></div>
        <div class="card-team away">${g.away}</div>
      </div>
      <div class="card-stats-row">
        <div class="cs"><div class="cs-val">${g.q1_total}</div><div class="cs-lbl">Q1 Total</div></div>
        <div class="cs"><div class="cs-val">${g.q2_live||'—'}</div><div class="cs-lbl">Q2 live</div></div>
        <div class="cs"><div class="cs-val">${g.ht_total}</div><div class="cs-lbl">HT Total</div></div>
      </div>
      <div class="card-bot">
        <span class="h2h-note" id="h2hn-${g.id}">H2H laden...</span>
        <span class="card-sig-badge none" id="badge-${g.id}">?</span>
        <span class="card-stufe-badge c" id="stufe-${g.id}"></span>
      </div>
    </div>
    <div class="card-inputs" id="ci-${g.id}">
      <div class="inp-group"><label id="h2hlbl-${g.id}">H2H Ø</label><input type="number" id="ih2h-${g.id}" placeholder="96.5" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>Bookie Line</label><input type="number" id="iline-${g.id}" placeholder="91.5" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>Fouls</label><input type="number" id="ifouls-${g.id}" placeholder="5" min="0" inputmode="numeric"></div>
      <button class="calc-mini" onclick="event.stopPropagation();calcHzCard(${g.id},${g.q1_total},${g.q2_live||0},${timer})">▶ SIGNAL</button>
    </div>
  </div>`;
}
async function selectHzCard(id,home,away){
  document.querySelectorAll('.game-card').forEach(c=>{c.classList.remove('selected');const ci=c.querySelector('.card-inputs');if(ci)ci.classList.remove('open');});
  const card=document.getElementById('gc-'+id);
  if(card){card.classList.add('selected');document.getElementById('ci-'+id).classList.add('open');}
  try{
    const r=await fetch(`/api/h2h?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}`);
    const d=await r.json();
    const note=document.getElementById('h2hn-'+id);
    const inp=document.getElementById('ih2h-'+id);
    if(d.found){
      note.textContent=`H2H Ø ${d.avg} (${d.count}x)`;note.className='h2h-note found';
      if(inp&&!inp.value){inp.value=d.avg;document.getElementById('h2hlbl-'+id).textContent=`H2H Ø (${d.count}x)`;}
    }else{note.textContent='H2H: kein Eintrag';note.className='h2h-note';}
  }catch(e){document.getElementById('h2hn-'+id).textContent='H2H: Fehler';}
}
function calcHzCard(id,q1,q2live,timer){
  const h2h=parseFloat(document.getElementById('ih2h-'+id).value)||null;
  const line=parseFloat(document.getElementById('iline-'+id).value);
  const fouls=parseFloat(document.getElementById('ifouls-'+id).value)||0;
  if(!line){alert('Bookie Line eingeben!');return;}
  const sig=hzEngine({h2h,line,q1,q2:q2live,timer,fouls,ft:null,fg:null,lineDrop:false,lineRise:false});
  const card=document.getElementById('gc-'+id);
  const cls=sig.dir==='UNDER'?'sig-under':sig.dir==='OVER'?'sig-over':'';
  card.className=`game-card selected ${cls} ${sig.stufe==='A'?'sig-a':''}`;
  document.getElementById('badge-'+id).className=`card-sig-badge ${sig.dir.toLowerCase()}`;
  document.getElementById('badge-'+id).textContent=sig.dir;
  const sEl=document.getElementById('stufe-'+id);
  sEl.className=`card-stufe-badge ${sig.stufe.toLowerCase()}`;
  sEl.textContent=sig.stufe==='C'?'SKIP':sig.stufe;
  renderSignal(sig);window.scrollTo({top:0,behavior:'smooth'});
}

// ── Today list ──
function renderToday(games){
  const w=document.getElementById('todayWrap');
  if(!games.length){w.innerHTML='<div class="empty" style="font-size:10px">Keine Spiele heute</div>';return;}
  w.innerHTML=games.map(g=>{
    const sc=g.status==='FT'?'var(--dim2)':g.status==='HT'?'var(--gold)':g.status==='NS'?'var(--dim)':'var(--green)';
    return`<div class="today-card"><div class="card-stripe" style="background:${sc}"></div>
      <div class="today-body">
        <div class="today-top"><span class="today-league">${g.league_name}</span><span class="today-status" style="color:${sc}">${g.status}${g.timer?' '+g.timer+'′':''}</span></div>
        <div class="today-teams">
          <div class="today-team">${g.home}</div>
          <div><div class="today-score">${g.total_home}–${g.total_away}</div><div class="today-q">Q1:${g.q1_total} Q2:${g.q2_live||'—'}</div></div>
          <div class="today-team away">${g.away}</div>
        </div>
      </div>
    </div>`;
  }).join('');
}

// ── FT Cards ──
function renderFtCandidates(games){
  const w=document.getElementById('ftGamesWrap');
  if(!games.length){w.innerHTML='<div class="empty">Keine Spiele am Q3 Break</div>';return;}
  w.innerHTML=games.map(g=>ftCard(g)).join('');
}
function ftCard(g){
  const q3tot=(g.q3_home||0)+(g.q3_away||0);
  const gap=Math.abs((g.q3_home||0)-(g.q3_away||0));
  return`<div class="ft-card" id="ftc-${g.id}" onclick="selectFtCard(${g.id},${JSON.stringify(g.home)},${JSON.stringify(g.away)})">
    <div class="card-stripe"></div>
    <div class="ft-body">
      <div class="card-top"><span class="card-league">${g.league_name}</span><span class="card-status">Q3 BREAK</span></div>
      <div class="card-teams">
        <div class="card-team">${g.home}</div>
        <div><div class="score-num">${g.total_home}–${g.total_away}</div><div class="score-q1">HZ:${g.ht_total} Gap:${gap}</div></div>
        <div class="card-team away">${g.away}</div>
      </div>
      <div class="card-stats-row">
        <div class="cs"><div class="cs-val">${g.ht_total}</div><div class="cs-lbl">HZ Total</div></div>
        <div class="cs"><div class="cs-val">${q3tot||'—'}</div><div class="cs-lbl">Q3 Total</div></div>
        <div class="cs"><div class="cs-val">${gap}</div><div class="cs-lbl">Gap</div></div>
      </div>
      <div class="card-bot">
        <span class="h2h-note" id="fth2hn-${g.id}">H2H FT laden...</span>
        <span class="card-sig-badge none" id="ftbadge-${g.id}">?</span>
        <span class="card-stufe-badge c" id="ftstufe-${g.id}"></span>
      </div>
    </div>
    <div class="ft-card-inputs" id="ftci-${g.id}">
      <div class="inp-group"><label id="fth2hlbl-${g.id}">H2H FT Ø</label><input type="number" id="ifth2h-${g.id}" placeholder="188" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>FT Bookie Line</label><input type="number" id="iftline-${g.id}" placeholder="182.5" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>Fouls</label><input type="number" id="iftfouls-${g.id}" placeholder="10" inputmode="numeric"></div>
      <div class="inp-group"><label>FT% Heim</label><input type="number" id="iftfth-${g.id}" placeholder="78" inputmode="numeric"></div>
      <div class="inp-group"><label>FT% Gast</label><input type="number" id="iftfta-${g.id}" placeholder="75" inputmode="numeric"></div>
      <button class="calc-mini" onclick="event.stopPropagation();calcFtCard(${g.id},${g.ht_total},${g.q3_home||0},${g.q3_away||0})">▶ FT SIGNAL</button>
    </div>
  </div>`;
}
async function selectFtCard(id,home,away){
  document.querySelectorAll('.ft-card').forEach(c=>{c.classList.remove('selected');const ci=c.querySelector('.ft-card-inputs');if(ci)ci.classList.remove('open');});
  const card=document.getElementById('ftc-'+id);
  if(card){card.classList.add('selected');document.getElementById('ftci-'+id).classList.add('open');}
  try{
    const r=await fetch(`/api/h2h?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}&type=ft`);
    const d=await r.json();
    const note=document.getElementById('fth2hn-'+id);
    if(d.found){
      note.textContent=`H2H FT Ø ${d.avg} (${d.count}x)`;note.className='h2h-note found';
      const inp=document.getElementById('ifth2h-'+id);
      if(inp&&!inp.value){inp.value=d.avg;document.getElementById('fth2hlbl-'+id).textContent=`H2H FT Ø (${d.count}x)`;}
    }else{note.textContent='H2H FT: kein Eintrag';note.className='h2h-note';}
  }catch(e){}
}
function calcFtCard(id,hz,q3h,q3a){
  const line=parseFloat(document.getElementById('iftline-'+id).value);
  if(!line){alert('FT Bookie Line eingeben!');return;}
  const sig=ftEngine({
    h2h:parseFloat(document.getElementById('ifth2h-'+id).value)||null,
    line,q3h,q3a,hz,
    fouls:parseFloat(document.getElementById('iftfouls-'+id).value)||0,
    ftPctH:parseFloat(document.getElementById('iftfth-'+id).value)||null,
    ftPctA:parseFloat(document.getElementById('iftfta-'+id).value)||null,
  });
  const card=document.getElementById('ftc-'+id);
  const cls=sig.dir==='UNDER'?'sig-under':sig.dir==='OVER'?'sig-over':'';
  card.className=`ft-card selected ${cls} ${sig.stufe==='A'?'sig-a':''}`;
  document.getElementById('ftbadge-'+id).className=`card-sig-badge ${sig.dir.toLowerCase()}`;
  document.getElementById('ftbadge-'+id).textContent=sig.dir;
  const sEl=document.getElementById('ftstufe-'+id);
  sEl.className=`card-stufe-badge ${sig.stufe.toLowerCase()}`;
  sEl.textContent=sig.stufe==='C'?'SKIP':sig.stufe;
  renderSignal(sig);window.scrollTo({top:0,behavior:'smooth'});
}
function renderFtToday(games){
  const w=document.getElementById('ftTodayWrap');
  const done=games.filter(g=>g.status==='FT');
  if(!done.length){w.innerHTML='<div class="empty" style="font-size:10px">Noch keine FT Ergebnisse heute</div>';return;}
  w.innerHTML=done.map(g=>`<div class="today-card">
    <div class="card-stripe" style="background:var(--dim2)"></div>
    <div class="today-body">
      <div class="today-top"><span class="today-league">${g.league_name}</span><span class="today-status" style="color:var(--dim2)">FT</span></div>
      <div class="today-teams">
        <div class="today-team">${g.home}</div>
        <div><div class="today-score">${g.total_home}–${g.total_away}</div><div class="today-q">Total:${g.total_home+g.total_away}</div></div>
        <div class="today-team away">${g.away}</div>
      </div>
    </div>
  </div>`).join('');
}
</script>
</body>
</html>"""


# ─── API helpers ─────────────────────────────────────────────────────────────

async def api_get(endpoint: str, params: dict) -> dict:
    headers = {
        "x-apisports-key": API_KEY,
        "x-rapidapi-host": "v1.basketball.api-sports.io",
    }
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(f"{API_BASE}/{endpoint}", headers=headers, params=params)
        r.raise_for_status()
        return r.json()


def _normalize_game(g: dict, league_id: int, league_name: str) -> dict:
    scores  = g.get("scores", {})
    home_s  = scores.get("home", {})
    away_s  = scores.get("away", {})
    q1h = home_s.get("quarter_1") or 0
    q1a = away_s.get("quarter_1") or 0
    q2h = home_s.get("quarter_2") or 0
    q2a = away_s.get("quarter_2") or 0
    q3h = home_s.get("quarter_3") or 0
    q3a = away_s.get("quarter_3") or 0
    total_h = home_s.get("total") or 0
    total_a = away_s.get("total") or 0
    return {
        "id":          g.get("id"),
        "league_id":   league_id,
        "league_name": g.get("league", {}).get("name", league_name),
        "status":      g.get("status", {}).get("short", ""),
        "timer":       g.get("status", {}).get("timer"),
        "home":        g.get("teams", {}).get("home", {}).get("name", "Home"),
        "away":        g.get("teams", {}).get("away", {}).get("name", "Away"),
        "q1_home": q1h, "q1_away": q1a,
        "q2_home": q2h, "q2_away": q2a,
        "q3_home": q3h, "q3_away": q3a,
        "total_home": total_h, "total_away": total_a,
        "q1_total":  q1h + q1a,
        "q2_live":   q2h + q2a,
        "ht_total":  q1h + q1a + q2h + q2a,
    }


# ─── Google Sheets ────────────────────────────────────────────────────────────

def _matchup_key(home: str, away: str) -> str:
    return "|".join(sorted([home.lower().strip(), away.lower().strip()]))


def _get_worksheet():
    global _ws
    if _ws is not None:
        return _ws
    if not (SHEETS_ID and CREDS_JSON):
        return None
    try:
        import gspread
        gc  = gspread.service_account_from_dict(json.loads(CREDS_JSON))
        sh  = gc.open_by_key(SHEETS_ID)
        try:
            _ws = sh.worksheet(SHEETS_TAB)
        except gspread.WorksheetNotFound:
            _ws = sh.add_worksheet(title=SHEETS_TAB, rows=2000, cols=10)
            _ws.append_row(["date", "home", "away", "league",
                            "q1_total", "q2_total", "ht_total", "ft_total"])
        return _ws
    except Exception as e:
        logging.warning("Sheets init failed: %s", e)
        return None


def _load_h2h_from_sheet() -> None:
    global _h2h_cache, _ft_h2h_cache, _seen_ft_ids
    ws = _get_worksheet()
    if ws is None:
        return
    try:
        rows = ws.get_all_records()
        _h2h_cache = {}
        _ft_h2h_cache = {}
        _seen_ft_ids = set()
        for row in rows:
            home     = str(row.get("home", "")).strip()
            away     = str(row.get("away", "")).strip()
            ht_total = row.get("ht_total")
            ft_total = row.get("ft_total")
            game_key = f"{row.get('date','')}-{home}-{away}"
            _seen_ft_ids.add(game_key)
            key = _matchup_key(home, away)
            if home and away:
                if ht_total:
                    _h2h_cache.setdefault(key, []).append(float(ht_total))
                if ft_total:
                    _ft_h2h_cache.setdefault(key, []).append(float(ft_total))
        logging.info("Loaded %d HZ / %d FT matchups", len(_h2h_cache), len(_ft_h2h_cache))
    except Exception as e:
        logging.warning("H2H load failed: %s", e)


async def _extract_ft_games(date_str: str | None = None) -> int:
    """Fetch FT games for a date, write new rows to Sheets. Returns rows written."""
    if not API_KEY:
        return 0
    target = date_str or _date.today().isoformat()
    new_rows = []
    for league_id, (name, season) in LEAGUES.items():
        try:
            data = await api_get("games", {"league": league_id, "season": season, "date": target})
            for g in (data.get("response") or []):
                if g.get("status", {}).get("short", "") != "FT":
                    continue
                ng = _normalize_game(g, league_id, name)
                home, away = ng["home"], ng["away"]
                ft_total = ng["total_home"] + ng["total_away"]
                if ft_total == 0:
                    continue
                game_key = f"{target}-{home}-{away}"
                if game_key in _seen_ft_ids:
                    continue
                _seen_ft_ids.add(game_key)
                q2_total     = ng["q2_home"] + ng["q2_away"]
                ht_total_val = ng["q1_total"] + q2_total
                new_rows.append([target, home, away, ng["league_name"],
                                  ng["q1_total"], q2_total, ht_total_val, ft_total])
                key = _matchup_key(home, away)
                _h2h_cache.setdefault(key, []).append(float(ht_total_val))
                _ft_h2h_cache.setdefault(key, []).append(float(ft_total))
        except Exception as e:
            logging.warning("FT extract %s league %s: %s", target, league_id, e)

    if new_rows:
        ws = await asyncio.to_thread(_get_worksheet)
        if ws:
            try:
                await asyncio.to_thread(ws.append_rows, new_rows, value_input_option="USER_ENTERED")
                logging.info("Wrote %d rows (%s)", len(new_rows), target)
            except Exception as e:
                logging.warning("Sheets write failed: %s", e)
                global _ws
                _ws = None
    return len(new_rows)


async def _scheduler_loop() -> None:
    await asyncio.to_thread(_load_h2h_from_sheet)
    while True:
        try:
            await _extract_ft_games()
        except Exception as e:
            logging.warning("Scheduler: %s", e)
        await asyncio.sleep(1800)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "api_key_set":       bool(API_KEY),
        "sheets_configured": bool(SHEETS_ID and CREDS_JSON),
        "hz_matchups":  len(_h2h_cache),
        "ft_matchups":  len(_ft_h2h_cache),
    }


@app.get("/api/leagues")
async def get_leagues():
    return {"leagues": [{"id": k, "name": v[0], "season": v[1]} for k, v in LEAGUES.items()]}


@app.get("/api/live")
async def get_live_games():
    if not API_KEY:
        return {"games": _demo_hz(), "today": _demo_today(), "q3": _demo_q3(),
                "source": "demo", "count": 2}

    today_str = _date.today().isoformat()
    live_hz, live_q3, today_all, seen = [], [], [], set()

    for league_id, (name, season) in LEAGUES.items():
        try:
            data = await api_get("games", {"league": league_id, "season": season, "live": "all"})
            for g in (data.get("response") or []):
                gid = g.get("id")
                if gid in seen:
                    continue
                seen.add(gid)
                status = g.get("status", {}).get("short", "")
                ng = _normalize_game(g, league_id, name)
                if status in ("HT", "Q2"):
                    live_hz.append(ng)
                elif status == "Q3BT":
                    live_q3.append(ng)
                else:
                    today_all.append(ng)
        except Exception:
            pass

        try:
            data2 = await api_get("games", {"league": league_id, "season": season, "date": today_str})
            for g in (data2.get("response") or []):
                gid = g.get("id")
                if gid not in seen:
                    seen.add(gid)
                    today_all.append(_normalize_game(g, league_id, name))
        except Exception:
            continue

    return {"games": live_hz, "q3": live_q3, "today": today_all[:40],
            "source": "live", "count": len(live_hz)}


@app.get("/api/h2h")
async def get_h2h(home: str, away: str, type: str = "hz"):
    key   = _matchup_key(home, away)
    cache = _ft_h2h_cache if type == "ft" else _h2h_cache
    vals  = cache.get(key, [])
    avg   = round(sum(vals) / len(vals), 1) if vals else None
    return {"avg": avg, "count": len(vals), "found": avg is not None, "type": type}


@app.get("/api/backfill")
async def backfill(days: int = Query(default=30, ge=1, le=90)):
    """
    Backfill Google Sheet with historical FT data.
    GET /api/backfill?days=30  — iterates last N days, writes missing FT games.
    """
    if not API_KEY:
        raise HTTPException(status_code=400, detail="API_SPORTS_KEY not set")
    total = 0
    today = _date.today()
    for i in range(1, days + 1):
        target = (today - timedelta(days=i)).isoformat()
        try:
            written = await _extract_ft_games(target)
            total += written
        except Exception as e:
            logging.warning("Backfill %s: %s", target, e)
        await asyncio.sleep(0.4)   # rate-limit buffer
    await asyncio.to_thread(_load_h2h_from_sheet)
    return {"status": "done", "days_processed": days, "rows_written": total,
            "hz_matchups": len(_h2h_cache), "ft_matchups": len(_ft_h2h_cache)}


@app.get("/api/trigger-extract")
async def trigger_extract():
    written = await _extract_ft_games()
    return {"status": "ok", "rows_written": written,
            "hz_matchups": len(_h2h_cache), "ft_matchups": len(_ft_h2h_cache)}


# ─── Demo data ────────────────────────────────────────────────────────────────

def _demo_hz():
    return [
        {"id": 1001, "league_id": 4, "league_name": "ACB", "status": "HT", "timer": None,
         "home": "Real Madrid", "away": "FC Barcelona",
         "q1_home": 28, "q1_away": 24, "q2_home": 0,  "q2_away": 0,  "q3_home": 0, "q3_away": 0,
         "total_home": 28, "total_away": 24, "q1_total": 52, "q2_live": 0, "ht_total": 52},
        {"id": 1002, "league_id": 120, "league_name": "TBL", "status": "Q2", "timer": 5,
         "home": "Fenerbahce", "away": "Galatasaray",
         "q1_home": 31, "q1_away": 27, "q2_home": 18, "q2_away": 14, "q3_home": 0, "q3_away": 0,
         "total_home": 49, "total_away": 41, "q1_total": 58, "q2_live": 32, "ht_total": 90},
    ]

def _demo_q3():
    return [
        {"id": 2001, "league_id": 3, "league_name": "EuroLeague", "status": "Q3BT", "timer": None,
         "home": "Olympiacos", "away": "CSKA",
         "q1_home": 24, "q1_away": 22, "q2_home": 21, "q2_away": 24,
         "q3_home": 22, "q3_away": 25,
         "total_home": 67, "total_away": 71, "q1_total": 46, "q2_live": 45, "ht_total": 91},
    ]

def _demo_today():
    return [
        {"id": 3001, "league_id": 8, "league_name": "Lega A", "status": "FT", "timer": None,
         "home": "Olimpia Milano", "away": "Virtus Bologna",
         "q1_home": 26, "q1_away": 21, "q2_home": 22, "q2_away": 24,
         "q3_home": 0,  "q3_away": 0,
         "total_home": 88, "total_away": 79, "q1_total": 47, "q2_live": 46, "ht_total": 93},
    ]
