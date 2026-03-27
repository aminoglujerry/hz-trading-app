from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from typing import Optional

app = FastAPI(title="HZ Trading App")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_KEY = os.getenv("API_SPORTS_KEY", "")
API_BASE = "https://v1.basketball.api-sports.io"

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

/* ─── TABS ───────────────────────────── */
.tab-nav{display:flex;border-bottom:1px solid var(--border);background:var(--s1);}
.tab-btn{background:none;border:none;border-bottom:2px solid transparent;color:var(--dim2);font-family:'Barlow',sans-serif;font-size:9px;letter-spacing:2px;text-transform:uppercase;padding:10px 18px;cursor:pointer;transition:all .15s;}
.tab-btn.active{color:var(--white);border-bottom-color:var(--green);}
.tab-btn:hover:not(.active){color:var(--text);}

/* ─── DASHBOARD ──────────────────────── */
.dash{padding:14px;}
.dash-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;}
.dash-title{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--dim);}
.dash-info{font-size:9px;color:var(--dim2);}
.count-badge{background:var(--green);color:var(--bg);font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:700;padding:1px 8px;display:inline-block;margin-left:5px;}

/* Alert Cards */
.alerts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px;margin-bottom:20px;}
.alert-card{background:var(--s2);border:1px solid var(--border);animation:fadeIn .3s ease;}
.alert-card.under{border-color:rgba(0,180,216,.4);box-shadow:0 0 16px rgba(0,180,216,.07);}
.alert-card.over{border-color:rgba(230,57,70,.4);box-shadow:0 0 16px rgba(230,57,70,.07);}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.alert-top{padding:10px 12px 8px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:flex-start;gap:8px;}
.alert-game-info{display:flex;flex-direction:column;gap:2px;min-width:0;}
.alert-league{font-size:8px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dim2);}
.alert-teams{font-family:'Barlow Condensed',sans-serif;font-size:14px;font-weight:700;color:var(--white);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.alert-score{font-size:10px;color:var(--gold);}
.alert-conf{display:flex;flex-direction:column;align-items:flex-end;gap:1px;flex-shrink:0;}
.conf-pct{font-family:'Barlow Condensed',sans-serif;font-size:28px;font-weight:900;line-height:1;}
.conf-pct.high{color:var(--green);}
.conf-pct.med{color:var(--gold);}
.conf-pct.low{color:var(--dim2);}
.conf-label{font-size:7px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dim);}
.alert-signals{padding:8px 12px;display:flex;flex-direction:column;gap:6px;}
.signal-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}
.sig-badge{font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;padding:2px 6px;border:1px solid;}
.sig-badge.under{color:var(--under);border-color:rgba(0,180,216,.4);}
.sig-badge.over{color:var(--over);border-color:rgba(230,57,70,.4);}
.sig-badge.watch{color:var(--gold);border-color:rgba(244,162,97,.4);}
.sig-badge.skip{color:var(--dim);border-color:var(--border);}
.sig-tag{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);padding:2px 5px;border:1px solid var(--border);flex-shrink:0;}
.sig-meta{font-size:9px;color:var(--dim2);}
.alert-skip-row{padding:6px 12px;background:rgba(230,57,70,.04);border-top:1px solid rgba(230,57,70,.15);font-size:9px;color:var(--over);}
.alert-actions{padding:8px 12px;border-top:1px solid var(--border);display:flex;gap:6px;}
.btn-book{flex:1;background:var(--green);border:none;color:var(--bg);font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:900;letter-spacing:2px;padding:7px;cursor:pointer;text-transform:uppercase;}
.btn-book:hover{background:#35d460;}
.no-alerts{text-align:center;padding:32px 14px;color:var(--dim);border:1px dashed var(--border);font-size:10px;line-height:2.5;}

/* Filter Bar */
.filter-bar{display:flex;gap:4px;flex-wrap:wrap;}
.filter-btn{background:none;border:1px solid var(--border2);color:var(--dim2);font-family:'Barlow',sans-serif;font-size:8px;letter-spacing:1.5px;text-transform:uppercase;padding:5px 12px;cursor:pointer;transition:all .15s;}
.filter-btn:hover{border-color:var(--dim);color:var(--text);}
.filter-btn.active{background:var(--border2);color:var(--white);border-color:var(--dim);}

/* Games Table */
.gt-wrap{overflow-x:auto;margin-top:8px;}
table.gt{width:100%;border-collapse:collapse;font-size:9px;}
table.gt th{font-size:7px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dim);padding:6px 8px;border-bottom:1px solid var(--border);white-space:nowrap;text-align:left;}
table.gt td{padding:5px 8px;border-bottom:1px solid var(--border);color:var(--text);white-space:nowrap;vertical-align:middle;}
table.gt tr:hover td{background:var(--s1);}
table.gt tr.is-alert td:first-child{border-left:2px solid var(--green);}
.td-under{color:var(--under);font-weight:700;}
.td-over{color:var(--over);font-weight:700;}
.td-watch{color:var(--gold);}
.td-skip{color:var(--dim);}
.td-conf{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;}
.td-conf.high{color:var(--green);}
.td-conf.med{color:var(--gold);}
.td-conf.low{color:var(--dim2);}
.td-st{font-size:8px;padding:2px 5px;border:1px solid;}
.td-st.live{color:var(--gold);border-color:rgba(244,162,97,.3);}
.td-st.ht{color:var(--green);border-color:rgba(45,198,83,.3);}
.td-st.ns{color:var(--dim);border-color:var(--border);}
.td-st.ft{color:var(--dim2);border-color:var(--border);}
.td-act{cursor:pointer;color:var(--green);font-size:11px;text-align:center;}
.td-act:hover{color:var(--white);}

@media(max-width:700px){
  .alerts-grid{grid-template-columns:1fr;}
  .gt-wrap{font-size:8px;}
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
<div class="tab-nav">
  <button class="tab-btn active" id="tabBtnHz" onclick="showTab('hz')">⚡ HZ CLASSIC</button>
  <button class="tab-btn" id="tabBtnDash" onclick="showTab('dash')">📊 LIVE DASHBOARD</button>
</div>

<div id="viewHz">
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

</div><!-- end #viewHz -->

<div id="viewDash" style="display:none;">
<div class="dash">
  <div class="dash-header">
    <div>
      <span class="dash-title">🔴 Alerts</span>
      <span class="count-badge" id="alertCount">0</span>
    </div>
    <span class="dash-info" id="dashTs">—</span>
  </div>
  <div class="alerts-grid" id="alertsGrid">
    <div class="no-alerts">📊 Dashboard lädt…<br><span style="font-size:9px">Klicke auf LIVE DASHBOARD um zu starten</span></div>
  </div>

  <div class="dash-header" style="margin-top:4px;">
    <span class="dash-title">Alle Spiele</span>
    <div class="filter-bar" id="filterBar">
      <button class="filter-btn active" onclick="setFilter(this,'all')">ALLE</button>
      <button class="filter-btn" onclick="setFilter(this,'hz')">HZ-SIGNALE</button>
      <button class="filter-btn" onclick="setFilter(this,'ft')">FT-SIGNALE</button>
      <button class="filter-btn" onclick="setFilter(this,'alerts')">ALERTS</button>
      <button class="filter-btn" onclick="setFilter(this,'skip')">SKIPPED</button>
    </div>
  </div>
  <div class="gt-wrap">
    <table class="gt">
      <thead><tr>
        <th>Liga</th><th>Spiel</th><th>Status</th>
        <th>Total</th><th>Lead</th><th>Pace</th>
        <th>HZ Signal</th><th>FT Signal</th><th>Alert%</th><th>Skip?</th><th></th>
      </tr></thead>
      <tbody id="gamesTableBody">
        <tr><td colspan="11" style="text-align:center;padding:20px;color:var(--dim)">Keine Spiele geladen</td></tr>
      </tbody>
    </table>
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
  return `<div class="game-card" id="gc-${g.id}" onclick="selectCard(${g.id})">
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

function selectCard(id){
  document.querySelectorAll('.game-card').forEach(c=>{c.classList.remove('selected');const ci=c.querySelector('.card-inputs');if(ci)ci.classList.remove('open');});
  const card=document.getElementById('gc-'+id);
  if(card){card.classList.add('selected');document.getElementById('ci-'+id).classList.add('open');}
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

// ─── TAB SWITCHING ────────────────────
let currentTab='hz',dashInterval=null,currentFilter='all',allScreenedGames=[];
function showTab(tab){
  currentTab=tab;
  document.getElementById('viewHz').style.display=tab==='hz'?'':'none';
  document.getElementById('viewDash').style.display=tab==='dash'?'':'none';
  document.getElementById('tabBtnHz').classList.toggle('active',tab==='hz');
  document.getElementById('tabBtnDash').classList.toggle('active',tab==='dash');
  if(tab==='dash'){
    loadScreened();
    if(!dashInterval)dashInterval=setInterval(loadScreened,30000);
  }else{
    if(dashInterval){clearInterval(dashInterval);dashInterval=null;}
  }
}

// ─── SCREENING DASHBOARD ─────────────
async function loadScreened(){
  try{
    const r=await fetch('/api/live/screened');
    const data=await r.json();
    renderAlerts(data.alerts||[]);
    allScreenedGames=data.all_games||[];
    renderGameTable(allScreenedGames);
    document.getElementById('alertCount').textContent=data.count_alerts||0;
    const ts=data.timestamp?new Date(data.timestamp).toLocaleTimeString():'—';
    document.getElementById('dashTs').textContent='⟳ '+ts+' · '+((data.all_games||[]).length)+' Spiele';
    setLive(data.source==='live');
  }catch(e){
    document.getElementById('alertsGrid').innerHTML=`<div class="no-alerts">⚠ ${e.message}</div>`;
  }
}

function renderAlerts(alerts){
  const grid=document.getElementById('alertsGrid');
  if(!alerts.length){
    grid.innerHTML='<div class="no-alerts">Keine Alerts<br><span style="font-size:9px;color:var(--dim)">Alle Spiele werden automatisch gescreened — Alerts erscheinen sobald Signale erkannt werden</span></div>';
    return;
  }
  grid.innerHTML=alerts.map((g,i)=>alertCard(g,i)).join('');
}

function alertCard(g,idx){
  const hz=g.hz_result||{},ft=g.ft_result||{};
  const conf=g.alert_level||0;
  const confCls=conf>=70?'high':conf>=45?'med':'low';
  const hzSig=hz.signal||'SKIP',ftSig=ft.signal||'SKIP';
  const dirCls=hzSig==='UNDER'||ftSig==='UNDER'?'under':hzSig==='OVER'||ftSig==='OVER'?'over':'';
  function sigRow(tag,res){
    if(!res||res.signal==='SKIP')return'';
    const sc=res.signal.toLowerCase();
    let meta='';
    if(res.buffer!=null)meta+=`Buffer ${res.buffer>=0?'+':''}${res.buffer} `;
    if(res.time_left!=null)meta+=`${res.time_left}′ `;
    if(res.pace!=null)meta+=`Pace ${res.pace}`;
    return `<div class="signal-row">
      <span class="sig-tag">${tag}</span>
      <span class="sig-badge ${sc}">${res.signal}</span>
      ${res.stufe&&res.stufe!=='C'?`<span class="sig-tag">STF ${res.stufe}</span>`:''}
      ${meta?`<span class="sig-meta">${meta.trim()}</span>`:''}
    </div>`;
  }
  return `<div class="alert-card ${dirCls}">
    <div class="alert-top">
      <div class="alert-game-info">
        <span class="alert-league">${g.league_name} · ${g.status}${g.timer?' '+g.timer+'′':''}</span>
        <span class="alert-teams" title="${g.home} vs ${g.away}">${g.home} vs ${g.away}</span>
        <span class="alert-score">${g.total_home}–${g.total_away}${g.lead?' · Lead '+g.lead:''}</span>
      </div>
      <div class="alert-conf">
        <span class="conf-pct ${confCls}">${conf}%</span>
        <span class="conf-label">Alert</span>
      </div>
    </div>
    <div class="alert-signals">
      ${sigRow('HZ',hz)}
      ${sigRow('FT',ft)}
      ${hzSig==='SKIP'&&ftSig==='SKIP'?`<div class="signal-row"><span class="sig-badge skip">SKIP</span><span class="sig-meta">${hz.reason||ft.reason||'—'}</span></div>`:''}
    </div>
    ${g.skip_reason?`<div class="alert-skip-row">⊘ ${g.skip_reason}</div>`:''}
    <div class="alert-actions">
      <button class="btn-book" onclick="bookFromAlert(${g.id})">+ Trade buchen</button>
    </div>
  </div>`;
}

function setFilter(btn,f){
  currentFilter=f;
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  renderGameTable(allScreenedGames);
}

function renderGameTable(games){
  const tbody=document.getElementById('gamesTableBody');
  let filtered=games;
  if(currentFilter==='hz')filtered=games.filter(g=>g.hz_result&&g.hz_result.signal&&g.hz_result.signal!=='SKIP');
  else if(currentFilter==='ft')filtered=games.filter(g=>g.ft_result&&g.ft_result.signal&&g.ft_result.signal!=='SKIP');
  else if(currentFilter==='alerts')filtered=games.filter(g=>g.is_alert);
  else if(currentFilter==='skip')filtered=games.filter(g=>g.skip_reason);
  if(!filtered.length){tbody.innerHTML='<tr><td colspan="11" style="text-align:center;padding:20px;color:var(--dim)">Keine Spiele in dieser Kategorie</td></tr>';return;}
  tbody.innerHTML=filtered.map(g=>{
    const hz=g.hz_result||{},ft=g.ft_result||{};
    const conf=g.alert_level||0;
    const confCls=conf>=70?'high':conf>=45?'med':'low';
    function sigCls(s){return s==='UNDER'?'td-under':s==='OVER'?'td-over':s==='WATCH'?'td-watch':'td-skip';}
    const stMap={HT:'ht',Q2:'live',Q3:'ht',Q4:'live',FT:'ft',NS:'ns'};
    const stCls=stMap[g.status]||'ns';
    return `<tr class="${g.is_alert?'is-alert':''}">
      <td style="font-size:8px;color:var(--dim2);max-width:80px;overflow:hidden;text-overflow:ellipsis">${g.league_name}</td>
      <td><span style="font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:700">${g.home} vs ${g.away}</span></td>
      <td><span class="td-st ${stCls}">${g.status}${g.timer?' '+g.timer+'′':''}</span></td>
      <td style="font-family:'Barlow Condensed',sans-serif">${g.total_home}–${g.total_away}</td>
      <td>${g.lead!=null?g.lead+' Pkt':'—'}</td>
      <td>${g.pace||'—'}</td>
      <td class="${sigCls(hz.signal)}">${hz.signal||'—'}</td>
      <td class="${sigCls(ft.signal)}">${ft.signal||'—'}</td>
      <td><span class="td-conf ${confCls}">${conf>0?conf+'%':'—'}</span></td>
      <td style="font-size:8px;color:var(--over);max-width:120px;overflow:hidden;text-overflow:ellipsis">${g.skip_reason||''}</td>
      <td class="td-act" onclick="bookFromAlert(${g.id})">+</td>
    </tr>`;
  }).join('');
}

function bookFromAlert(gameId){
  const game=allScreenedGames.find(g=>g.id===gameId);
  if(!game){alert('Spiel nicht gefunden');return;}
  const hz=game.hz_result||{},ft=game.ft_result||{};
  const sig=hz.signal&&hz.signal!=='SKIP'?hz:ft.signal&&ft.signal!=='SKIP'?ft:null;
  if(!sig||sig.signal==='SKIP'){alert('Kein gültiges Signal für dieses Spiel!');return;}
  const stufe=sig.stufe||'B';
  const amt=bankroll<100?(stufe==='A'?5:2.5):bankroll*(stufe==='A'?0.05:0.025);
  const dir=sig.signal;
  const gameName=game.home+' vs '+game.away;
  const engine=hz.signal&&hz.signal!=='SKIP'?'hz':'ft';
  trades.unshift({id:Date.now(),game:gameName,dir,stufe,amt:amt.toFixed(2),result:'open',engine});
  if(trades.length>100)trades.pop();
  localStorage.setItem('hz_trades',JSON.stringify(trades));
  renderTradeLog();
  showTab('hz');
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
    return {"status": "ok", "api_key_set": bool(API_KEY)}

@app.get("/api/leagues")
async def get_leagues():
    return {"leagues": [{"id": k, "name": v[0], "season": v[1]} for k, v in LEAGUES.items()]}

@app.get("/api/live")
async def get_live_games():
    if not API_KEY:
        demo_live = [g for g in _demo_games() if g["status"] in ("HT", "Q2")]
        demo_today = [g for g in _demo_games() if g["status"] not in ("HT", "Q2")] + _demo_today()
        return {"games": demo_live, "today": demo_today, "source": "demo", "count": len(demo_live)}

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

# ─── Screening Constants ───────────────────────────────────────────────────
QUARTER_DURATION = 10.0          # minutes per quarter
HZ_MIN_ENTRY_TIME = 2.5          # minimum time remaining in Q2 for HZ entry
HZ_ENTRY_PRIME = 3.5             # prime entry window threshold
HZ_UNDER_MIN_BUFFER = 5.0        # projection must be ≥5 pts above line for UNDER
HZ_OVER_MAX_BUFFER = -3.0        # projection must be ≤-3 pts below line for OVER
HZ_MAX_FOULS_FOR_UNDER = 8       # fouls below this allow UNDER; above → possible catalyst
FT_OVER_MAX_BUFFER = -8.0        # projection ≥8 pts under line → OVER signal
FT_UNDER_MIN_BUFFER = 10.0       # projection ≥10 pts over line → UNDER signal
LOW_PACE_THRESHOLD = 5.0         # pts/min pace below which UNDER is favoured
FT_MIN_FOULS_FOR_OVER = 25       # fouls required to trigger OVER
FT_MIN_FT_PCT = 75.0             # minimum FT% for both teams for OVER
FT_HIGH_FT_PCT = 80.0            # Stufe A FT% threshold
BLOWOUT_LEAD = 20                # lead ≥ this → skip regardless of signal
FT_LATE_ENTRY_MINUTE = 37        # Q4 minute after which entry is too late (timer ≥ 7)
# ──────────────────────────────────────────────────────────────────────────

def check_skip_conditions(game: dict):
    """Universal skip checks. Returns a skip reason string or None."""
    lead = game.get("lead") or 0
    if lead >= BLOWOUT_LEAD:
        return f"Lead {lead} Pkt ≥ {BLOWOUT_LEAD}"
    return None


def check_hz_rules(game: dict) -> dict:
    """Check HZ (Halftime) signal. Returns dict with signal/stufe/confidence/reason."""
    status = game.get("status", "")
    if status not in ("HT", "Q2"):
        return {"signal": "SKIP", "stufe": "C", "confidence": 0, "reason": "Nicht HT/Q2"}
    skip = check_skip_conditions(game)
    if skip:
        return {"signal": "SKIP", "stufe": "C", "confidence": 0, "reason": skip}
    timer = game.get("timer") or 0
    time_left = max(0.0, QUARTER_DURATION - timer) if status == "Q2" else QUARTER_DURATION
    if time_left < HZ_MIN_ENTRY_TIME:
        return {"signal": "SKIP", "stufe": "C", "confidence": 0,
                "reason": f"Entry {time_left:.1f}′ zu spät"}
    q1_total = game.get("q1_total") or 0
    q2_live = game.get("q2_live") or 0
    fouls = game.get("fouls_total") or 0
    bookie_line = game.get("bookie_line")
    if status == "Q2" and timer > 0.5 and q2_live > 0:
        q2_proj = q2_live + (q2_live / timer) * time_left
    else:
        q2_proj = float(q1_total)
    proj = float(q1_total) + q2_proj
    if not bookie_line:
        confidence = 25 + (15 if time_left >= HZ_ENTRY_PRIME else 0)
        return {"signal": "WATCH", "stufe": "B", "confidence": confidence,
                "proj": round(proj, 1), "time_left": round(time_left, 1),
                "reason": "Bookie-Linie fehlt"}
    buffer = proj - bookie_line
    if buffer >= HZ_UNDER_MIN_BUFFER and fouls < HZ_MAX_FOULS_FOR_UNDER:
        confidence = min(92, 50 + int(buffer * 4) + (10 if time_left >= HZ_ENTRY_PRIME else 0))
        stufe = "A" if time_left >= HZ_ENTRY_PRIME else "B"
        return {"signal": "UNDER", "stufe": stufe, "confidence": confidence,
                "proj": round(proj, 1), "buffer": round(buffer, 1),
                "time_left": round(time_left, 1), "reason": None}
    if buffer <= HZ_OVER_MAX_BUFFER:
        over_cat = fouls >= HZ_MAX_FOULS_FOR_UNDER
        confidence = min(92, 45 + int(abs(buffer) * 4) + (15 if over_cat else 0))
        stufe = "A" if over_cat else "B"
        return {"signal": "OVER", "stufe": stufe, "confidence": confidence,
                "proj": round(proj, 1), "buffer": round(buffer, 1),
                "time_left": round(time_left, 1), "reason": None}
    return {"signal": "SKIP", "stufe": "C", "confidence": 0,
            "proj": round(proj, 1), "buffer": round(buffer, 1),
            "reason": f"Buffer {buffer:+.1f} zu klein", "time_left": round(time_left, 1)}


def check_ft_rules(game: dict) -> dict:
    """Check FT-Total signal (Q3/Q4 break). Returns dict with signal/stufe/confidence/reason."""
    status = game.get("status", "")
    if status not in ("Q3", "Q4"):
        return {"signal": "SKIP", "stufe": "C", "confidence": 0, "reason": "Nicht Q3/Q4"}
    timer = game.get("timer") or 0
    # After minute 37 means 7+ minutes into Q4 (30 + 7 = 37)
    if status == "Q4" and timer >= (FT_LATE_ENTRY_MINUTE - 30):
        return {"signal": "SKIP", "stufe": "C", "confidence": 0,
                "reason": f"Nach Minute {int(30 + timer)}"}
    skip = check_skip_conditions(game)
    if skip:
        return {"signal": "SKIP", "stufe": "C", "confidence": 0, "reason": skip}
    total_now = (game.get("total_home") or 0) + (game.get("total_away") or 0)
    if status == "Q3":
        mins_played = 2 * QUARTER_DURATION + timer
        time_remaining = (QUARTER_DURATION - timer) + QUARTER_DURATION
    else:
        mins_played = 3 * QUARTER_DURATION + timer
        time_remaining = max(0.0, QUARTER_DURATION - timer)
    pace = game.get("pace") or 0
    if not pace and mins_played > 0:
        pace = total_now / mins_played
    proj_ft = round(total_now + pace * time_remaining, 1) if pace > 0 else 0
    bookie_line = game.get("bookie_line")
    ft_home = game.get("ft_home")
    ft_away = game.get("ft_away")
    fouls = game.get("fouls_total") or 0
    if not bookie_line:
        confidence = 25 + (15 if status == "Q3" else 0)
        return {"signal": "WATCH", "stufe": "B", "confidence": confidence,
                "proj": proj_ft, "pace": round(pace, 1), "reason": "Bookie-Linie fehlt"}
    buffer = proj_ft - bookie_line
    lead = game.get("lead") or 0
    if lead >= BLOWOUT_LEAD:
        return {"signal": "SKIP", "stufe": "C", "confidence": 0,
                "reason": f"Lead {lead} ≥ {BLOWOUT_LEAD}"}
    ft_both_75 = bool(ft_home and ft_away and ft_home >= FT_MIN_FT_PCT and ft_away >= FT_MIN_FT_PCT)
    ft_both_80 = bool(ft_home and ft_away and ft_home >= FT_HIGH_FT_PCT and ft_away >= FT_HIGH_FT_PCT)
    ft_one_low = bool((ft_home and ft_home < FT_MIN_FT_PCT) or (ft_away and ft_away < FT_MIN_FT_PCT))
    # OVER signal: projection is 8+ under bookie line → expect score to go over
    if buffer <= FT_OVER_MAX_BUFFER:
        if ft_one_low:
            return {"signal": "SKIP", "stufe": "C", "confidence": 0,
                    "reason": f"FT% < {FT_MIN_FT_PCT:.0f}%"}
        if fouls > 0 and fouls < FT_MIN_FOULS_FOR_OVER:
            return {"signal": "SKIP", "stufe": "C", "confidence": 0,
                    "reason": f"Fouls {fouls} < {FT_MIN_FOULS_FOR_OVER}"}
        confidence = min(92, 50 + int(abs(buffer) * 3))
        if ft_both_80 and abs(buffer) >= 10:
            stufe = "A"
            confidence = min(95, confidence + 15)
        elif ft_both_75:
            stufe = "B"
        else:
            stufe = "B"
        return {"signal": "OVER", "stufe": stufe, "confidence": confidence,
                "proj": proj_ft, "buffer": round(buffer, 1),
                "pace": round(pace, 1), "reason": None}
    # UNDER signal: projection is FT_UNDER_MIN_BUFFER+ over bookie line + low pace
    if buffer >= FT_UNDER_MIN_BUFFER:
        low_pace = pace < LOW_PACE_THRESHOLD
        if low_pace:
            confidence = min(92, 50 + int(buffer * 2.5))
            stufe = "A" if buffer >= FT_UNDER_MIN_BUFFER * 1.2 else "B"
            return {"signal": "UNDER", "stufe": stufe, "confidence": confidence,
                    "proj": proj_ft, "buffer": round(buffer, 1),
                    "pace": round(pace, 1), "reason": None}
    return {"signal": "SKIP", "stufe": "C", "confidence": 0,
            "proj": proj_ft, "buffer": round(buffer, 1),
            "pace": round(pace, 1), "reason": f"Buffer {buffer:+.1f} kein Signal"}


def calculate_alert_level(hz_result: dict, ft_result: dict) -> int:
    """Return 0-100 alert confidence based on both signals."""
    hz_conf = hz_result.get("confidence", 0) if hz_result.get("signal") not in ("SKIP", None) else 0
    ft_conf = ft_result.get("confidence", 0) if ft_result.get("signal") not in ("SKIP", None) else 0
    return min(100, max(hz_conf, ft_conf))


def screen_all_games(games: list) -> list:
    """Apply screening rules to all games and annotate with signal info."""
    result = []
    for game in games:
        skip_reason = check_skip_conditions(game)
        hz_result = check_hz_rules(game)
        ft_result = check_ft_rules(game)
        alert_level = calculate_alert_level(hz_result, ft_result)
        hz_sig = hz_result.get("signal", "SKIP")
        ft_sig = ft_result.get("signal", "SKIP")
        is_alert = (
            (hz_sig not in ("SKIP", "WATCH") or ft_sig not in ("SKIP", "WATCH"))
            and skip_reason is None
            and alert_level >= 40
        )
        result.append({
            **game,
            "hz_result": hz_result,
            "ft_result": ft_result,
            "skip_reason": skip_reason,
            "alert_level": alert_level,
            "is_alert": is_alert,
        })
    return result


@app.get("/api/live/screened")
async def get_screened_games():
    """Return all live games with screening signals plus top-10 alerts."""
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    if not API_KEY:
        all_demo = _demo_games() + _demo_today()
        screened = screen_all_games(all_demo)
        alerts = sorted([g for g in screened if g["is_alert"]], key=lambda x: -x["alert_level"])[:10]
        return {"alerts": alerts, "all_games": screened,
                "count_alerts": len(alerts), "timestamp": timestamp, "source": "demo"}
    all_games: list = []
    seen_ids: set = set()
    for league_id, (name, season) in LEAGUES.items():
        try:
            data = await api_get("games", {"league": league_id, "season": season, "live": "all"})
            for g in (data.get("response") or []):
                gid = g.get("id")
                if gid in seen_ids:
                    continue
                seen_ids.add(gid)
                all_games.append(_normalize_game(g, league_id, name))
        except Exception:
            continue
    screened = screen_all_games(all_games)
    alerts = sorted([g for g in screened if g["is_alert"]], key=lambda x: -x["alert_level"])[:10]
    return {"alerts": alerts, "all_games": screened,
            "count_alerts": len(alerts), "timestamp": timestamp, "source": "live"}


def _normalize_game(g: dict, league_id: int, league_name: str) -> dict:
    scores = g.get("scores", {})
    home_s = scores.get("home", {})
    away_s = scores.get("away", {})
    q1h = home_s.get("quarter_1") or 0
    q1a = away_s.get("quarter_1") or 0
    q2h = home_s.get("quarter_2") or 0
    q2a = away_s.get("quarter_2") or 0
    q3h = home_s.get("quarter_3") or 0
    q3a = away_s.get("quarter_3") or 0
    q4h = home_s.get("quarter_4") or 0
    q4a = away_s.get("quarter_4") or 0
    total_h = home_s.get("total") or 0
    total_a = away_s.get("total") or 0
    status = g.get("status", {}).get("short", "")
    timer_val = g.get("status", {}).get("timer")
    timer = timer_val or 0
    # Minutes played for pace calculation
    _mins_map = {"Q1": timer, "Q2": 10.0 + timer, "HT": 20.0,
                 "Q3": 20.0 + timer, "Q4": 30.0 + timer, "FT": 40.0, "AOT": 45.0}
    mins_played = _mins_map.get(status, 0) or 0
    total_pts = total_h + total_a
    pace = round(total_pts / mins_played, 1) if mins_played > 0 else 0
    lead = abs(total_h - total_a)
    venue = g.get("venue") or {}
    return {
        "id": g.get("id"),
        "league_id": league_id,
        "league_name": g.get("league", {}).get("name", league_name),
        "status": status,
        "phase": status,
        "timer": timer_val,
        "home": g.get("teams", {}).get("home", {}).get("name", "Home"),
        "away": g.get("teams", {}).get("away", {}).get("name", "Away"),
        "q1_home": q1h, "q1_away": q1a,
        "q2_home": q2h, "q2_away": q2a,
        "q3_home": q3h, "q3_away": q3a,
        "q4_home": q4h, "q4_away": q4a,
        "total_home": total_h, "total_away": total_a,
        "q1_total": q1h + q1a,
        "q2_live": q2h + q2a,
        "q3_total": q3h + q3a,
        "q4_total": q4h + q4a,
        "ht_total": total_h + total_a,
        "lead": lead,
        "lead_home": total_h - total_a,
        "pace": pace,
        "venue_name": venue.get("name", ""),
        "venue_city": venue.get("city", ""),
        "fouls_home": 0,
        "fouls_away": 0,
        "fouls_total": 0,
        "ft_home": None,
        "ft_away": None,
        "h2h_avg": None,
        "bookie_line": None,
    }

def _demo_games():
    return [
        {"id": 1001, "league_id": 4, "league_name": "ACB", "status": "HT", "timer": None, "phase": "HT",
         "home": "Real Madrid", "away": "FC Barcelona",
         "q1_home": 28, "q1_away": 24, "q2_home": 22, "q2_away": 20,
         "q3_home": 0, "q3_away": 0, "q4_home": 0, "q4_away": 0,
         "total_home": 50, "total_away": 44, "q1_total": 52, "q2_live": 42,
         "q3_total": 0, "q4_total": 0, "ht_total": 94,
         "lead": 6, "lead_home": 6, "pace": 4.7,
         "venue_name": "WiZink Center", "venue_city": "Madrid",
         "fouls_home": 5, "fouls_away": 4, "fouls_total": 9,
         "ft_home": None, "ft_away": None, "h2h_avg": None, "bookie_line": None},
        {"id": 1002, "league_id": 120, "league_name": "TBL", "status": "Q2", "timer": 5, "phase": "Q2",
         "home": "Fenerbahce", "away": "Galatasaray",
         "q1_home": 31, "q1_away": 27, "q2_home": 18, "q2_away": 14,
         "q3_home": 0, "q3_away": 0, "q4_home": 0, "q4_away": 0,
         "total_home": 49, "total_away": 41, "q1_total": 58, "q2_live": 32,
         "q3_total": 0, "q4_total": 0, "ht_total": 90,
         "lead": 8, "lead_home": 8, "pace": 6.0,
         "venue_name": "Ulker Sports Arena", "venue_city": "Istanbul",
         "fouls_home": 4, "fouls_away": 5, "fouls_total": 9,
         "ft_home": None, "ft_away": None, "h2h_avg": None, "bookie_line": None},
        {"id": 1003, "league_id": 6, "league_name": "ABA Liga", "status": "Q3", "timer": 6, "phase": "Q3",
         "home": "Crvena zvezda", "away": "Partizan",
         "q1_home": 22, "q1_away": 26, "q2_home": 25, "q2_away": 21,
         "q3_home": 16, "q3_away": 14, "q4_home": 0, "q4_away": 0,
         "total_home": 63, "total_away": 61, "q1_total": 48, "q2_live": 46,
         "q3_total": 30, "q4_total": 0, "ht_total": 94,
         "lead": 2, "lead_home": 2, "pace": 4.8,
         "venue_name": "Stark Arena", "venue_city": "Beograd",
         "fouls_home": 14, "fouls_away": 13, "fouls_total": 27,
         "ft_home": 82.0, "ft_away": 78.0, "h2h_avg": None, "bookie_line": 155.5},
        {"id": 1004, "league_id": 3, "league_name": "EuroLeague", "status": "Q4", "timer": 4, "phase": "Q4",
         "home": "Anadolu Efes", "away": "CSKA Moscow",
         "q1_home": 24, "q1_away": 22, "q2_home": 19, "q2_away": 23,
         "q3_home": 21, "q3_away": 18, "q4_home": 12, "q4_away": 10,
         "total_home": 76, "total_away": 73, "q1_total": 46, "q2_live": 42,
         "q3_total": 39, "q4_total": 22, "ht_total": 88,
         "lead": 3, "lead_home": 3, "pace": 4.4,
         "venue_name": "Sinan Erdem Dome", "venue_city": "Istanbul",
         "fouls_home": 18, "fouls_away": 16, "fouls_total": 34,
         "ft_home": 85.0, "ft_away": 76.0, "h2h_avg": None, "bookie_line": 160.0},
    ]

def _demo_today():
    return [
        {"id": 2001, "league_id": 3, "league_name": "EuroLeague", "status": "FT", "timer": None, "phase": "FT",
         "home": "Olympiacos", "away": "CSKA", "q1_home": 24, "q1_away": 22,
         "q2_home": 18, "q2_away": 26, "q3_home": 20, "q3_away": 18,
         "q4_home": 16, "q4_away": 16, "total_home": 78, "total_away": 82,
         "q1_total": 46, "q2_live": 44, "q3_total": 38, "q4_total": 32, "ht_total": 90,
         "lead": 4, "lead_home": -4, "pace": 4.0,
         "venue_name": "Peace and Friendship Stadium", "venue_city": "Piraeus",
         "fouls_home": 22, "fouls_away": 19, "fouls_total": 41,
         "ft_home": 78.0, "ft_away": 81.0, "h2h_avg": None, "bookie_line": None},
        {"id": 2002, "league_id": 8, "league_name": "Lega A", "status": "NS", "timer": None, "phase": "NS",
         "home": "Olimpia Milano", "away": "Virtus Bologna",
         "q1_home": 0, "q1_away": 0, "q2_home": 0, "q2_away": 0,
         "q3_home": 0, "q3_away": 0, "q4_home": 0, "q4_away": 0,
         "total_home": 0, "total_away": 0, "q1_total": 0, "q2_live": 0,
         "q3_total": 0, "q4_total": 0, "ht_total": 0,
         "lead": 0, "lead_home": 0, "pace": 0,
         "venue_name": "Mediolanum Forum", "venue_city": "Milano",
         "fouls_home": 0, "fouls_away": 0, "fouls_total": 0,
         "ft_home": None, "ft_away": None, "h2h_avg": None, "bookie_line": None},
    ]
