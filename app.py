from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import httpx
import json
import logging
import os
from typing import Optional

API_KEY = os.getenv("API_SPORTS_KEY", "")
API_BASE = "https://v1.basketball.api-sports.io"

SHEETS_ID  = os.getenv("GOOGLE_SHEETS_ID", "")
SHEETS_TAB = os.getenv("GOOGLE_SHEETS_TAB", "H2H")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

LEAGUES = {
    120: ("BSL / TBL",  "2025-2026"),
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
}

# ---------- Google Sheets / H2H state ----------
_h2h_cache: dict = {}   # matchup_key -> [ft_total, ...]
_seen_ft_ids: set = set()
_ws = None               # cached gspread Worksheet


@asynccontextmanager
async def lifespan(app_: FastAPI):
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="HZ Trading App", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HZ Trading</title>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;900&family=Barlow:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#07080b;--s1:#0d0e13;--s2:#111218;--border:#1a1b24;--border2:#22232f;
  --text:#c9cdd8;--dim:#3e4055;--dim2:#555770;
  --under:#00b4d8;--over:#e63946;--green:#2dc653;--gold:#f4a261;--white:#f0f1f5;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;min-height:100vh;}

.topbar{position:sticky;top:0;z-index:200;background:var(--s1);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:48px;}
.logo{font-family:'Barlow Condensed',sans-serif;font-weight:900;font-size:18px;letter-spacing:4px;color:var(--white);}
.logo em{color:var(--green);font-style:normal;}
.topbar-right{display:flex;align-items:center;gap:10px;}
.live-pill{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--dim2);letter-spacing:1px;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--dim);}
.dot.live{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 1.5s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.br-chip{background:var(--s2);border:1px solid var(--border2);padding:4px 10px;color:var(--gold);cursor:pointer;font-family:'Barlow Condensed',sans-serif;font-size:14px;letter-spacing:1px;}
.icon-btn{background:none;border:1px solid var(--border2);color:var(--dim2);padding:5px 10px;font-size:11px;letter-spacing:1px;cursor:pointer;font-family:'Barlow',sans-serif;text-transform:uppercase;transition:all .15s;}
.icon-btn:hover{border-color:var(--green);color:var(--green);}

/* SIGNAL BAR — always pinned below topbar */
.signal-bar{background:var(--s1);border-bottom:2px solid var(--border);padding:14px 16px;display:grid;grid-template-columns:1fr 1fr;gap:12px;transition:border-bottom-color .3s;}
.signal-bar.under{border-bottom-color:rgba(0,180,216,.5);}
.signal-bar.over {border-bottom-color:rgba(230,57,70,.5);}
.signal-bar.glow {box-shadow:0 4px 24px rgba(45,198,83,.12);}

.sig-main{display:flex;align-items:center;gap:14px;padding:12px 14px;border:1px solid var(--border);background:var(--bg);transition:border-color .3s,background .3s;}
.sig-main.under{border-color:rgba(0,180,216,.4);background:rgba(0,180,216,.03);}
.sig-main.over {border-color:rgba(230,57,70,.4); background:rgba(230,57,70,.03);}
.sig-dir{font-family:'Barlow Condensed',sans-serif;font-weight:900;font-size:48px;letter-spacing:4px;line-height:1;color:var(--dim);}
.sig-main.under .sig-dir{color:var(--under);}
.sig-main.over  .sig-dir{color:var(--over);}
.sig-info{display:flex;flex-direction:column;gap:5px;}
.sig-stufe{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;letter-spacing:4px;padding:2px 10px;border:1px solid;display:inline-block;}
.st-a{color:var(--green);border-color:rgba(45,198,83,.4);}
.st-b{color:var(--gold); border-color:rgba(244,162,97,.4);}
.st-c{color:var(--dim);  border-color:var(--border);}
.sig-reasons{font-size:10px;line-height:1.9;color:var(--dim2);}
.r-ok{color:var(--green);}
.r-warn{color:var(--gold);}
.r-bad{color:var(--over);}

.sig-right{display:flex;flex-direction:column;gap:8px;}
.stats-4{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;}
.stat{background:var(--bg);border:1px solid var(--border);padding:8px 6px;text-align:center;}
.stat-v{font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:700;color:var(--white);}
.stat-v.pos{color:var(--under);}
.stat-v.neg{color:var(--over);}
.stat-v.gold{color:var(--gold);}
.stat-l{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);margin-top:1px;}
.stake-box{background:var(--bg);border:1px solid var(--border);padding:10px 12px;display:flex;justify-content:space-between;align-items:center;}
.stake-lbl{font-size:9px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);}
.stake-desc{font-size:10px;color:var(--dim2);margin-top:2px;}
.stake-amt{font-family:'Barlow Condensed',sans-serif;font-size:26px;font-weight:700;color:var(--gold);}
.stake-amt.none{color:var(--dim);font-size:16px;}
.trade-mini{background:var(--bg);border:1px solid var(--border);padding:8px 12px;}
.trade-mini-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}
.trade-mini-title{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--dim);}
.trade-mini-stats{font-size:10px;color:var(--dim2);}
.tl-row{display:grid;grid-template-columns:1fr 48px 42px 38px;gap:4px;padding:3px 0;border-bottom:1px solid var(--border);font-size:10px;align-items:center;}
.tl-row:last-child{border-bottom:none;}
.tl-game{color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.tl-dir{font-weight:700;}
.tl-dir.under{color:var(--under);}
.tl-dir.over{color:var(--over);}
.tl-amt{color:var(--dim2);text-align:right;}
.tl-res{text-align:center;cursor:pointer;padding:1px 3px;border:1px solid var(--border);font-size:9px;letter-spacing:1px;}
.tl-res.win{color:var(--green);border-color:rgba(45,198,83,.3);}
.tl-res.loss{color:var(--over);border-color:rgba(230,57,70,.3);}
.tl-res.open{color:var(--gold);border-color:rgba(244,162,97,.3);}
.add-trade-btn{width:100%;background:none;border:none;border-top:1px solid var(--border);color:var(--dim2);font-family:'Barlow',sans-serif;font-size:10px;padding:6px;cursor:pointer;letter-spacing:1px;text-transform:uppercase;}
.add-trade-btn:hover{color:var(--green);}

/* MAIN */
.main{display:grid;grid-template-columns:1fr 1fr;gap:0;}
.panel{padding:14px;border-right:1px solid var(--border);}
.panel:last-child{border-right:none;}
.sec{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--dim);margin-bottom:10px;display:flex;align-items:center;gap:8px;}
.sec::after{content:'';flex:1;height:1px;background:var(--border);}

.br-editor{display:none;background:var(--s2);border:1px solid var(--border);padding:10px 14px;margin-bottom:12px;}
.br-editor.open{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.br-editor label{font-size:9px;color:var(--dim2);letter-spacing:1px;text-transform:uppercase;}
.br-editor input{background:var(--bg);border:1px solid var(--border2);color:var(--gold);font-family:'Barlow Condensed',sans-serif;font-size:20px;font-weight:700;padding:5px 10px;outline:none;width:110px;}
.br-editor input:focus{border-color:var(--gold);}
.btn-xs{background:var(--green);border:none;color:var(--bg);font-family:'Barlow',sans-serif;font-size:11px;font-weight:700;padding:6px 12px;cursor:pointer;letter-spacing:1px;}

.manual-toggle{background:none;border:1px dashed var(--border2);color:var(--dim2);width:100%;padding:10px;font-size:10px;letter-spacing:2px;text-transform:uppercase;cursor:pointer;font-family:'Barlow',sans-serif;margin-bottom:2px;transition:all .15s;}
.manual-toggle:hover{border-color:var(--dim);color:var(--text);}
.manual-form{display:none;background:var(--s2);border:1px solid var(--border);padding:14px;margin-bottom:8px;}
.manual-form.open{display:block;}
.mf-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;}
.mf-inp{display:flex;flex-direction:column;gap:3px;}
.mf-inp label{font-size:9px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.mf-inp input{background:var(--bg);border:1px solid var(--border2);color:var(--white);font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:700;padding:6px 8px;outline:none;}
.mf-inp input:focus{border-color:var(--green);}
.checks-row{display:flex;gap:14px;margin-bottom:8px;flex-wrap:wrap;}
.chk{display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none;}
.chk-box{width:14px;height:14px;border:1px solid var(--border2);background:var(--bg);display:flex;align-items:center;justify-content:center;font-size:9px;}
.chk.on .chk-box{background:var(--over);border-color:var(--over);color:#fff;}
.chk-lbl{font-size:10px;color:var(--dim2);}
.chk.on .chk-lbl{color:var(--text);}
.btn-calc{width:100%;background:var(--white);border:none;color:var(--bg);font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:900;letter-spacing:4px;padding:12px;cursor:pointer;text-transform:uppercase;}
.btn-calc:hover{background:#dde1f0;}

.games-wrap{display:flex;flex-direction:column;gap:2px;}
.game-card{background:var(--s2);border:1px solid var(--border);cursor:pointer;display:grid;grid-template-columns:3px 1fr;transition:border-color .15s;}
.game-card:hover{border-color:var(--border2);}
.game-card.selected{border-color:var(--dim2);}
.game-card.sig-under{border-color:rgba(0,180,216,.4);}
.game-card.sig-over{border-color:rgba(230,57,70,.4);}
.game-card.sig-a{box-shadow:0 0 12px rgba(45,198,83,.1);}
.card-stripe{width:3px;}
.sig-under .card-stripe,.sig-a .card-stripe{background:var(--under);}
.sig-over  .card-stripe{background:var(--over);}
.sig-a     .card-stripe{background:var(--green);}
.card-body{padding:10px 12px;}
.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}
.card-league{font-size:9px;letter-spacing:1.5px;color:var(--dim2);text-transform:uppercase;}
.card-status{font-size:9px;color:var(--gold);}
.card-teams{display:grid;grid-template-columns:1fr auto 1fr;gap:4px;align-items:center;margin-bottom:8px;}
.card-team{font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700;color:var(--white);}
.card-team.away{text-align:right;}
.card-score{text-align:center;}
.score-num{font-family:'Barlow Condensed',sans-serif;font-size:20px;font-weight:900;color:var(--white);line-height:1;}
.score-q1{font-size:9px;color:var(--dim2);margin-top:1px;}
.card-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;margin-bottom:6px;}
.cs{background:var(--bg);padding:5px 4px;text-align:center;}
.cs-val{font-family:'Barlow Condensed',sans-serif;font-size:14px;font-weight:700;color:var(--text);}
.cs-lbl{font-size:7px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);margin-top:1px;}
.card-bot{display:flex;justify-content:space-between;align-items:center;padding-top:6px;border-top:1px solid var(--border);}
.card-sig-badge{font-size:9px;font-weight:700;letter-spacing:1.5px;padding:2px 7px;border:1px solid;}
.card-sig-badge.under{color:var(--under);border-color:rgba(0,180,216,.3);}
.card-sig-badge.over{color:var(--over);border-color:rgba(230,57,70,.3);}
.card-sig-badge.none{color:var(--dim);border-color:var(--border);}
.card-stufe{font-size:9px;font-weight:700;padding:2px 7px;}
.card-stufe.a{background:var(--green);color:var(--bg);}
.card-stufe.b{background:var(--gold);color:var(--bg);}
.card-stufe.c{color:var(--dim);}
.card-inputs{display:none;padding:10px 12px;border-top:1px solid var(--border);background:var(--s1);}
.card-inputs.open{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;}
.inp-group{display:flex;flex-direction:column;gap:3px;}
.inp-group label{font-size:8px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.inp-group input{background:var(--bg);border:1px solid var(--border2);color:var(--white);font-family:'Barlow Condensed',sans-serif;font-size:16px;font-weight:600;padding:5px 7px;outline:none;width:100%;}
.inp-group input:focus{border-color:var(--under);}
.calc-mini{grid-column:1/-1;background:var(--white);border:none;font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:900;letter-spacing:3px;padding:8px;cursor:pointer;text-transform:uppercase;color:var(--bg);}
.calc-mini:hover{background:#dde1f0;}
.empty{text-align:center;padding:32px 14px;color:var(--dim);border:1px dashed var(--border);font-size:11px;line-height:2.2;}
.today-card{background:var(--s2);border:1px solid var(--border);display:grid;grid-template-columns:3px 1fr;margin-bottom:2px;}
.today-body{padding:8px 12px;}
.today-top{display:flex;justify-content:space-between;margin-bottom:4px;}
.today-league{font-size:9px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.today-status{font-size:9px;}
.today-teams{display:grid;grid-template-columns:1fr auto 1fr;gap:4px;align-items:center;}
.today-team{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;color:var(--white);}
.today-team.away{text-align:right;}
.today-score{text-align:center;font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:900;color:var(--white);}
.today-q{font-size:8px;color:var(--dim2);margin-top:1px;text-align:center;}

@media(max-width:700px){
  .signal-bar{grid-template-columns:1fr;}
  .main{grid-template-columns:1fr;}
  .panel{border-right:none;border-bottom:1px solid var(--border);}
}
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">HZ <em>TRADING</em></div>
  <div class="topbar-right">
    <div class="live-pill"><div class="dot" id="liveDot"></div><span id="liveLabel">OFFLINE</span></div>
    <div class="br-chip" onclick="toggleBrEditor()">💰 <span id="brDisplay">21.88€</span></div>
    <button class="icon-btn" id="refreshBtn" onclick="loadLive()">⟳ LIVE</button>
  </div>
</div>

<!-- SIGNAL always visible -->
<div class="signal-bar" id="signalBar">
  <div class="sig-main" id="sigMain">
    <div class="sig-dir" id="sigDir">WARTE</div>
    <div class="sig-info">
      <span class="sig-stufe st-c" id="sigStufe">— —</span>
      <div class="sig-reasons" id="sigReasons" style="margin-top:5px">Signal berechnen oder Spiel wählen</div>
    </div>
  </div>
  <div class="sig-right">
    <div class="stats-4">
      <div class="stat"><div class="stat-v" id="stProj">—</div><div class="stat-l">Proj</div></div>
      <div class="stat"><div class="stat-v" id="stBuf">—</div><div class="stat-l">Buffer</div></div>
      <div class="stat"><div class="stat-v" id="stTime">—</div><div class="stat-l">Zeit</div></div>
      <div class="stat"><div class="stat-v" id="stFouls">—</div><div class="stat-l">Fouls</div></div>
    </div>
    <div class="stake-box">
      <div><div class="stake-lbl">Einsatz</div><div class="stake-desc" id="stakeDesc">—</div></div>
      <div class="stake-amt none" id="stakeAmt">—</div>
    </div>
    <div class="trade-mini">
      <div class="trade-mini-head">
        <span class="trade-mini-title">Trade Log</span>
        <span class="trade-mini-stats" id="tlStats">0W / 0L</span>
      </div>
      <div id="tlRows"><div style="font-size:10px;color:var(--dim);padding:3px 0">Noch keine Trades</div></div>
      <button class="add-trade-btn" onclick="bookTrade()">+ Trade buchen</button>
    </div>
  </div>
</div>

<div class="main">
  <div class="panel">
    <div class="br-editor" id="brEditor">
      <label>Bankroll €</label>
      <input type="number" id="brInput" step="0.01">
      <button class="btn-xs" onclick="saveBr()">OK</button>
    </div>
    <button class="manual-toggle" onclick="toggleManual()">+ Manuell eingeben</button>
    <div class="manual-form" id="manualForm">
      <div class="mf-grid">
        <div class="mf-inp"><label>H2H Ø Total (HZ)</label><input type="number" id="mH2H" placeholder="96.5" step="0.5" inputmode="decimal"></div>
        <div class="mf-inp"><label>Bookie Line</label><input type="number" id="mLine" placeholder="91.5" step="0.5" inputmode="decimal"></div>
        <div class="mf-inp"><label>Q1 Total</label><input type="number" id="mQ1" placeholder="52" inputmode="numeric"></div>
        <div class="mf-inp"><label>Q2 aktuell</label><input type="number" id="mQ2" placeholder="28" inputmode="numeric"></div>
        <div class="mf-inp"><label>Q2 Spielzeit (Min)</label><input type="number" id="mTimer" placeholder="4" min="0" max="10" step="0.5" inputmode="decimal"></div>
        <div class="mf-inp"><label>Fouls gesamt</label><input type="number" id="mFouls" placeholder="5" inputmode="numeric"></div>
        <div class="mf-inp"><label>FT% Ø (opt.)</label><input type="number" id="mFT" placeholder="—" inputmode="numeric"></div>
        <div class="mf-inp"><label>FG% Quote (opt.)</label><input type="number" id="mFG" placeholder="—" inputmode="numeric"></div>
      </div>
      <div class="checks-row">
        <div class="chk" id="chkDrop" onclick="this.classList.toggle('on')"><div class="chk-box">✓</div><span class="chk-lbl">Linie fällt drastisch (≥8)</span></div>
        <div class="chk" id="chkRise" onclick="this.classList.toggle('on')"><div class="chk-box">✓</div><span class="chk-lbl">Linie steigt</span></div>
      </div>
      <button class="btn-calc" onclick="calcManual()">▶ SIGNAL BERECHNEN</button>
    </div>
    <div class="sec">Live Spiele · Halbzeit</div>
    <div class="games-wrap" id="gamesWrap">
      <div class="empty">⟳ Klicke LIVE um Halbzeit-Spiele zu laden</div>
    </div>
  </div>

  <div class="panel">
    <div class="sec">Heute · Alle Spiele</div>
    <div id="todayWrap">
      <div class="empty" style="font-size:10px">Klicke LIVE — zeigt alle heutigen Spiele mit Stats</div>
    </div>
  </div>
</div>

<script>
let bankroll=parseFloat(localStorage.getItem('hz_br')||'21.88');
let trades=JSON.parse(localStorage.getItem('hz_trades')||'[]');
let currentSig=null,currentGameName='';
updateBrDisplay();renderTradeLog();

function toggleBrEditor(){const e=document.getElementById('brEditor');e.classList.toggle('open');document.getElementById('brInput').value=bankroll;}
function saveBr(){bankroll=parseFloat(document.getElementById('brInput').value)||bankroll;localStorage.setItem('hz_br',bankroll);updateBrDisplay();document.getElementById('brEditor').classList.remove('open');if(currentSig)renderStake(currentSig);}
function updateBrDisplay(){document.getElementById('brDisplay').textContent=bankroll.toFixed(2)+'€';}
function toggleManual(){document.getElementById('manualForm').classList.toggle('open');}

function calcManual(){
  const h2h=parseFloat(document.getElementById('mH2H').value);
  const line=parseFloat(document.getElementById('mLine').value);
  const q1=parseFloat(document.getElementById('mQ1').value)||0;
  const q2=parseFloat(document.getElementById('mQ2').value)||0;
  const timer=parseFloat(document.getElementById('mTimer').value)||0;
  const fouls=parseFloat(document.getElementById('mFouls').value)||0;
  const ft=parseFloat(document.getElementById('mFT').value)||null;
  const fg=parseFloat(document.getElementById('mFG').value)||null;
  const lineDrop=document.getElementById('chkDrop').classList.contains('on');
  const lineRise=document.getElementById('chkRise').classList.contains('on');
  if(!h2h||!line){alert('H2H Ø und Bookie Line sind Pflicht!');return;}
  const sig=engine({h2h,line,q1,q2,timer,fouls,ft,fg,lineDrop,lineRise});
  currentGameName='Manuell';currentSig=sig;renderSignal(sig);
}

async function loadLive(){
  const btn=document.getElementById('refreshBtn');
  btn.textContent='...';
  try{
    const r=await fetch('/api/live');
    const data=await r.json();
    renderGames(data.games||[]);
    renderToday(data.today||[]);
    setLive(data.source==='live'&&(data.count||0)>0);
  }catch(e){
    document.getElementById('gamesWrap').innerHTML=`<div class="empty">⚠ ${e.message}</div>`;
    setLive(false);
  }
  btn.textContent='⟳ LIVE';
}
function setLive(on){
  document.getElementById('liveDot').className='dot'+(on?' live':'');
  document.getElementById('liveLabel').textContent=on?'LIVE':'OFFLINE';
}

function renderGames(games){
  const w=document.getElementById('gamesWrap');
  if(!games.length){w.innerHTML='<div class="empty">Keine HT/Q2 Spiele live<br><span style="font-size:9px">Europäische Ligen meist 18–22 Uhr</span></div>';return;}
  w.innerHTML=games.map(g=>gameCard(g)).join('');
}

function renderToday(games){
  const w=document.getElementById('todayWrap');
  if(!games.length){w.innerHTML='<div class="empty" style="font-size:10px">Keine Spiele heute</div>';return;}
  w.innerHTML=games.map(g=>todayCard(g)).join('');
}

function todayCard(g){
  const sc=g.status==='FT'?'var(--dim2)':g.status==='HT'?'var(--gold)':g.status==='NS'?'var(--dim)':'var(--green)';
  const q1tot=g.q1_home+g.q1_away;
  const q2tot=g.q2_home+g.q2_away;
  return `<div class="today-card">
    <div class="card-stripe" style="background:${sc}"></div>
    <div class="today-body">
      <div class="today-top">
        <span class="today-league">${g.league_name}</span>
        <span class="today-status" style="color:${sc}">${g.status}${g.timer?' '+g.timer+'′':''}</span>
      </div>
      <div class="today-teams">
        <div class="today-team">${g.home}</div>
        <div>
          <div class="today-score">${g.total_home}–${g.total_away}</div>
          <div class="today-q">Q1:${q1tot} Q2:${q2tot||'—'}</div>
        </div>
        <div class="today-team away">${g.away}</div>
      </div>
    </div>
  </div>`;
}

function gameCard(g){
  const timer=g.timer||0;
  const statusLabel=g.status==='HT'?'HALBZEIT':`Q2·${timer}′`;
  return `<div class="game-card" id="gc-${g.id}" onclick="selectCard(${g.id},${JSON.stringify(g.home)},${JSON.stringify(g.away)})">
    <div class="card-stripe"></div>
    <div class="card-body">
      <div class="card-top">
        <span class="card-league">${g.league_name}</span>
        <span class="card-status">${statusLabel}</span>
      </div>
      <div class="card-teams">
        <div class="card-team">${g.home}</div>
        <div class="card-score">
          <div class="score-num">${g.total_home}–${g.total_away}</div>
          <div class="score-q1">Q1:${g.q1_home}–${g.q1_away}</div>
        </div>
        <div class="card-team away">${g.away}</div>
      </div>
      <div class="card-stats">
        <div class="cs"><div class="cs-val">${g.q1_total}</div><div class="cs-lbl">Q1 Total</div></div>
        <div class="cs"><div class="cs-val">${g.q2_live||'—'}</div><div class="cs-lbl">Q2 live</div></div>
        <div class="cs"><div class="cs-val">${g.ht_total}</div><div class="cs-lbl">HT Total</div></div>
      </div>
      <div class="card-bot">
        <span style="font-size:9px;color:var(--dim2)">H2H + Line →</span>
        <span class="card-sig-badge none" id="badge-${g.id}">?</span>
        <span class="card-stufe c" id="stufe-${g.id}"></span>
      </div>
    </div>
    <div class="card-inputs" id="ci-${g.id}">
      <div class="inp-group"><label>H2H Ø</label><input type="number" id="ih2h-${g.id}" placeholder="96.5" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>Bookie Line</label><input type="number" id="iline-${g.id}" placeholder="91.5" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>Fouls</label><input type="number" id="ifouls-${g.id}" placeholder="5" min="0" inputmode="numeric"></div>
      <button class="calc-mini" onclick="event.stopPropagation();calcCard(${g.id},${g.q1_total},${g.q2_live||0},${timer})">▶ SIGNAL</button>
    </div>
  </div>`;
}

async function selectCard(id,home,away){
  document.querySelectorAll('.game-card').forEach(c=>{c.classList.remove('selected');const ci=c.querySelector('.card-inputs');if(ci)ci.classList.remove('open');});
  const card=document.getElementById('gc-'+id);
  if(card){card.classList.add('selected');document.getElementById('ci-'+id).classList.add('open');}
  if(home&&away){
    try{
      const r=await fetch(`/api/h2h?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}`);
      const d=await r.json();
      const inp=document.getElementById('ih2h-'+id);
      if(d.found&&inp&&!inp.value){
        inp.value=d.avg;
        const lbl=inp.closest('.inp-group')?.querySelector('label');
        if(lbl)lbl.textContent=`H2H Ø (${d.count}x)`;
      }
    }catch(e){}
  }
}

function calcCard(id,q1,q2live,timer){
  const h2h=parseFloat(document.getElementById('ih2h-'+id).value);
  const line=parseFloat(document.getElementById('iline-'+id).value);
  const fouls=parseFloat(document.getElementById('ifouls-'+id).value)||0;
  if(!h2h||!line){alert('H2H Ø und Bookie Line eingeben!');return;}
  const sig=engine({h2h,line,q1,q2:q2live,timer,fouls,ft:null,fg:null,lineDrop:false,lineRise:false});
  currentSig=sig;
  const card=document.getElementById('gc-'+id);
  const teams=card.querySelectorAll('.card-team');
  currentGameName=(teams[0]?.textContent||'')+' vs '+(teams[1]?.textContent||'');
  const cls=sig.dir==='UNDER'?'sig-under':sig.dir==='OVER'?'sig-over':'';
  card.className=`game-card selected ${cls} ${sig.stufe==='A'?'sig-a':''}`;
  const bEl=document.getElementById('badge-'+id);
  bEl.className=`card-sig-badge ${sig.dir.toLowerCase()}`;bEl.textContent=sig.dir;
  const sEl=document.getElementById('stufe-'+id);
  sEl.className=`card-stufe ${sig.stufe.toLowerCase()}`;sEl.textContent=sig.stufe==='C'?'SKIP':sig.stufe;
  renderSignal(sig);
  window.scrollTo({top:0,behavior:'smooth'});
}

function engine({h2h,line,q1,q2,timer,fouls,ft,fg,lineDrop,lineRise}){
  const timeLeft=Math.max(0,10-timer);
  let q2proj=timer>0.5&&q2>0?q2+(q2/timer)*timeLeft:q1;
  const proj=q1+q2proj;
  const buffer=proj-line;
  const foulsOC=fouls>=8,ftOC=ft!==null&&ft>=85,lineMC=lineDrop||lineRise;
  const overCat=foulsOC||ftOC||lineMC;
  const fgSkip=fg!==null&&fg>60;
  const entryOk=timeLeft>=2.5,entryA=timeLeft>=3.5;
  let dir='SKIP',stufe='C',reasons=[];
  if(buffer>=5&&entryOk&&fouls<8&&!fgSkip){
    dir='UNDER';
    if(entryA){stufe='A';reasons=[`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ 5</span>`,`<span class="r-ok">✓ Entry ${timeLeft.toFixed(1)}′</span>`,`<span class="r-ok">✓ Fouls ${fouls} &lt; 8</span>`];}
    else{stufe='B';reasons=[`<span class="r-warn">~ Buffer +${buffer.toFixed(1)}</span>`,`<span class="r-warn">~ Entry ${timeLeft.toFixed(1)}′</span>`];}
  }else if(buffer<=-3&&entryOk){
    dir='OVER';
    if(overCat){stufe='A';if(foulsOC)reasons.push(`<span class="r-ok">🔥 Fouls ${fouls} ≥ 8</span>`);if(ftOC)reasons.push(`<span class="r-ok">🔥 FT% ${ft}%</span>`);if(lineMC)reasons.push(`<span class="r-ok">🔥 Linie bewegt</span>`);}
    else{stufe='B';reasons.push(`<span class="r-warn">~ ${buffer.toFixed(1)} unter Linie</span>`);reasons.push(`<span class="r-warn">~ Kein Katalysator</span>`);}
    reasons.push(`<span class="r-ok">✓ Entry ${timeLeft.toFixed(1)}′</span>`);
  }else{
    if(fgSkip)reasons.push(`<span class="r-bad">✗ FG% ${fg}% &gt; 60</span>`);
    if(!entryOk)reasons.push(`<span class="r-bad">✗ Entry ${timeLeft.toFixed(1)}′ &lt; 2:30</span>`);
    if(Math.abs(buffer)<3)reasons.push(`<span class="r-bad">✗ Buffer ${buffer.toFixed(1)} &lt; 3</span>`);
    if(fouls>=8&&buffer>0)reasons.push(`<span class="r-warn">⚠ Fouls ≥8 → OVER?</span>`);
    if(!reasons.length)reasons.push(`<span class="r-bad">✗ Kein Signal</span>`);
  }
  return{dir,stufe,proj,buffer,timeLeft,fouls,reasons};
}

function renderSignal(sig){
  const sm=document.getElementById('sigMain');
  sm.className=`sig-main ${sig.dir.toLowerCase()} ${sig.stufe==='A'?'glow':''}`;
  const sd=document.getElementById('sigDir');
  sd.textContent=sig.dir;
  sd.style.color=sig.dir==='UNDER'?'var(--under)':sig.dir==='OVER'?'var(--over)':'var(--dim)';
  const se=document.getElementById('sigStufe');
  se.textContent=sig.stufe==='C'?'— SKIP —':`STUFE  ${sig.stufe}`;
  se.className=`sig-stufe st-${sig.stufe.toLowerCase()}`;
  document.getElementById('sigReasons').innerHTML=sig.reasons.join('<br>')||'—';
  document.getElementById('stProj').textContent=sig.proj.toFixed(1);
  const be=document.getElementById('stBuf');
  be.textContent=(sig.buffer>=0?'+':'')+sig.buffer.toFixed(1);
  be.className=`stat-v ${sig.buffer>=3?'pos':sig.buffer<=-3?'neg':''}`;
  const te=document.getElementById('stTime');
  te.textContent=sig.timeLeft.toFixed(1)+'′';
  te.className=`stat-v ${sig.timeLeft>=3.5?'pos':sig.timeLeft>=2.5?'gold':'neg'}`;
  const fe=document.getElementById('stFouls');
  fe.textContent=sig.fouls;
  fe.className=`stat-v ${sig.fouls>=8?'neg':''}`;
  const bar=document.getElementById('signalBar');
  bar.className=`signal-bar ${sig.dir==='UNDER'?'under':sig.dir==='OVER'?'over':''} ${sig.stufe==='A'?'glow':''}`;
  renderStake(sig);
}

function renderStake(sig){
  const ae=document.getElementById('stakeAmt'),de=document.getElementById('stakeDesc');
  if(sig.stufe==='C'){ae.textContent='—';ae.className='stake-amt none';de.textContent='Kein Trade';return;}
  let amt,desc;
  if(bankroll<100){amt=sig.stufe==='A'?5:2.5;desc=`Fix ${sig.stufe==='A'?'5€':'2.50€'}`;}
  else{const p=sig.stufe==='A'?0.05:0.025;amt=bankroll*p;desc=`${sig.stufe==='A'?'5':'2.5'}% von ${bankroll.toFixed(2)}€`;}
  ae.textContent=amt.toFixed(2)+'€';ae.className='stake-amt';de.textContent=desc;
}

function bookTrade(){
  if(!currentSig||currentSig.stufe==='C'){alert('Kein gültiges Signal!');return;}
  let amt=bankroll<100?(currentSig.stufe==='A'?5:2.5):bankroll*(currentSig.stufe==='A'?0.05:0.025);
  trades.unshift({id:Date.now(),game:currentGameName||'Manual',dir:currentSig.dir,stufe:currentSig.stufe,amt:amt.toFixed(2),result:'open'});
  if(trades.length>100)trades.pop();
  localStorage.setItem('hz_trades',JSON.stringify(trades));renderTradeLog();
}
function cycleResult(id){
  const t=trades.find(t=>t.id===id);if(!t)return;
  t.result={open:'win',win:'loss',loss:'open'}[t.result];
  localStorage.setItem('hz_trades',JSON.stringify(trades));renderTradeLog();
}
function renderTradeLog(){
  const rows=document.getElementById('tlRows');
  if(!trades.length){rows.innerHTML='<div style="font-size:10px;color:var(--dim);padding:3px 0">Noch keine Trades</div>';updateTlStats();return;}
  rows.innerHTML=trades.slice(0,8).map(t=>`<div class="tl-row"><span class="tl-game" title="${t.game}">${t.game.length>16?t.game.slice(0,14)+'…':t.game}</span><span class="tl-dir ${t.dir.toLowerCase()}">${t.dir}</span><span class="tl-amt">${t.amt}€</span><span class="tl-res ${t.result}" onclick="cycleResult(${t.id})">${t.result.toUpperCase()}</span></div>`).join('');
  updateTlStats();
}
function updateTlStats(){
  const w=trades.filter(t=>t.result==='win').length,l=trades.filter(t=>t.result==='loss').length;
  document.getElementById('tlStats').textContent=`${w}W / ${l}L`;
}
</script>
</body>
</html>"""


async def api_get(endpoint: str, params: dict) -> dict:
    headers = {
        "x-apisports-key": API_KEY,
        "x-rapidapi-host": "v1.basketball.api-sports.io",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{API_BASE}/{endpoint}", headers=headers, params=params)
        r.raise_for_status()
        return r.json()

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "api_key_set": bool(API_KEY),
        "sheets_configured": bool(SHEETS_ID and CREDS_JSON),
        "h2h_matchups": len(_h2h_cache),
    }

@app.get("/api/leagues")
async def get_leagues():
    return {"leagues": [{"id": k, "name": v[0], "season": v[1]} for k, v in LEAGUES.items()]}

@app.get("/api/live")
async def get_live_games():
    if not API_KEY:
        return {"games": _demo_games(), "today": _demo_today(), "source": "demo", "count": 3}

    from datetime import date
    today_str = date.today().isoformat()
    live_results, today_results, seen_ids = [], [], set()

    for league_id, (name, season) in LEAGUES.items():
        try:
            data = await api_get("games", {"league": league_id, "season": season, "live": "all"})
            for g in (data.get("response") or []):
                gid = g.get("id")
                if gid in seen_ids:
                    continue
                seen_ids.add(gid)
                status = g.get("status", {}).get("short", "")
                ng = _normalize_game(g, league_id, name)
                if status in ("HT", "Q2"):
                    live_results.append(ng)
                else:
                    today_results.append(ng)
        except Exception:
            continue
        try:
            data2 = await api_get("games", {"league": league_id, "season": season, "date": today_str})
            for g in (data2.get("response") or []):
                gid = g.get("id")
                if gid not in seen_ids:
                    seen_ids.add(gid)
                    today_results.append(_normalize_game(g, league_id, name))
        except Exception:
            continue

    return {"games": live_results, "today": today_results[:30], "source": "live", "count": len(live_results)}

@app.get("/api/games")
async def get_games(league: int, season: str = "2025-2026", date: Optional[str] = None):
    if not API_KEY:
        return {"response": [], "error": "No API key configured"}
    params = {"league": league, "season": season}
    if date:
        params["date"] = date
    try:
        return await api_get("games", params)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/api/h2h")
async def get_h2h(home: str, away: str):
    key = _matchup_key(home, away)
    vals = _h2h_cache.get(key, [])
    avg = round(sum(vals) / len(vals), 1) if vals else None
    return {"avg": avg, "count": len(vals), "found": avg is not None}

@app.get("/api/trigger-extract")
async def trigger_extract():
    await _extract_ft_games()
    return {"status": "ok", "cached_matchups": len(_h2h_cache)}

def _normalize_game(g: dict, league_id: int, league_name: str) -> dict:
    scores = g.get("scores", {})
    home_s = scores.get("home", {})
    away_s = scores.get("away", {})
    q1h = home_s.get("quarter_1") or 0
    q1a = away_s.get("quarter_1") or 0
    q2h = home_s.get("quarter_2") or 0
    q2a = away_s.get("quarter_2") or 0
    total_h = home_s.get("total") or 0
    total_a = away_s.get("total") or 0
    return {
        "id": g.get("id"),
        "league_id": league_id,
        "league_name": g.get("league", {}).get("name", league_name),
        "status": g.get("status", {}).get("short", ""),
        "timer": g.get("status", {}).get("timer"),
        "home": g.get("teams", {}).get("home", {}).get("name", "Home"),
        "away": g.get("teams", {}).get("away", {}).get("name", "Away"),
        "q1_home": q1h, "q1_away": q1a,
        "q2_home": q2h, "q2_away": q2a,
        "total_home": total_h, "total_away": total_a,
        "q1_total": q1h + q1a,
        "q2_live": q2h + q2a,
        "ht_total": total_h + total_a,
    }

def _demo_games():
    return [
        {"id": 1001, "league_id": 4, "league_name": "ACB", "status": "HT", "timer": None,
         "home": "Real Madrid", "away": "FC Barcelona",
         "q1_home": 28, "q1_away": 24, "q2_home": 0, "q2_away": 0,
         "total_home": 28, "total_away": 24, "q1_total": 52, "q2_live": 0, "ht_total": 52},
        {"id": 1002, "league_id": 120, "league_name": "TBL", "status": "Q2", "timer": 5,
         "home": "Fenerbahce", "away": "Galatasaray",
         "q1_home": 31, "q1_away": 27, "q2_home": 18, "q2_away": 14,
         "total_home": 49, "total_away": 41, "q1_total": 58, "q2_live": 32, "ht_total": 90},
        {"id": 1003, "league_id": 6, "league_name": "ABA Liga", "status": "HT", "timer": None,
         "home": "Crvena zvezda", "away": "Partizan",
         "q1_home": 22, "q1_away": 26, "q2_home": 0, "q2_away": 0,
         "total_home": 22, "total_away": 26, "q1_total": 48, "q2_live": 0, "ht_total": 48},
    ]

def _demo_today():
    return [
        {"id": 2001, "league_id": 3, "league_name": "EuroLeague", "status": "FT", "timer": None,
         "home": "Olympiacos", "away": "CSKA", "q1_home": 24, "q1_away": 22,
         "q2_home": 18, "q2_away": 26, "total_home": 78, "total_away": 82,
         "q1_total": 46, "q2_live": 44, "ht_total": 90},
        {"id": 2002, "league_id": 8, "league_name": "Lega A", "status": "FT", "timer": None,
         "home": "Olimpia Milano", "away": "Virtus Bologna", "q1_home": 26, "q1_away": 21,
         "q2_home": 22, "q2_away": 24, "total_home": 88, "total_away": 79,
         "q1_total": 47, "q2_live": 46, "ht_total": 93},
    ]


# ---------- Google Sheets helpers ----------

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
        creds_data = json.loads(CREDS_JSON)
        gc = gspread.service_account_from_dict(creds_data)
        sh = gc.open_by_key(SHEETS_ID)
        try:
            _ws = sh.worksheet(SHEETS_TAB)
        except gspread.WorksheetNotFound:
            _ws = sh.add_worksheet(title=SHEETS_TAB, rows=1000, cols=10)
            _ws.append_row(["date", "home", "away", "league",
                            "q1_total", "q2_total", "ht_total", "ft_total"])
        return _ws
    except Exception as e:
        logging.warning("Google Sheets init failed: %s", e)
        return None


def _load_h2h_from_sheet() -> None:
    global _h2h_cache, _seen_ft_ids
    ws = _get_worksheet()
    if ws is None:
        return
    try:
        rows = ws.get_all_records()
        _h2h_cache = {}
        _seen_ft_ids = set()
        for row in rows:
            home = str(row.get("home", "")).strip()
            away = str(row.get("away", "")).strip()
            ft_total = row.get("ft_total")
            game_key = f"{row.get('date', '')}-{home}-{away}"
            _seen_ft_ids.add(game_key)
            if home and away and ft_total:
                key = _matchup_key(home, away)
                _h2h_cache.setdefault(key, []).append(float(ft_total))
        logging.info("Loaded %d matchups from Google Sheets", len(_h2h_cache))
    except Exception as e:
        logging.warning("Failed to load H2H from sheet: %s", e)


async def _extract_ft_games() -> None:
    """Fetch today's finished games, write new rows to Google Sheets, update cache."""
    if not API_KEY:
        return
    from datetime import date as _date
    today_str = _date.today().isoformat()
    new_rows = []
    for league_id, (name, season) in LEAGUES.items():
        try:
            data = await api_get("games", {"league": league_id, "season": season, "date": today_str})
            for g in (data.get("response") or []):
                if g.get("status", {}).get("short", "") != "FT":
                    continue
                ng = _normalize_game(g, league_id, name)
                home, away = ng["home"], ng["away"]
                game_key = f"{today_str}-{home}-{away}"
                if game_key in _seen_ft_ids:
                    continue
                _seen_ft_ids.add(game_key)
                ft_total = ng["total_home"] + ng["total_away"]
                q2_total = ng["q2_home"] + ng["q2_away"]
                new_rows.append([today_str, home, away, ng["league_name"],
                                  ng["q1_total"], q2_total, ng["ht_total"], ft_total])
                _h2h_cache.setdefault(_matchup_key(home, away), []).append(float(ft_total))
        except Exception as e:
            logging.warning("FT extraction failed for league %s: %s", league_id, e)
            continue

    if not new_rows:
        return
    logging.info("Extracted %d new FT games", len(new_rows))
    ws = await asyncio.to_thread(_get_worksheet)
    if ws:
        try:
            await asyncio.to_thread(ws.append_rows, new_rows, value_input_option="USER_ENTERED")
            logging.info("Wrote %d rows to Google Sheets", len(new_rows))
        except Exception as e:
            logging.warning("Failed to write to Google Sheets: %s", e)


async def _scheduler_loop() -> None:
    """On startup: load H2H cache from sheet; then extract FT games every 30 min."""
    await asyncio.to_thread(_load_h2h_from_sheet)
    while True:
        try:
            await _extract_ft_games()
        except Exception as e:
            logging.warning("Scheduler error: %s", e)
        await asyncio.sleep(1800)

