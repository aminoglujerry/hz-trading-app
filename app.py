"""
HZ / FT Trading — Basketball Live Signal Engine
Optimised for Render Free Plan (512 MB RAM)
"""

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from collections import OrderedDict
from time import time
import asyncio
import httpx
import json
import logging
import os
import uvicorn
from typing import Optional
from datetime import date as _date, timedelta

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(funcName)s] %(message)s",
)
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

API_KEY    = os.getenv("API_SPORTS_KEY", "")
API_BASE   = "https://v1.basketball.api-sports.io"

SHEETS_ID  = os.getenv("GOOGLE_SHEETS_ID", "")
SHEETS_TAB = os.getenv("GOOGLE_SHEETS_TAB", "h2h_2025_2026")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

ODDS_API_KEY       = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE      = "https://api.the-odds-api.com/v4"

# ─── Signal Engine Constants ──────────────────────────────────────────────────

# HZ Engine
HZ_BUFFER_UNDER       = 5      # min proj-vs-line buffer for UNDER signal
HZ_BUFFER_OVER        = 3      # min proj-vs-line buffer (negative) for OVER signal
HZ_ENTRY_MIN          = 2.5    # min Q2 time remaining (min) for any entry
HZ_ENTRY_OPTIMAL      = 3.5    # Q2 time remaining for Stufe-A entry
HZ_FOULS_THRESHOLD    = 8      # fouls at or above → OVER catalyst / blocks UNDER
HZ_FT_PCT_CATALYST    = 85     # FT% at or above → OVER catalyst
HZ_FG_SKIP            = 60     # FG% above this → skip UNDER
HZ_H2H_OVER_BUFFER    = -3     # h2h_buf ≤ this → OVER H2H catalyst
HZ_H2H_UNDER_KONTRA   = 0      # h2h_buf < this → kontra (Stufe B on UNDER)
HZ_H2H_CONFIRM_BUFFER = 3      # h2h_buf ≥ this → strong confirmation on UNDER

# FT Engine
FT_BUFFER_UNDER_A     = 8      # min buffer for UNDER Stufe A (needs FT%)
FT_BUFFER_UNDER_B     = 10     # min buffer for UNDER Stufe B (no FT% required)
FT_BUFFER_OVER        = 8      # buffer ≤ −this → OVER signal
FT_FT_PCT_THRESHOLD   = 75     # min FT% (both teams) for A-signal
FT_GAP_MAX            = 20     # score gap above this → garbage-time skip
FT_FOULS_CATALYST     = 10     # fouls ≥ this → OVER catalyst
FT_H2H_CONFIRM_BUFFER = 5      # h2h_buf ≥ this → H2H confirmation on UNDER

# ─── App Constants ────────────────────────────────────────────────────────────

SEEN_FT_IDS_MAX       = 10_000  # FIFO cap for _seen_ft_ids (prevents unbounded growth)
SCHEDULER_INTERVAL    = 1800    # seconds between background extract runs
BACKFILL_SLEEP        = 0.5     # seconds between days in backfill loop
BACKFILL_MAX_DAYS     = 28      # max days per backfill request
GAME_STATS_CACHE_TTL  = 60      # seconds to cache /api/game-stats responses
API_TIMEOUT           = 12      # httpx request timeout (seconds)
TODAY_GAMES_LIMIT     = 40      # max games returned in today list
LIVE_API_CONCURRENCY  = 8       # max simultaneous API-Sports calls
SHEETS_ROWS_INIT      = 2000
SHEETS_COLS_INIT      = 10

H2H_HZ_MAX            = 400    # sanity cap for halftime total (any value above is corrupt)
H2H_FT_MAX            = 800    # sanity cap for full-game total

# ─── Auto-Scan (background signal loop) ──────────────────────────────────────
AUTO_SCAN_INTERVAL    = int(os.getenv("AUTO_SCAN_INTERVAL", "120"))  # seconds between scan cycles
H2H_MIN_SAMPLES       = 3      # minimum H2H entries required to auto-compute a signal
AUTO_SENT_TTL         = 1500   # seconds before re-sending a signal for the same game (25 min)
AUTO_SCAN_STUFE       = os.getenv("AUTO_SCAN_STUFE", "A")  # only send signals at this stufe or higher

SHEETS_HEADER = ["date", "home", "away", "league",
                 "q1_total", "q2_total", "ht_total", "ft_total"]

# ─── Leagues ──────────────────────────────────────────────────────────────────

LEAGUES: dict[int, tuple[str, str]] = {
    120: ("TBL",          "2025-2026"),
    4:   ("ACB",          "2025-2026"),
    6:   ("ABA Liga",     "2025-2026"),
    23:  ("LNB Pro A",    "2025-2026"),
    8:   ("Lega A",       "2025-2026"),
    3:   ("EuroLeague",   "2025-2026"),
    2:   ("EuroCup",      "2025-2026"),
    15:  ("BBL",          "2025-2026"),
    11:  ("GBL",          "2025-2026"),
    22:  ("BCL",          "2025-2026"),
    12:  ("NBA",          "2025"),
    5:   ("VTB",          "2025-2026"),
    16:  ("Jeep Elite",   "2025-2026"),
    19:  ("NBB",          "2025-2026"),
    38:  ("Sueper Lig",   "2025-2026"),
    117: ("LNB Pro B",    "2025-2026"),
    14:  ("BSL",          "2025-2026"),
    17:  ("Korisliiga",   "2025-2026"),
    18:  ("Korisliiga W", "2025-2026"),
    24:  ("Pro B",        "2025-2026"),
    7:   ("Adriatic",     "2025-2026"),
    9:   ("Lega A2",      "2025-2026"),
    10:  ("A1 GR",        "2025-2026"),
    13:  ("CBA",          "2025-2026"),
    20:  ("Orlen BP",     "2025-2026"),
    25:  ("NLA",          "2025-2026"),
    29:  ("NBL",          "2025-2026"),
    30:  ("Superliga",    "2025-2026"),
    31:  ("Divizia A",    "2025-2026"),
    32:  ("PBL",          "2025-2026"),
    33:  ("LKL",          "2025-2026"),
    34:  ("Premijer",     "2025-2026"),
    36:  ("SBL",          "2025-2026"),
    37:  ("Extraliga",    "2025-2026"),
    40:  ("Superleague",  "2025-2026"),
}

# ─── In-Memory State ──────────────────────────────────────────────────────────

_h2h_cache:        dict        = {}           # matchup_key → [ht_total, …]
_ft_h2h_cache:     dict        = {}           # matchup_key → [ft_total, …]
_seen_ft_ids:      OrderedDict = OrderedDict() # FIFO set, capped at SEEN_FT_IDS_MAX
_game_stats_cache: OrderedDict = OrderedDict() # game_id → (timestamp, result), FIFO-capped
_auto_sent:        dict        = {}           # (game_id, type) → timestamp; dedup for auto-signals
_ws                             = None         # gspread Worksheet (lazy init)
_api_semaphore: Optional[asyncio.Semaphore]   = None  # init in lifespan
_http_client:   Optional[httpx.AsyncClient]   = None  # persistent — reused across all API calls

GAME_STATS_CACHE_MAX = 200   # max entries before oldest is evicted


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app_: FastAPI):
    global _api_semaphore, _http_client
    _api_semaphore = asyncio.Semaphore(LIVE_API_CONCURRENCY)
    _http_client   = httpx.AsyncClient(
        timeout=API_TIMEOUT,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    scheduler_task  = asyncio.create_task(_scheduler_loop())
    auto_scan_task  = asyncio.create_task(_auto_scan_loop())
    log.info("🚀 App started — scheduler interval: %ds, auto-scan interval: %ds, concurrency: %d",
             SCHEDULER_INTERVAL, AUTO_SCAN_INTERVAL, LIVE_API_CONCURRENCY)
    yield
    scheduler_task.cancel()
    auto_scan_task.cancel()
    for t in (scheduler_task, auto_scan_task):
        try:
            await t
        except asyncio.CancelledError:
            pass
    await _http_client.aclose()
    log.info("App shutdown complete")


app = FastAPI(title="HZ / FT Trading", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── HTML ─────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HZ / FT Trading</title>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;900&family=Barlow:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#07080b;--s1:#0d0e13;--s2:#111218;--s3:#13141a;
  --border:#1a1b24;--border2:#252630;
  --text:#c9cdd8;--dim:#3e4055;--dim2:#555770;
  --under:#00b4d8;--over:#e63946;--green:#2dc653;--gold:#f4a261;--white:#f0f1f5;
  --panel-w:340px;--topbar-h:48px;--statusbar-h:26px;
}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;overflow:hidden;}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;}

/* ── Topbar ── */
.topbar{
  position:fixed;top:0;left:0;right:0;z-index:300;
  height:var(--topbar-h);background:var(--s1);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 16px;gap:12px;
}
.logo{font-family:'Barlow Condensed',sans-serif;font-weight:900;font-size:20px;
  letter-spacing:5px;color:var(--white);flex-shrink:0;}
.logo em{color:var(--green);font-style:normal;}
.topbar-divider{width:1px;height:20px;background:var(--border2);flex-shrink:0;}
.live-count{font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700;
  letter-spacing:2px;color:var(--dim2);flex-shrink:0;}
.live-count span{color:var(--white);}
.topbar-spacer{flex:1;}
.live-pill{display:flex;align-items:center;gap:6px;font-size:10px;
  color:var(--dim2);letter-spacing:1.5px;flex-shrink:0;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--dim);}
.dot.live{background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 1.5s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.icon-btn{background:none;border:1px solid var(--border2);color:var(--dim2);
  padding:5px 14px;font-size:11px;letter-spacing:1.5px;cursor:pointer;
  font-family:'Barlow',sans-serif;text-transform:uppercase;transition:all .15s;flex-shrink:0;}
.icon-btn:hover,.icon-btn:disabled{border-color:var(--green);color:var(--green);}
.icon-btn:disabled{opacity:.5;cursor:default;}

/* ── Status bar ── */
.statusbar{
  position:fixed;top:var(--topbar-h);left:0;right:0;z-index:299;
  height:var(--statusbar-h);background:var(--s3);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 16px;gap:16px;
  font-size:9px;letter-spacing:1px;text-transform:uppercase;
}
.sb-item{display:flex;align-items:center;gap:5px;color:var(--dim2);}
.sb-dot{width:5px;height:5px;border-radius:50%;background:var(--dim);}
.sb-dot.ok{background:var(--green);}
.sb-dot.warn{background:var(--gold);}
.sb-dot.err{background:var(--over);}
.sb-val{color:var(--text);}
.sb-sep{width:1px;height:12px;background:var(--border2);}
#sbNextRefresh{color:var(--dim);}

/* ── App shell ── */
.app-shell{
  display:grid;
  grid-template-columns:1fr var(--panel-w);
  height:100vh;
  padding-top:calc(var(--topbar-h) + var(--statusbar-h));
}

/* ── Games column (left) ── */
.games-col{
  overflow-y:auto;padding:14px 14px 24px;
  scrollbar-width:thin;scrollbar-color:var(--border2) transparent;
}
.games-col::-webkit-scrollbar{width:4px;}
.games-col::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px;}

.sec{font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--dim);
  margin:16px 0 8px;display:flex;align-items:center;gap:8px;}
.sec:first-child{margin-top:4px;}
.sec::after{content:'';flex:1;height:1px;background:var(--border);}
.sec-badge{background:var(--s2);border:1px solid var(--border2);color:var(--dim2);
  font-size:9px;padding:1px 6px;letter-spacing:1px;}

.games-wrap{display:flex;flex-direction:column;gap:2px;}
.empty{text-align:center;padding:28px 14px;color:var(--dim);
  border:1px dashed var(--border);font-size:11px;line-height:2.2;}

/* ── Game cards ── */
.game-card,.ft-card{
  background:var(--s2);border:1px solid var(--border);cursor:pointer;
  display:grid;grid-template-columns:3px 1fr;transition:border-color .12s,box-shadow .12s;
}
.game-card:hover,.ft-card:hover{border-color:var(--border2);}
.game-card.selected,.ft-card.selected{border-color:var(--dim2);}
.sig-under{border-color:rgba(0,180,216,.45)!important;}
.sig-over {border-color:rgba(230,57,70,.45)!important;}
.sig-a    {box-shadow:0 0 14px rgba(45,198,83,.12);}

.card-stripe{width:3px;transition:background .2s;}
.sig-under .card-stripe{background:var(--under);}
.sig-over  .card-stripe{background:var(--over);}
.sig-a     .card-stripe{background:var(--green);}
.card-body,.ft-body{padding:9px 11px;}

.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}
.card-league{font-size:9px;letter-spacing:1.5px;color:var(--dim2);text-transform:uppercase;}
.card-status{font-size:9px;color:var(--gold);font-family:'Barlow Condensed',sans-serif;font-weight:700;letter-spacing:1px;}

.card-teams{display:grid;grid-template-columns:1fr auto 1fr;gap:4px;align-items:center;margin-bottom:7px;}
.card-team{font-family:'Barlow Condensed',sans-serif;font-size:14px;font-weight:700;color:var(--white);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.card-team.away{text-align:right;}
.score-block{text-align:center;}
.score-num{font-family:'Barlow Condensed',sans-serif;font-size:22px;font-weight:900;color:var(--white);line-height:1;}
.score-q1{font-size:9px;color:var(--dim2);margin-top:1px;}

.card-stats-row{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;margin-bottom:6px;}
.cs{background:var(--bg);padding:4px;text-align:center;}
.cs-val{font-family:'Barlow Condensed',sans-serif;font-size:14px;font-weight:700;color:var(--text);}
.cs-lbl{font-size:7px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);margin-top:1px;}

.card-bot{display:flex;justify-content:space-between;align-items:center;
  padding-top:6px;border-top:1px solid var(--border);}
.h2h-note{font-size:9px;color:var(--dim2);letter-spacing:.5px;}
.h2h-note.found{color:var(--green);}
.card-sig-badge{font-size:9px;font-weight:700;letter-spacing:1.5px;padding:2px 7px;border:1px solid;}
.card-sig-badge.under{color:var(--under);border-color:rgba(0,180,216,.3);}
.card-sig-badge.over {color:var(--over); border-color:rgba(230,57,70,.3);}
.card-sig-badge.skip,.card-sig-badge.none{color:var(--dim);border-color:var(--border);}
.card-stufe-badge{font-size:9px;font-weight:700;padding:2px 7px;font-family:'Barlow Condensed',sans-serif;}
.card-stufe-badge.a{background:var(--green);color:var(--bg);}
.card-stufe-badge.b{background:var(--gold);color:var(--bg);}
.card-stufe-badge.c{color:var(--dim);}

/* card input drawer */
.card-inputs,.ft-card-inputs{
  display:none;padding:9px 11px;border-top:1px solid var(--border);background:var(--s3);
}
.card-inputs.open,.ft-card-inputs.open{
  display:grid;grid-template-columns:repeat(3,1fr);gap:5px;
}
.inp-group{display:flex;flex-direction:column;gap:3px;}
.inp-group label{font-size:8px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.inp-group input{
  background:var(--bg);border:1px solid var(--border2);color:var(--white);
  font-family:'Barlow Condensed',sans-serif;font-size:16px;font-weight:600;
  padding:5px 7px;outline:none;width:100%;
}
.inp-group input:focus{border-color:var(--under);}
.calc-mini{
  grid-column:1/-1;background:var(--white);border:none;
  font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:900;
  letter-spacing:3px;padding:8px;cursor:pointer;text-transform:uppercase;color:var(--bg);
}
.calc-mini:hover{background:#dde1f0;}

/* ── Right panel ── */
.right-panel{
  border-left:1px solid var(--border);
  display:flex;flex-direction:column;
  height:100%;overflow:hidden;
}

/* Signal card — always visible at top of right panel */
.signal-card{
  flex-shrink:0;
  padding:14px 16px 12px;
  border-bottom:2px solid var(--border);
  background:var(--s1);
  transition:border-bottom-color .25s,background .25s;
}
.signal-card.under{border-bottom-color:rgba(0,180,216,.6);background:#09131a;}
.signal-card.over {border-bottom-color:rgba(230,57,70,.6);background:#140d0e;}
.signal-card.glow {box-shadow:inset 0 -1px 0 rgba(45,198,83,.15);}

.sig-header{display:flex;align-items:center;gap:8px;margin-bottom:10px;}
.sig-tag{font-size:9px;letter-spacing:2px;color:var(--dim2);text-transform:uppercase;
  padding:2px 8px;background:var(--s2);border:1px solid var(--border2);}
.sig-stufe{font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:700;
  letter-spacing:3px;padding:2px 10px;border:1px solid;}
.st-a{color:var(--green);border-color:rgba(45,198,83,.4);}
.st-b{color:var(--gold); border-color:rgba(244,162,97,.4);}
.st-c{color:var(--dim);  border-color:var(--border);}

.sig-dir{
  font-family:'Barlow Condensed',sans-serif;font-weight:900;
  font-size:48px;letter-spacing:4px;line-height:1;
  color:var(--dim);margin-bottom:10px;
}
.sig-dir.under{color:var(--under);}
.sig-dir.over {color:var(--over);}

.sig-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;margin-bottom:10px;}
.ss{background:var(--s2);border:1px solid var(--border);padding:7px 4px;text-align:center;}
.ss-v{font-family:'Barlow Condensed',sans-serif;font-size:17px;font-weight:700;color:var(--white);}
.ss-v.pos{color:var(--under);}
.ss-v.neg{color:var(--over);}
.ss-v.gold{color:var(--gold);}
.ss-l{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);margin-top:1px;}

.sig-reasons{font-size:10px;line-height:1.9;color:var(--dim2);}
.r-ok{color:var(--green);}
.r-warn{color:var(--gold);}
.r-bad{color:var(--over);}

/* Manual section */
.manual-section{flex-shrink:0;border-bottom:1px solid var(--border);}
.manual-toggle{
  display:flex;align-items:center;justify-content:space-between;
  width:100%;padding:10px 16px;background:none;border:none;
  color:var(--dim2);font-size:10px;letter-spacing:2px;text-transform:uppercase;
  cursor:pointer;font-family:'Barlow',sans-serif;transition:color .15s;
  border-bottom:1px solid var(--border);
}
.manual-toggle:last-of-type{border-bottom:none;}
.manual-toggle:hover{color:var(--text);}
.manual-toggle .arrow{font-size:9px;transition:transform .15s;}
.manual-toggle.open .arrow{transform:rotate(90deg);}
.manual-form{display:none;padding:10px 16px 12px;background:var(--s3);}
.manual-form.open{display:block;}
.mf-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:7px;}
.mf-inp{display:flex;flex-direction:column;gap:3px;}
.mf-inp label{font-size:8px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.mf-inp input{
  background:var(--bg);border:1px solid var(--border2);color:var(--white);
  font-family:'Barlow Condensed',sans-serif;font-size:17px;font-weight:700;
  padding:5px 7px;outline:none;
}
.mf-inp input:focus{border-color:var(--green);}
.checks-row{display:flex;gap:12px;margin-bottom:7px;flex-wrap:wrap;}
.chk{display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none;}
.chk-box{width:13px;height:13px;border:1px solid var(--border2);background:var(--bg);
  display:flex;align-items:center;justify-content:center;font-size:8px;}
.chk.on .chk-box{background:var(--over);border-color:var(--over);color:#fff;}
.chk-lbl{font-size:10px;color:var(--dim2);}
.chk.on .chk-lbl{color:var(--text);}
.btn-calc{
  width:100%;background:var(--white);border:none;color:var(--bg);
  font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:900;
  letter-spacing:4px;padding:10px;cursor:pointer;text-transform:uppercase;
}
.btn-calc:hover{background:#dde1f0;}

/* Today section — scrolls independently */
.today-section{
  flex:1;min-height:0;overflow-y:auto;
  scrollbar-width:thin;scrollbar-color:var(--border2) transparent;
}
.today-section::-webkit-scrollbar{width:4px;}
.today-section::-webkit-scrollbar-thumb{background:var(--border2);}
.today-inner{padding:0 14px 24px;}

.today-card{
  background:var(--s2);border:1px solid var(--border);
  display:grid;grid-template-columns:3px 1fr;margin-top:2px;
}
.today-body{padding:7px 10px;}
.today-top{display:flex;justify-content:space-between;margin-bottom:3px;}
.today-league{font-size:9px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;}
.today-status{font-size:9px;}
.today-teams{display:grid;grid-template-columns:1fr auto 1fr;gap:4px;align-items:center;}
.today-team{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;
  color:var(--white);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.today-team.away{text-align:right;}
.today-score{text-align:center;font-family:'Barlow Condensed',sans-serif;
  font-size:17px;font-weight:900;color:var(--white);}
.today-q{font-size:8px;color:var(--dim2);margin-top:1px;text-align:center;}

/* ── Preview (NS) cards ── */
.preview-card{
  background:var(--s2);border:1px solid var(--border);
  display:grid;grid-template-columns:3px 1fr;
}
.preview-card.no-h2h{opacity:.5;}
.preview-card.wl-active{border-color:rgba(244,162,97,.35);}
.pre-card-body{padding:9px 11px;}
.pre-card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}
.pre-card-teams{display:grid;grid-template-columns:1fr auto 1fr;gap:4px;align-items:center;margin-bottom:7px;}
.pre-line-row{display:flex;align-items:center;gap:8px;margin-bottom:6px;}
.pre-line-row label{font-size:8px;letter-spacing:1px;color:var(--dim2);text-transform:uppercase;white-space:nowrap;}
.pre-line-row input{
  background:var(--bg);border:1px solid var(--border2);color:var(--white);
  font-family:'Barlow Condensed',sans-serif;font-size:15px;font-weight:600;
  padding:4px 7px;outline:none;width:90px;
}
.pre-line-row input:focus{border-color:var(--gold);}
.pre-card-bot{display:flex;justify-content:space-between;align-items:center;
  padding-top:6px;border-top:1px solid var(--border);}
.pre-sig-badge{font-size:9px;font-weight:700;letter-spacing:1px;padding:2px 7px;border:1px solid;}
.pre-sig-badge.under{color:var(--under);border-color:rgba(0,180,216,.3);}
.pre-sig-badge.over{color:var(--over);border-color:rgba(230,57,70,.3);}
.pre-sig-badge.neutral{color:var(--dim2);border-color:var(--border);}
.watch-btn{
  background:none;border:none;cursor:pointer;font-size:14px;
  color:var(--dim);padding:1px 4px;line-height:1;transition:color .15s;}
.watch-btn:hover{color:var(--gold);}
.watch-btn.active{color:var(--gold);}
.wl-star{font-size:11px;color:var(--gold);margin-left:5px;display:none;vertical-align:middle;}
.wl-star.vis{display:inline;}
.h2h-missing{color:var(--over);}

/* ── Signal Log ── */
.sig-log-section{
  border-top:1px solid var(--border);
  display:flex;flex-direction:column;
  max-height:190px;flex-shrink:0;
}
.sig-log-header{
  display:flex;justify-content:space-between;align-items:center;
  padding:5px 14px;font-size:9px;letter-spacing:1px;text-transform:uppercase;
  color:var(--dim2);border-bottom:1px solid var(--border);flex-shrink:0;
}
.log-clear-btn{
  background:none;border:none;cursor:pointer;
  color:var(--dim);font-size:9px;letter-spacing:1px;
  text-transform:uppercase;padding:1px 4px;
}
.log-clear-btn:hover{color:var(--over);}
.sig-log-inner{
  overflow-y:auto;flex:1;
  scrollbar-width:thin;scrollbar-color:var(--border2) transparent;
}
.sig-log-inner::-webkit-scrollbar{width:3px;}
.sig-log-inner::-webkit-scrollbar-thumb{background:var(--border2);}
.sig-log-entry{
  display:flex;align-items:center;gap:6px;
  padding:4px 14px;border-bottom:1px solid var(--border);
  font-size:9px;
}
.sig-log-entry:last-child{border-bottom:none;}
.sig-log-time{color:var(--dim);min-width:40px;flex-shrink:0;font-size:8px;}
.sig-log-dir{
  font-family:'Barlow Condensed',sans-serif;font-weight:700;
  font-size:11px;letter-spacing:1px;flex-shrink:0;
}
.sig-log-dir.under{color:var(--under);}
.sig-log-dir.over{color:var(--over);}
.sig-log-dir.skip{color:var(--dim);}
.sig-log-stufe{font-size:8px;padding:1px 4px;border:1px solid;flex-shrink:0;}
.sig-log-stufe.a{color:var(--green);border-color:rgba(45,198,83,.3);}
.sig-log-stufe.b{color:var(--gold);border-color:rgba(244,162,97,.3);}
.sig-log-stufe.c{color:var(--dim);border-color:var(--border);}
.sig-log-type{color:var(--dim2);font-size:8px;flex-shrink:0;}
.sig-log-buf{color:var(--text);flex-shrink:0;}
.sig-log-ctx{color:var(--dim);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:8px;}
.icon-btn.active{border-color:var(--green);color:var(--green);}

/* Mobile */
@media(max-width:800px){
  html,body{overflow:auto;}
  .app-shell{grid-template-columns:1fr;height:auto;}
  .right-panel{height:auto;border-left:none;border-top:1px solid var(--border);}
  .today-section{max-height:60vh;}
  .signal-card{position:sticky;top:calc(var(--topbar-h)+var(--statusbar-h));z-index:100;}
  .sig-dir{font-size:36px;}
  .sig-log-section{max-height:140px;}
}

/* ── Stats Modal ── */
.stats-overlay{
  display:none;position:fixed;inset:0;z-index:500;
  background:rgba(0,0,0,.75);backdrop-filter:blur(3px);
  align-items:flex-start;justify-content:center;
  padding-top:calc(var(--topbar-h) + var(--statusbar-h) + 16px);
}
.stats-overlay.open{display:flex;}
.stats-modal{
  background:var(--s1);border:1px solid var(--border2);
  width:min(700px,96vw);
  max-height:calc(100vh - var(--topbar-h) - var(--statusbar-h) - 32px);
  display:flex;flex-direction:column;overflow:hidden;
}
.stats-modal-header{
  display:flex;justify-content:space-between;align-items:center;
  padding:12px 16px;border-bottom:1px solid var(--border);flex-shrink:0;
}
.stats-modal-title{
  font-family:'Barlow Condensed',sans-serif;font-weight:900;
  font-size:16px;letter-spacing:3px;color:var(--white);
}
.stats-close{
  background:none;border:none;cursor:pointer;
  color:var(--dim);font-size:18px;padding:2px 8px;line-height:1;
}
.stats-close:hover{color:var(--over);}
.stats-body{
  overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:12px;
  scrollbar-width:thin;scrollbar-color:var(--border2) transparent;
}
.stats-body::-webkit-scrollbar{width:4px;}
.stats-body::-webkit-scrollbar-thumb{background:var(--border2);}
.stats-section{background:var(--s2);border:1px solid var(--border);padding:12px;}
.stats-section-title{
  font-size:9px;letter-spacing:3px;text-transform:uppercase;
  color:var(--dim);margin-bottom:10px;
}
.stats-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:4px;
}
.stat-box{background:var(--bg);border:1px solid var(--border);padding:8px;text-align:center;}
.stat-box-val{
  font-family:'Barlow Condensed',sans-serif;
  font-size:22px;font-weight:700;color:var(--white);
}
.stat-box-val.green{color:var(--green);}
.stat-box-val.red{color:var(--over);}
.stat-box-val.gold{color:var(--gold);}
.stat-box-val.blue{color:var(--under);}
.stat-box-lbl{
  font-size:7px;letter-spacing:1px;text-transform:uppercase;
  color:var(--dim);margin-top:3px;
}
.tracked-list{
  display:flex;flex-direction:column;gap:2px;
  max-height:220px;overflow-y:auto;
  scrollbar-width:thin;scrollbar-color:var(--border2) transparent;
}
.tracked-entry{
  display:flex;align-items:center;gap:5px;
  padding:5px 7px;background:var(--bg);border:1px solid var(--border);font-size:9px;
}
.tracked-dir{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:11px;letter-spacing:1px;flex-shrink:0;}
.tracked-dir.under{color:var(--under);}
.tracked-dir.over{color:var(--over);}
.tracked-dir.skip{color:var(--dim);}
.tracked-result-btns{margin-left:auto;display:flex;gap:3px;flex-shrink:0;}
.result-btn{
  background:none;border:1px solid var(--border2);color:var(--dim);
  font-size:8px;letter-spacing:.5px;padding:2px 6px;cursor:pointer;
  font-family:'Barlow',sans-serif;text-transform:uppercase;
}
.result-btn:hover{border-color:var(--green);color:var(--green);}
.result-btn.won{background:rgba(45,198,83,.15);border-color:var(--green);color:var(--green);}
.result-btn.lost{background:rgba(230,57,70,.15);border-color:var(--over);color:var(--over);}
.result-btn.void{background:rgba(61,64,85,.3);border-color:var(--dim2);color:var(--dim2);}
.stats-action-row{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;}
.stats-action-btn{
  background:none;border:1px solid var(--border2);color:var(--dim);
  font-size:9px;letter-spacing:1px;padding:4px 12px;cursor:pointer;
  font-family:'Barlow',sans-serif;text-transform:uppercase;
}
.stats-action-btn:hover{border-color:var(--over);color:var(--over);}
.backfill-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px;}
.bf-select,.bf-input{
  background:var(--bg);border:1px solid var(--border2);color:var(--text);
  font-family:'Barlow',sans-serif;font-size:10px;padding:4px 6px;
  min-width:0;
}
.bf-select{flex:1 1 80px;max-width:110px;}
.bf-input{flex:1 1 60px;max-width:80px;}
.backfill-progress{
  font-size:10px;color:var(--gold);letter-spacing:.5px;
  margin-top:6px;min-height:16px;
}
</style>
</head>
<body>

<!-- Topbar -->
<div class="topbar">
  <div class="logo">HZ / <em>FT</em></div>
  <div class="topbar-divider"></div>
  <div class="live-count"><span id="liveCountNum">0</span> LIVE</div>
  <div class="topbar-spacer"></div>
  <div class="live-pill">
    <div class="dot" id="liveDot"></div>
    <span id="liveLabel">OFFLINE</span>
  </div>
  <button class="icon-btn" id="refreshBtn" onclick="loadLive()">⟳ LIVE</button>
  <button class="icon-btn" id="tgTestBtn" onclick="testTelegram()" title="Telegram Test-Nachricht senden">📱 TG</button>
  <button class="icon-btn" id="statsBtn" onclick="toggleStats()" title="Statistiken & P&L Tracking">📊 STATS</button>
  <button class="icon-btn" id="notifBtn" onclick="toggleNotif()" title="Browser-Benachrichtigungen ein/aus">🔕 AUS</button>
  <button class="icon-btn" id="soundBtn" onclick="toggleSound()" title="Sound-Alert ein/aus">🔇 AUS</button>
</div>

<!-- Status bar -->
<div class="statusbar">
  <div class="sb-item"><div class="sb-dot" id="sbApiDot"></div><span>API</span> <span class="sb-val" id="sbApiVal">—</span></div>
  <div class="sb-sep"></div>
  <div class="sb-item"><div class="sb-dot" id="sbH2hDot"></div><span>H2H</span> <span class="sb-val" id="sbH2hVal">—</span></div>
  <div class="sb-sep"></div>
  <div class="sb-item"><div class="sb-dot" id="sbSheetsDot"></div><span>Sheets</span></div>
  <div class="sb-sep"></div>
  <div class="sb-item"><div class="sb-dot" id="sbTgDot"></div><span>Telegram</span></div>
  <div class="sb-sep"></div>
  <span id="sbNextRefresh"></span>
</div>

<!-- App Shell: Games (left) + Signal Panel (right) -->
<div class="app-shell">

  <!-- Left: scrollable games -->
  <div class="games-col">
    <div class="sec">HZ · Halbzeit / Q2 <span class="sec-badge" id="hzCount">0</span></div>
    <div class="games-wrap" id="gamesWrap">
      <div class="empty">⟳ Klicke LIVE um Halbzeit-Spiele zu laden</div>
    </div>

    <div class="sec">FT · Q3 Break <span class="sec-badge" id="ftCount">0</span></div>
    <div class="games-wrap" id="ftGamesWrap">
      <div class="empty">⟳ Klicke LIVE — zeigt Spiele am Q3 Break</div>
    </div>

    <div class="sec">LIVE · Im Gang <span class="sec-badge" id="liveOtherCount">0</span></div>
    <div class="games-wrap" id="liveOtherWrap">
      <div class="empty">⟳ Klicke LIVE um laufende Spiele zu laden</div>
    </div>

    <div class="sec">Heute · Vorschau <span class="sec-badge" id="previewCount">0</span></div>
    <div class="games-wrap" id="previewWrap">
      <div class="empty">⟳ Klicke LIVE um Vorschau zu laden</div>
    </div>
  </div>

  <!-- Right: sticky signal panel -->
  <div class="right-panel">

    <!-- Signal card — always visible -->
    <div class="signal-card" id="signalStrip">
      <div class="sig-header">
        <span class="sig-tag" id="sigTag">HZ</span>
        <span class="sig-stufe st-c" id="sigStufe">— —</span>
      </div>
      <div class="sig-dir" id="sigDir">—</div>
      <div class="sig-stats">
        <div class="ss"><div class="ss-v" id="ssProj">—</div><div class="ss-l">Proj</div></div>
        <div class="ss"><div class="ss-v" id="ssBuf">—</div><div class="ss-l">Buffer</div></div>
        <div class="ss"><div class="ss-v" id="ssTime">—</div><div class="ss-l">Zeit</div></div>
        <div class="ss"><div class="ss-v" id="ssFouls">—</div><div class="ss-l">Fouls</div></div>
      </div>
      <div class="sig-reasons" id="sigReasons">Spiel wählen oder manuell eingeben</div>
    </div>

    <!-- Manual input — collapsible -->
    <div class="manual-section">
      <button class="manual-toggle" id="mToggleHz" onclick="toggleManual('hz')">
        + Manuell HZ <span class="arrow">›</span>
      </button>
      <div class="manual-form" id="manualHz">
        <div class="mf-grid">
          <div class="mf-inp"><label>H2H Ø HZ</label><input type="number" id="hH2H" placeholder="96.5" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Bookie Line</label><input type="number" id="hLine" placeholder="91.5" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Q1 Total</label><input type="number" id="hQ1" placeholder="52" inputmode="numeric"></div>
          <div class="mf-inp"><label>Q2 aktuell</label><input type="number" id="hQ2" placeholder="28" inputmode="numeric"></div>
          <div class="mf-inp"><label>Q2 Zeit (Min)</label><input type="number" id="hTimer" placeholder="4" min="0" max="10" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Fouls gesamt</label><input type="number" id="hFouls" placeholder="5" inputmode="numeric"></div>
          <div class="mf-inp"><label>FT% Ø</label><input type="number" id="hFT" placeholder="—" inputmode="numeric"></div>
          <div class="mf-inp"><label>FG%</label><input type="number" id="hFG" placeholder="—" inputmode="numeric"></div>
        </div>
        <div class="checks-row">
          <div class="chk" id="chkDrop" onclick="this.classList.toggle('on')"><div class="chk-box">✓</div><span class="chk-lbl">Linie fällt ≥8</span></div>
          <div class="chk" id="chkRise" onclick="this.classList.toggle('on')"><div class="chk-box">✓</div><span class="chk-lbl">Linie steigt</span></div>
        </div>
        <button class="btn-calc" onclick="calcManualHz()">▶ HZ SIGNAL</button>
      </div>

      <button class="manual-toggle" id="mToggleFt" onclick="toggleManual('ft')">
        + Manuell FT <span class="arrow">›</span>
      </button>
      <div class="manual-form" id="manualFt">
        <div class="mf-grid">
          <div class="mf-inp"><label>H2H Ø FT</label><input type="number" id="fH2H" placeholder="188" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>FT Bookie Line</label><input type="number" id="fLine" placeholder="182.5" step="0.5" inputmode="decimal"></div>
          <div class="mf-inp"><label>Q3 Score Heim</label><input type="number" id="fQ3H" placeholder="25" inputmode="numeric"></div>
          <div class="mf-inp"><label>Q3 Score Gast</label><input type="number" id="fQ3A" placeholder="22" inputmode="numeric"></div>
          <div class="mf-inp"><label>HZ Total</label><input type="number" id="fHZ" placeholder="90" inputmode="numeric"></div>
          <div class="mf-inp"><label>Fouls gesamt</label><input type="number" id="fFouls" placeholder="10" inputmode="numeric"></div>
          <div class="mf-inp"><label>FT% Heim</label><input type="number" id="fFTH" placeholder="78" inputmode="numeric"></div>
          <div class="mf-inp"><label>FT% Gast</label><input type="number" id="fFTA" placeholder="75" inputmode="numeric"></div>
        </div>
        <button class="btn-calc" onclick="calcManualFt()">▶ FT SIGNAL</button>
      </div>
    </div>

    <!-- Today's games — scrollable, fills remaining height -->
    <div class="today-section">
      <div class="sec" style="margin:12px 14px 0;padding:0;">Heute · Alle Spiele</div>
      <div class="today-inner" id="todayWrap">
        <div class="empty" style="font-size:10px;margin-top:6px">Klicke LIVE</div>
      </div>
    </div>

    <!-- Hidden — kept for JS compatibility -->
    <div style="display:none" id="ftTodayWrap"></div>

    <!-- Signal Log — session history of calculated signals -->
    <div class="sig-log-section">
      <div class="sig-log-header">
        <span>Signal Log <span class="sec-badge" id="logCount">0</span></span>
        <button class="log-clear-btn" onclick="clearLog()">✕ leeren</button>
      </div>
      <div class="sig-log-inner" id="sigLogWrap">
        <div class="empty" style="font-size:10px;padding:8px 14px;">Noch kein Signal berechnet</div>
      </div>
    </div>

  </div><!-- /right-panel -->
</div><!-- /app-shell -->

<!-- Stats Modal -->
<div class="stats-overlay" id="statsOverlay" onclick="if(event.target===this)toggleStats()">
  <div class="stats-modal">
    <div class="stats-modal-header">
      <span class="stats-modal-title">📊 STATISTIKEN</span>
      <button class="stats-close" onclick="toggleStats()">✕</button>
    </div>
    <div class="stats-body" id="statsBody">
      <div class="empty" style="font-size:11px;padding:28px;">Lade Statistiken…</div>
    </div>
  </div>
</div>

<script>
// ── Signal Engine Constants (mirrors Python constants) ──
const HZ_BUFFER_UNDER       = 5;
const HZ_BUFFER_OVER        = 3;
const HZ_ENTRY_MIN          = 2.5;
const HZ_ENTRY_OPTIMAL      = 3.5;
const HZ_FOULS_THRESHOLD    = 8;
const HZ_FT_PCT_CATALYST    = 85;
const HZ_FG_SKIP            = 60;
const HZ_H2H_OVER_BUFFER    = -3;
const HZ_H2H_UNDER_KONTRA   = 0;
const HZ_H2H_CONFIRM_BUFFER = 3;
const FT_BUFFER_UNDER_A     = 8;
const FT_BUFFER_UNDER_B     = 10;
const FT_BUFFER_OVER        = 8;
const FT_FT_PCT_THRESHOLD   = 75;
const FT_GAP_MAX            = 20;
const FT_FOULS_CATALYST     = 10;
const FT_H2H_CONFIRM_BUFFER = 5;

// switchTab is kept for backwards-compat but does nothing in new layout
function switchTab(){}

function toggleManual(t){
  const form=document.getElementById(t==='hz'?'manualHz':'manualFt');
  const btn=document.getElementById(t==='hz'?'mToggleHz':'mToggleFt');
  form.classList.toggle('open');
  btn.classList.toggle('open');
}

// ── Status bar ──
async function loadHealth(){
  try{
    const h=await fetch('/api/health').then(r=>r.json());
    const apiOk=h.api_key_set;
    document.getElementById('sbApiDot').className='sb-dot '+(apiOk?'ok':'err');
    document.getElementById('sbApiVal').textContent=apiOk?'OK':'KEY FEHLT';
    const hzN=h.hz_matchups||0,ftN=h.ft_matchups||0;
    const h2hOk=hzN>0;
    document.getElementById('sbH2hDot').className='sb-dot '+(h2hOk?'ok':'warn');
    document.getElementById('sbH2hVal').textContent=h2hOk?`${hzN} HZ / ${ftN} FT`:'0 — Backfill nötig';
    document.getElementById('sbSheetsDot').className='sb-dot '+(h.sheets_configured?'ok':'warn');
    const tgDot=document.getElementById('sbTgDot');
    if(tgDot)tgDot.className='sb-dot '+(h.telegram_configured?'ok':'warn');
    const tgBtn=document.getElementById('tgTestBtn');
    if(tgBtn)tgBtn.title=h.telegram_configured?'Telegram Test senden':'Telegram nicht konfiguriert';
  }catch(e){
    document.getElementById('sbApiDot').className='sb-dot err';
    document.getElementById('sbApiVal').textContent='Server schläft…';
  }
}

let _autoRefreshTimer=null;
let _countdownTimer=null;
let _nextRefreshAt=null;
const AUTO_REFRESH_MS=60_000;

function _startCountdown(){
  if(_countdownTimer)clearInterval(_countdownTimer);
  _nextRefreshAt=Date.now()+AUTO_REFRESH_MS;
  _countdownTimer=setInterval(()=>{
    const sec=Math.max(0,Math.round((_nextRefreshAt-Date.now())/1000));
    document.getElementById('sbNextRefresh').textContent=sec>0?`⟳ in ${sec}s`:'';
    if(sec===0)clearInterval(_countdownTimer);
  },1000);
}
function _stopCountdown(){
  if(_countdownTimer){clearInterval(_countdownTimer);_countdownTimer=null;}
  document.getElementById('sbNextRefresh').textContent='';
}

function setLive(on,count){
  document.getElementById('liveDot').className='dot'+(on?' live':'');
  document.getElementById('liveLabel').textContent=on?'LIVE':'OFFLINE';
  if(count!=null)document.getElementById('liveCountNum').textContent=count;
  if(on&&!_autoRefreshTimer){
    _autoRefreshTimer=setInterval(()=>{loadLive(true);_nextRefreshAt=Date.now()+AUTO_REFRESH_MS;},AUTO_REFRESH_MS);
    _startCountdown();
  }else if(!on&&_autoRefreshTimer){
    clearInterval(_autoRefreshTimer);_autoRefreshTimer=null;
    _stopCountdown();
  }
}

async function loadLive(silent=false){
  const btn=document.getElementById('refreshBtn');
  if(!silent){btn.textContent='...';btn.disabled=true;}
  try{
    const r=await fetch('/api/live');
    const d=await r.json();
    renderHzGames(d.games||[]);
    renderLiveOther(d.other||[]);
    renderToday(d.today||[]);
    renderFtCandidates(d.q3||[]);
    renderFtToday(d.today||[]);
    renderPreview(d.today||[]);
    const totalLive=(d.games||[]).length+(d.q3||[]).length+(d.other||[]).length;
    setLive(d.source==='live'&&totalLive>0,totalLive);
    document.getElementById('hzCount').textContent=(d.games||[]).length;
    document.getElementById('ftCount').textContent=(d.q3||[]).length;
    if(silent&&_autoRefreshTimer)_startCountdown();
  }catch(e){
    if(!silent)document.getElementById('gamesWrap').innerHTML=`<div class="empty">⚠ ${e.message}</div>`;
    setLive(false,0);
  }
  if(!silent){btn.textContent='⟳ LIVE';btn.disabled=false;}
}

// ── HZ Engine ──
// isHT=true: game is at halftime — Q2 is complete, skip entry-time checks, use actual q2
function hzEngine({h2h,line,q1,q2,timer,fouls,ft,fg,lineDrop,lineRise,isHT=false}){
  // At HT: Q2 is fully played, projection = actual q1+q2, no entry-time gate
  const timeLeft=isHT?0:Math.max(0,10-timer);
  let q2proj=isHT?q2:(timer>0.5&&q2>0?q2+(q2/timer)*timeLeft:q1);
  const proj=q1+q2proj;
  const buffer=proj-line;
  const h2hBuf=h2h!=null&&h2h>0?h2h-line:null;
  const foulsOC=fouls>=HZ_FOULS_THRESHOLD,ftOC=ft!==null&&ft>=HZ_FT_PCT_CATALYST,lineMC=lineDrop||lineRise;
  const h2hOverCat=h2hBuf!==null&&h2hBuf<=HZ_H2H_OVER_BUFFER;
  const overCat=foulsOC||ftOC||lineMC||h2hOverCat;
  const fgSkip=fg!==null&&fg>HZ_FG_SKIP;
  // At HT entry is always valid (it's the last moment to bet HZ line)
  const entryOk=isHT||timeLeft>=HZ_ENTRY_MIN,entryA=isHT||timeLeft>=HZ_ENTRY_OPTIMAL;
  let dir='SKIP',stufe='C',reasons=[];
  if(buffer>=HZ_BUFFER_UNDER&&entryOk&&fouls<HZ_FOULS_THRESHOLD&&!fgSkip){
    dir='UNDER';
    if(entryA){
      if(h2hBuf!==null&&h2hBuf<HZ_H2H_UNDER_KONTRA){
        stufe='B';reasons=[`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ ${HZ_BUFFER_UNDER}</span>`,`<span class="r-warn">~ H2H ${h2h} &lt; Linie → kontra</span>`];
      }else{
        stufe='A';reasons=[`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ ${HZ_BUFFER_UNDER}</span>`];
        if(isHT)reasons.push(`<span class="r-ok">✓ Halbzeit — Ergebnis steht</span>`);
        else reasons.push(`<span class="r-ok">✓ Entry ${timeLeft.toFixed(1)}′</span>`,`<span class="r-ok">✓ Fouls ${fouls} &lt; ${HZ_FOULS_THRESHOLD}</span>`);
        if(h2hBuf!==null&&h2hBuf>=HZ_H2H_CONFIRM_BUFFER)reasons.push(`<span class="r-ok">✓ H2H +${h2hBuf.toFixed(1)} bestätigt</span>`);
      }
    }else{stufe='B';reasons=[`<span class="r-warn">~ Buffer +${buffer.toFixed(1)}</span>`,`<span class="r-warn">~ Entry ${timeLeft.toFixed(1)}′ spät</span>`];}
  }else if(buffer<=-HZ_BUFFER_OVER&&entryOk){
    dir='OVER';
    if(overCat){
      stufe='A';
      if(foulsOC)reasons.push(`<span class="r-ok">🔥 Fouls ${fouls} ≥ ${HZ_FOULS_THRESHOLD}</span>`);
      if(ftOC)reasons.push(`<span class="r-ok">🔥 FT% ${ft}%</span>`);
      if(lineMC)reasons.push(`<span class="r-ok">🔥 Linie bewegt</span>`);
      if(h2hOverCat)reasons.push(`<span class="r-ok">🔥 H2H ${h2hBuf.toFixed(1)} unter Linie</span>`);
    }else{stufe='B';reasons=[`<span class="r-warn">~ ${buffer.toFixed(1)} unter Linie</span>`,`<span class="r-warn">~ Kein Katalysator</span>`];}
    if(isHT)reasons.push(`<span class="r-ok">✓ Halbzeit — Ergebnis steht</span>`);
    else reasons.push(`<span class="r-ok">✓ Entry ${timeLeft.toFixed(1)}′</span>`);
  }else{
    if(fgSkip)reasons.push(`<span class="r-bad">✗ FG% ${fg}% &gt; ${HZ_FG_SKIP}</span>`);
    if(!isHT&&!entryOk)reasons.push(`<span class="r-bad">✗ Entry ${timeLeft.toFixed(1)}′ &lt; 2:30</span>`);
    if(Math.abs(buffer)<HZ_BUFFER_OVER)reasons.push(`<span class="r-bad">✗ Buffer ${buffer.toFixed(1)} &lt; ${HZ_BUFFER_OVER}</span>`);
    if(fouls>=HZ_FOULS_THRESHOLD&&buffer>0)reasons.push(`<span class="r-warn">⚠ Fouls ≥${HZ_FOULS_THRESHOLD} → OVER prüfen</span>`);
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
  const ftOK=(ftPctH!=null&&ftPctH>=FT_FT_PCT_THRESHOLD)&&(ftPctA!=null&&ftPctA>=FT_FT_PCT_THRESHOLD);
  let dir='SKIP',stufe='C',reasons=[];
  if(gap>FT_GAP_MAX){
    reasons.push(`<span class="r-bad">✗ Gap ${gap} &gt; ${FT_GAP_MAX} → Garbage Time Skip</span>`);
    return{dir,stufe,proj:current,buffer,timeLeft:null,fouls,reasons,type:'FT'};
  }
  if(buffer>=FT_BUFFER_UNDER_A&&ftOK){
    dir='UNDER';stufe='A';
    reasons.push(`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ ${FT_BUFFER_UNDER_A}</span>`);
    reasons.push(`<span class="r-ok">✓ FT% Heim ${ftPctH}% / Gast ${ftPctA}% ≥ ${FT_FT_PCT_THRESHOLD}</span>`);
    if(h2hBuf!==null&&h2hBuf>=FT_H2H_CONFIRM_BUFFER)reasons.push(`<span class="r-ok">✓ H2H +${h2hBuf.toFixed(1)} bestätigt</span>`);
  }else if(buffer>=FT_BUFFER_UNDER_B){
    dir='UNDER';stufe=ftOK?'A':'B';
    reasons.push(`<span class="r-ok">✓ Buffer +${buffer.toFixed(1)} ≥ ${FT_BUFFER_UNDER_B}</span>`);
    if(!ftOK)reasons.push(`<span class="r-warn">~ FT% unter ${FT_FT_PCT_THRESHOLD} → Stufe B</span>`);
  }else if(buffer<=-FT_BUFFER_OVER&&ftOK){
    dir='OVER';stufe='A';
    reasons.push(`<span class="r-ok">✓ Buffer ${buffer.toFixed(1)} ≤ −8</span>`);
    reasons.push(`<span class="r-ok">✓ FT% Heim ${ftPctH}% / Gast ${ftPctA}% ≥ ${FT_FT_PCT_THRESHOLD}</span>`);
    if(fouls>=FT_FOULS_CATALYST)reasons.push(`<span class="r-ok">🔥 Fouls ${fouls} ≥ ${FT_FOULS_CATALYST}</span>`);
  }else if(buffer<=-FT_BUFFER_OVER){
    dir='OVER';stufe='B';
    reasons.push(`<span class="r-warn">~ Buffer ${buffer.toFixed(1)} ≤ −${FT_BUFFER_OVER}</span>`);
    reasons.push(`<span class="r-warn">~ FT% nicht erfüllt → Stufe B</span>`);
  }else{
    reasons.push(`<span class="r-bad">✗ Buffer ${buffer.toFixed(1)} — min ±${FT_BUFFER_OVER} für FT</span>`);
  }
  return{dir,stufe,proj:current,buffer,timeLeft:null,fouls,reasons,type:'FT'};
}

// ── Render Signal ──
function renderSignal(sig){
  const sd=document.getElementById('sigDir');
  sd.textContent=sig.dir;
  sd.className='sig-dir'+(sig.dir==='UNDER'?' under':sig.dir==='OVER'?' over':'');
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
  const card=document.getElementById('signalStrip');
  card.className='signal-card'+(sig.dir==='UNDER'?' under':sig.dir==='OVER'?' over':'')+(sig.stufe==='A'?' glow':'');
}

// ── Manual calcs ──
function calcManualHz(){
  const h2h=parseFloat(document.getElementById('hH2H').value)||null;
  const line=parseFloat(document.getElementById('hLine').value);
  if(!line){alert('Bookie Line ist Pflicht!');return;}
  const sig=hzEngine({h2h,line,
    q1:parseFloat(document.getElementById('hQ1').value)||0,
    q2:parseFloat(document.getElementById('hQ2').value)||0,
    timer:parseFloat(document.getElementById('hTimer').value)||0,
    fouls:parseFloat(document.getElementById('hFouls').value)||0,
    ft:parseFloat(document.getElementById('hFT').value)||null,
    fg:parseFloat(document.getElementById('hFG').value)||null,
    lineDrop:document.getElementById('chkDrop').classList.contains('on'),
    lineRise:document.getElementById('chkRise').classList.contains('on'),
  });
  renderSignal(sig);
  logSignal(sig,'Manuell HZ');
}
function calcManualFt(){
  const line=parseFloat(document.getElementById('fLine').value);
  if(!line){alert('FT Bookie Line ist Pflicht!');return;}
  const sig=ftEngine({
    h2h:parseFloat(document.getElementById('fH2H').value)||null,
    line,
    q3h:parseFloat(document.getElementById('fQ3H').value)||0,
    q3a:parseFloat(document.getElementById('fQ3A').value)||0,
    hz:parseFloat(document.getElementById('fHZ').value)||0,
    fouls:parseFloat(document.getElementById('fFouls').value)||0,
    ftPctH:parseFloat(document.getElementById('fFTH').value)||null,
    ftPctA:parseFloat(document.getElementById('fFTA').value)||null,
  });
  renderSignal(sig);
  logSignal(sig,'Manuell FT');
}

// ── Badge helpers (update card signal colours without touching the signal panel) ──
function _applyHzBadge(id,sig){
  const cls=sig.dir==='UNDER'?'sig-under':sig.dir==='OVER'?'sig-over':'';
  const card=document.getElementById('gc-'+id);
  if(card)card.className=`game-card ${cls}${sig.stufe==='A'?' sig-a':''}`;
  const badge=document.getElementById('badge-'+id);
  if(badge){badge.className=`card-sig-badge ${sig.dir.toLowerCase()}`;badge.textContent=sig.dir;}
  const sEl=document.getElementById('stufe-'+id);
  if(sEl){sEl.className=`card-stufe-badge ${sig.stufe.toLowerCase()}`;sEl.textContent=sig.stufe==='C'?'SKIP':sig.stufe;}
}
function _applyFtBadge(id,sig){
  const cls=sig.dir==='UNDER'?'sig-under':sig.dir==='OVER'?'sig-over':'';
  const card=document.getElementById('ftc-'+id);
  if(card)card.className=`ft-card ${cls}${sig.stufe==='A'?' sig-a':''}`;
  const badge=document.getElementById('ftbadge-'+id);
  if(badge){badge.className=`card-sig-badge ${sig.dir.toLowerCase()}`;badge.textContent=sig.dir;}
  const sEl=document.getElementById('ftstufe-'+id);
  if(sEl){sEl.className=`card-stufe-badge ${sig.stufe.toLowerCase()}`;sEl.textContent=sig.stufe==='C'?'SKIP':sig.stufe;}
}

// ── Auto-load: fetch H2H + stats and run engine for each card on render ──
async function autoLoadHzCard(g){
  const id=g.id;
  const card=document.getElementById('gc-'+id);
  if(!card)return;
  const [h2hRes,statsRes]=await Promise.allSettled([
    fetch(`/api/h2h?home=${encodeURIComponent(g.home)}&away=${encodeURIComponent(g.away)}`).then(r=>r.json()),
    fetch(`/api/game-stats/${id}`).then(r=>r.json()),
  ]);
  let fouls=0,ftPct=null,fgPct=null,h2hAvg=null;
  try{
    const d=h2hRes.value;const note=document.getElementById('h2hn-'+id);const inp=document.getElementById('ih2h-'+id);
    if(d.found){
      note.textContent=`H2H Ø ${d.avg} (${d.count}x)`;note.className='h2h-note found';
      if(inp&&!inp.value){inp.value=d.avg;const lbl=document.getElementById('h2hlbl-'+id);if(lbl)lbl.textContent=`H2H Ø (${d.count}x)`;}
      const lineInp=document.getElementById('iline-'+id);
      if(lineInp&&!lineInp.value){lineInp.value=d.avg;lineInp.title='H2H-Ø als Referenz';}
      h2hAvg=d.avg;
    }else{if(note)note.textContent='H2H: kein Eintrag';}
  }catch(e){}
  try{
    const s=statsRes.value;
    if(s.found){
      const fi=document.getElementById('ifouls-'+id),ti=document.getElementById('ift-'+id),gi=document.getElementById('ifg-'+id);
      if(fi&&!fi.value&&s.total_fouls>0)fi.value=s.total_fouls;
      if(ti&&!ti.value&&s.avg_ft_pct!=null)ti.value=s.avg_ft_pct;
      if(gi&&!gi.value&&s.avg_fg_pct!=null)gi.value=s.avg_fg_pct;
      fouls=s.total_fouls||0;ftPct=s.avg_ft_pct;fgPct=s.avg_fg_pct;
      const note=document.getElementById('h2hn-'+id);
      const extra=(fouls>0?` · Fouls:${fouls}`:'')+
                  (ftPct!=null?` · FT%:${ftPct}`:'');
      if(note&&extra)note.textContent+=extra;
    }
  }catch(e){}
  if(h2hAvg!=null){
    const q1=parseFloat(card.dataset.q1)||0,q2=parseFloat(card.dataset.q2)||0;
    const tmr=parseFloat(card.dataset.timer)||0,isHT=card.dataset.isht==='1';
    const sig=hzEngine({h2h:h2hAvg,line:h2hAvg,q1,q2,timer:tmr,isHT,fouls,ft:ftPct,fg:fgPct,lineDrop:false,lineRise:false});
    _applyHzBadge(id,sig);
  }
}
async function autoLoadFtCard(g){
  const id=g.id;
  const card=document.getElementById('ftc-'+id);
  if(!card)return;
  const [h2hRes,statsRes]=await Promise.allSettled([
    fetch(`/api/h2h?home=${encodeURIComponent(g.home)}&away=${encodeURIComponent(g.away)}&type=ft`).then(r=>r.json()),
    fetch(`/api/game-stats/${id}`).then(r=>r.json()),
  ]);
  let fouls=0,homeFt=null,awayFt=null,h2hAvg=null;
  try{
    const d=h2hRes.value;const note=document.getElementById('fth2hn-'+id);const inp=document.getElementById('ifth2h-'+id);
    if(d.found){
      note.textContent=`H2H FT Ø ${d.avg} (${d.count}x)`;note.className='h2h-note found';
      if(inp&&!inp.value){inp.value=d.avg;const ftlbl=document.getElementById('fth2hlbl-'+id);if(ftlbl)ftlbl.textContent=`H2H FT Ø (${d.count}x)`;}
      const lineInp=document.getElementById('iftline-'+id);
      if(lineInp&&!lineInp.value){lineInp.value=d.avg;lineInp.title='H2H-FT-Ø als Referenz';}
      h2hAvg=d.avg;
    }else{if(note)note.textContent='H2H FT: kein Eintrag';}
  }catch(e){}
  try{
    const s=statsRes.value;
    if(s.found){
      const fi=document.getElementById('iftfouls-'+id),fh=document.getElementById('iftfth-'+id),fa=document.getElementById('iftfta-'+id);
      if(fi&&!fi.value&&s.total_fouls>0)fi.value=s.total_fouls;
      if(fh&&!fh.value&&s.home_ft_pct!=null)fh.value=s.home_ft_pct;
      if(fa&&!fa.value&&s.away_ft_pct!=null)fa.value=s.away_ft_pct;
      fouls=s.total_fouls||0;homeFt=s.home_ft_pct;awayFt=s.away_ft_pct;
      const note=document.getElementById('fth2hn-'+id);
      const extra=(fouls>0?` · Fouls:${fouls}`:'')+
                  (homeFt!=null?` · FT%H:${homeFt}`:'')+
                  (awayFt!=null?` · FT%G:${awayFt}`:'');
      if(note&&extra)note.textContent+=extra;
    }
  }catch(e){}
  if(h2hAvg!=null){
    const hz=parseFloat(card.dataset.hz)||0,q3h=parseFloat(card.dataset.q3h)||0,q3a=parseFloat(card.dataset.q3a)||0;
    const sig=ftEngine({h2h:h2hAvg,line:h2hAvg,q3h,q3a,hz,fouls,ftPctH:homeFt,ftPctA:awayFt});
    _applyFtBadge(id,sig);
  }
}
async function autoLoadOtherCard(g){
  const el=document.getElementById('ostats-'+g.id);
  if(!el)return;
  try{
    const s=await fetch(`/api/game-stats/${g.id}`).then(r=>r.json());
    if(s.found){
      const parts=[];
      if(s.total_fouls>0)parts.push(`Fouls: ${s.total_fouls}`);
      if(s.avg_ft_pct!=null)parts.push(`FT%: ${s.avg_ft_pct}`);
      if(s.avg_fg_pct!=null)parts.push(`FG%: ${s.avg_fg_pct}`);
      el.textContent=parts.length?parts.join(' · '):'';
    }else{el.textContent='';}
  }catch(e){el.textContent='';}
}

// ── HZ Cards ──
function renderHzGames(games){
  const w=document.getElementById('gamesWrap');
  if(!games.length){w.innerHTML='<div class="empty">Keine HT/Q2 Spiele live<br><span style="font-size:9px;color:var(--dim)">EU-Ligen meist 18–22 Uhr</span></div>';return;}
  w.innerHTML=games.map(g=>hzCard(g)).join('');
  applyWatchlistUI();
  games.forEach(g=>autoLoadHzCard(g));
}
function hzCard(g){
  const isHT=g.status==='HT';
  const timer=g.timer||0;
  const label=isHT?'HALBZEIT':`Q2 · ${timer}′`;
  return`<div class="game-card" id="gc-${g.id}" data-q1="${g.q1_total}" data-q2="${g.q2_live||0}" data-timer="${timer}" data-isht="${isHT?'1':'0'}" onclick="selectHzCard(${g.id},${JSON.stringify(g.home).replace(/"/g,'&quot;')},${JSON.stringify(g.away).replace(/"/g,'&quot;')})">
    <div class="card-stripe"></div>
    <div class="card-body">
      <div class="card-top"><span class="card-league">${g.league_name}</span><div style="display:flex;align-items:center;gap:5px;"><span class="wl-star" id="wl-${g.id}" data-id="${g.id}">★</span><span class="card-status">${label}</span></div></div>
      <div class="card-teams">
        <div class="card-team">${g.home}</div>
        <div class="score-block"><div class="score-num">${g.total_home}–${g.total_away}</div><div class="score-q1">Q1: ${g.q1_home}–${g.q1_away}</div></div>
        <div class="card-team away">${g.away}</div>
      </div>
      <div class="card-stats-row">
        <div class="cs"><div class="cs-val">${g.q1_total}</div><div class="cs-lbl">Q1</div></div>
        <div class="cs"><div class="cs-val">${g.q2_live||'—'}</div><div class="cs-lbl">Q2</div></div>
        <div class="cs"><div class="cs-val">${g.ht_total}</div><div class="cs-lbl">HT</div></div>
      </div>
      <div class="card-bot">
        <span class="h2h-note" id="h2hn-${g.id}">H2H laden…</span>
        <span class="card-sig-badge none" id="badge-${g.id}">?</span>
        <span class="card-stufe-badge c" id="stufe-${g.id}"></span>
      </div>
    </div>
    <div class="card-inputs" id="ci-${g.id}">
      <div class="inp-group"><label id="h2hlbl-${g.id}">H2H Ø</label><input type="number" id="ih2h-${g.id}" placeholder="96.5" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>Bookie Line</label><input type="number" id="iline-${g.id}" placeholder="91.5" step="0.5" inputmode="decimal"></div>
      <div class="inp-group"><label>Fouls</label><input type="number" id="ifouls-${g.id}" placeholder="5" min="0" inputmode="numeric"></div>
      <div class="inp-group"><label>FT% Ø</label><input type="number" id="ift-${g.id}" placeholder="—" inputmode="numeric"></div>
      <div class="inp-group"><label>FG%</label><input type="number" id="ifg-${g.id}" placeholder="—" inputmode="numeric"></div>
      <button class="calc-mini" onclick="event.stopPropagation();calcHzCard(${g.id},${g.q1_total},${g.q2_live||0},${timer},${isHT})">▶ SIGNAL</button>
    </div>
  </div>`;
}
async function selectHzCard(id,home,away){
  document.querySelectorAll('.game-card').forEach(c=>{c.classList.remove('selected');const ci=c.querySelector('.card-inputs');if(ci)ci.classList.remove('open');});
  const card=document.getElementById('gc-'+id);
  if(card){card.classList.add('selected');document.getElementById('ci-'+id).classList.add('open');}
  const [h2hRes,statsRes]=await Promise.allSettled([
    fetch(`/api/h2h?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}`).then(r=>r.json()),
    fetch(`/api/game-stats/${id}`).then(r=>r.json()),
  ]);
  let h2hAvg=null;
  try{
    const d=h2hRes.value;const note=document.getElementById('h2hn-'+id);const inp=document.getElementById('ih2h-'+id);
    if(d.found){note.textContent=`H2H Ø ${d.avg} (${d.count}x)`;note.className='h2h-note found';
      if(inp&&!inp.value){inp.value=d.avg;const lbl=document.getElementById('h2hlbl-'+id);if(lbl)lbl.textContent=`H2H Ø (${d.count}x)`;}
      // Pre-fill bookie line with H2H avg if the user hasn't entered one yet
      const lineInp=document.getElementById('iline-'+id);
      if(lineInp&&!lineInp.value){lineInp.value=d.avg;lineInp.title='H2H-Ø als Referenz (Bookie Line überschreiben)';}
      h2hAvg=d.avg;
    }else{note.textContent='H2H: kein Eintrag';note.className='h2h-note';}
  }catch(e){document.getElementById('h2hn-'+id).textContent='H2H: Fehler';}
  try{
    const s=statsRes.value;
    if(s.found){
      const fi=document.getElementById('ifouls-'+id),ti=document.getElementById('ift-'+id),gi=document.getElementById('ifg-'+id);
      if(fi&&!fi.value&&s.total_fouls>0)fi.value=s.total_fouls;
      if(ti&&!ti.value&&s.avg_ft_pct!=null)ti.value=s.avg_ft_pct;
      if(gi&&!gi.value&&s.avg_fg_pct!=null)gi.value=s.avg_fg_pct;
      const note=document.getElementById('h2hn-'+id);
      const extra=(s.total_fouls>0?` · Fouls:${s.total_fouls}`:'')+
                  (s.avg_ft_pct!=null?` · FT%:${s.avg_ft_pct}`:'');
      if(note&&extra)note.textContent+=extra;
    }
  }catch(e){}
  // Auto-calculate signal as soon as H2H (used as reference line) is available
  if(h2hAvg&&card){
    const q1=parseFloat(card.dataset.q1)||0;
    const q2=parseFloat(card.dataset.q2)||0;
    const tmr=parseFloat(card.dataset.timer)||0;
    const isHT=card.dataset.isht==='1';
    calcHzCard(id,q1,q2,tmr,isHT);
  }
  // Odds feed: pre-fill bookie line only if user hasn't typed anything
  try{
    const oddsD=await fetch(`/api/odds?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}`).then(r=>r.json());
    if(oddsD.found){
      const lineInp=document.getElementById('iline-'+id);
      if(lineInp&&!lineInp.value){
        lineInp.value=oddsD.line;
        lineInp.title=`Odds: ${oddsD.line} (${oddsD.bookmaker||'TheOddsAPI'})`;
        const note=document.getElementById('h2hn-'+id);
        if(note)note.textContent+=(note.textContent?' · ':'')+'Odds: '+oddsD.line;
      }
    }
  }catch(e){}
}
function calcHzCard(id,q1,q2live,timer,isHT=false){
  const line=parseFloat(document.getElementById('iline-'+id).value);
  if(!line){alert('Bookie Line eingeben!');return;}
  const sig=hzEngine({
    h2h:parseFloat(document.getElementById('ih2h-'+id).value)||null,
    line,q1,q2:q2live,timer,isHT,
    fouls:parseFloat(document.getElementById('ifouls-'+id).value)||0,
    ft:parseFloat(document.getElementById('ift-'+id)?.value)||null,
    fg:parseFloat(document.getElementById('ifg-'+id)?.value)||null,
    lineDrop:false,lineRise:false,
  });
  const card=document.getElementById('gc-'+id);
  const cls=sig.dir==='UNDER'?'sig-under':sig.dir==='OVER'?'sig-over':'';
  card.className=`game-card selected ${cls} ${sig.stufe==='A'?'sig-a':''}`;
  document.getElementById('badge-'+id).className=`card-sig-badge ${sig.dir.toLowerCase()}`;
  document.getElementById('badge-'+id).textContent=sig.dir;
  const sEl=document.getElementById('stufe-'+id);
  sEl.className=`card-stufe-badge ${sig.stufe.toLowerCase()}`;
  sEl.textContent=sig.stufe==='C'?'SKIP':sig.stufe;
  renderSignal(sig);
  const teams=card?.querySelectorAll('.card-team');
  const ctx=teams&&teams.length>=2?teams[0].textContent+' / '+teams[1].textContent:'Spiel #'+id;
  logSignal(sig,ctx);
}

// ── Live Other (Q1/Q3/Q4/OT — in progress, not at a trading window) ──
function renderLiveOther(games){
  document.getElementById('liveOtherCount').textContent=games.length;
  const w=document.getElementById('liveOtherWrap');
  if(!games.length){w.innerHTML='<div class="empty">Keine weiteren Live-Spiele</div>';return;}
  w.innerHTML=games.map(g=>{
    const st=g.status||'?';
    return`<div class="today-card"><div class="card-stripe" style="background:var(--green)"></div>
      <div class="today-body">
        <div class="today-top"><span class="today-league">${g.league_name}</span><span class="today-status" style="color:var(--green)">${st}${g.timer?' '+g.timer+'′':''}</span></div>
        <div class="today-teams">
          <div class="today-team">${g.home}</div>
          <div><div class="today-score">${g.total_home}–${g.total_away}</div><div class="today-q">Q1:${g.q1_total} Q2:${g.q2_live??'—'}</div></div>
          <div class="today-team away">${g.away}</div>
        </div>
        <div class="today-q" id="ostats-${g.id}" style="color:var(--dim);margin-top:2px">…</div>
      </div></div>`;
  }).join('');
  games.forEach(g=>autoLoadOtherCard(g));
}

// ── Today list ──
function renderToday(games){
  const w=document.getElementById('todayWrap');
  if(!games.length){w.innerHTML='<div class="empty" style="font-size:10px;margin-top:6px">Keine Spiele heute</div>';return;}
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
      </div></div>`;
  }).join('');
}

// ── FT Cards ──
function renderFtCandidates(games){
  const w=document.getElementById('ftGamesWrap');
  if(!games.length){w.innerHTML='<div class="empty">Keine Spiele am Q3 Break</div>';return;}
  w.innerHTML=games.map(g=>ftCard(g)).join('');
  applyWatchlistUI();
  games.forEach(g=>autoLoadFtCard(g));
}
function ftCard(g){
  const q3tot=(g.q3_home||0)+(g.q3_away||0);
  const gap=Math.abs((g.q3_home||0)-(g.q3_away||0));
  return`<div class="ft-card" id="ftc-${g.id}" data-hz="${g.ht_total}" data-q3h="${g.q3_home||0}" data-q3a="${g.q3_away||0}" onclick="selectFtCard(${g.id},${JSON.stringify(g.home).replace(/"/g,'&quot;')},${JSON.stringify(g.away).replace(/"/g,'&quot;')})">
    <div class="card-stripe"></div>
    <div class="ft-body">
      <div class="card-top"><span class="card-league">${g.league_name}</span><div style="display:flex;align-items:center;gap:5px;"><span class="wl-star" id="wl-${g.id}" data-id="${g.id}">★</span><span class="card-status">Q3 BREAK</span></div></div>
      <div class="card-teams">
        <div class="card-team">${g.home}</div>
        <div class="score-block"><div class="score-num">${g.total_home}–${g.total_away}</div><div class="score-q1">HZ:${g.ht_total} Gap:${gap}</div></div>
        <div class="card-team away">${g.away}</div>
      </div>
      <div class="card-stats-row">
        <div class="cs"><div class="cs-val">${g.ht_total}</div><div class="cs-lbl">HZ</div></div>
        <div class="cs"><div class="cs-val">${q3tot||'—'}</div><div class="cs-lbl">Q3</div></div>
        <div class="cs"><div class="cs-val">${gap}</div><div class="cs-lbl">Gap</div></div>
      </div>
      <div class="card-bot">
        <span class="h2h-note" id="fth2hn-${g.id}">H2H FT laden…</span>
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
  const [h2hRes,statsRes]=await Promise.allSettled([
    fetch(`/api/h2h?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}&type=ft`).then(r=>r.json()),
    fetch(`/api/game-stats/${id}`).then(r=>r.json()),
  ]);
  let h2hAvg=null;
  try{
    const d=h2hRes.value;const note=document.getElementById('fth2hn-'+id);
    if(d.found){
      note.textContent=`H2H FT Ø ${d.avg} (${d.count}x)`;note.className='h2h-note found';
      const inp=document.getElementById('ifth2h-'+id);
      if(inp&&!inp.value){inp.value=d.avg;const ftlbl=document.getElementById('fth2hlbl-'+id);if(ftlbl)ftlbl.textContent=`H2H FT Ø (${d.count}x)`;}
      // Pre-fill bookie line with H2H FT avg if the user hasn't entered one yet
      const lineInp=document.getElementById('iftline-'+id);
      if(lineInp&&!lineInp.value){lineInp.value=d.avg;lineInp.title='H2H-FT-Ø als Referenz (Bookie Line überschreiben)';}
      h2hAvg=d.avg;
    }else{note.textContent='H2H FT: kein Eintrag';note.className='h2h-note';}
  }catch(e){}
  try{
    const s=statsRes.value;
    if(s.found){
      const fi=document.getElementById('iftfouls-'+id);
      const fh=document.getElementById('iftfth-'+id);
      const fa=document.getElementById('iftfta-'+id);
      if(fi&&!fi.value&&s.total_fouls>0)fi.value=s.total_fouls;
      if(fh&&!fh.value&&s.home_ft_pct!=null)fh.value=s.home_ft_pct;
      if(fa&&!fa.value&&s.away_ft_pct!=null)fa.value=s.away_ft_pct;
      const note=document.getElementById('fth2hn-'+id);
      const extra=(s.total_fouls>0?` · Fouls:${s.total_fouls}`:'')+
                  (s.home_ft_pct!=null?` · FT%H:${s.home_ft_pct}`:'')+
                  (s.away_ft_pct!=null?` · FT%G:${s.away_ft_pct}`:'');
      if(note&&extra)note.textContent+=extra;
    }
  }catch(e){}
  // Auto-calculate signal as soon as H2H FT (used as reference line) is available
  if(h2hAvg&&card){
    const hz=parseFloat(card.dataset.hz)||0;
    const q3h=parseFloat(card.dataset.q3h)||0;
    const q3a=parseFloat(card.dataset.q3a)||0;
    calcFtCard(id,hz,q3h,q3a);
  }
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
  renderSignal(sig);
  const ftTeams=card?.querySelectorAll('.card-team');
  const ftCtx=ftTeams&&ftTeams.length>=2?ftTeams[0].textContent+' / '+ftTeams[1].textContent:'Spiel #'+id;
  logSignal(sig,ftCtx);
}
function renderFtToday(games){
  // kept for JS compatibility — today section shows all games incl. FT
  const w=document.getElementById('ftTodayWrap');
  if(!w)return;
  const done=games.filter(g=>g.status==='FT');
  w.innerHTML=done.map(g=>`<div>${g.home} vs ${g.away} — ${g.total_home+g.total_away}</div>`).join('');
}

// ── Watchlist ──
const _watchlist=new Set(JSON.parse(localStorage.getItem('hz_wl')||'[]'));
function _saveWatchlist(){localStorage.setItem('hz_wl',JSON.stringify([..._watchlist]));}
function toggleWatchlist(id){
  const btn=document.getElementById('wbtn-'+id);
  const card=document.getElementById('pvc-'+id);
  if(_watchlist.has(id)){
    _watchlist.delete(id);
    if(btn)btn.classList.remove('active');
    if(card)card.classList.remove('wl-active');
  }else{
    _watchlist.add(id);
    if(btn)btn.classList.add('active');
    if(card)card.classList.add('wl-active');
  }
  _saveWatchlist();
  applyWatchlistUI();
}
function applyWatchlistUI(){
  document.querySelectorAll('.wl-star').forEach(el=>{
    const id=parseInt(el.dataset.id);
    el.classList.toggle('vis',_watchlist.has(id));
  });
}

// ── Pre-Game Preview ──
function renderPreview(games){
  const ns=games.filter(g=>g.status==='NS');
  document.getElementById('previewCount').textContent=ns.length;
  const w=document.getElementById('previewWrap');
  if(!ns.length){w.innerHTML='<div class="empty">Keine Spiele anstehend</div>';return;}
  w.innerHTML=ns.map(g=>previewCard(g)).join('');
  ns.forEach(g=>loadPreviewH2h(g));
  applyWatchlistUI();
}
function previewCard(g){
  const isWl=_watchlist.has(g.id);
  return`<div class="preview-card no-h2h${isWl?' wl-active':''}" id="pvc-${g.id}">
    <div class="card-stripe"></div>
    <div class="pre-card-body">
      <div class="pre-card-top">
        <span class="card-league">${g.league_name}</span>
        <div style="display:flex;align-items:center;gap:4px;">
          <span style="font-size:9px;color:var(--dim2);letter-spacing:1px;">NS</span>
          <button class="watch-btn${isWl?' active':''}" id="wbtn-${g.id}"
            onclick="event.stopPropagation();toggleWatchlist(${g.id})" title="Watchlist">★</button>
        </div>
      </div>
      <div class="pre-card-teams">
        <div class="card-team">${g.home}</div>
        <div class="score-block"><div style="font-size:10px;color:var(--dim2);text-align:center;">vs</div></div>
        <div class="card-team away">${g.away}</div>
      </div>
      <div class="pre-line-row">
        <label>HZ Line</label>
        <input type="number" id="pvline-${g.id}" placeholder="91.5" step="0.5" inputmode="decimal"
          oninput="calcPreSignal(${g.id})">
      </div>
      <div class="pre-card-bot">
        <div style="display:flex;flex-direction:column;gap:2px;">
          <span class="h2h-note" id="pvh2h-${g.id}">H2H lädt…</span>
          <span class="h2h-note" id="pvfth2h-${g.id}" style="font-size:8px;color:var(--dim);">FT H2H lädt…</span>
        </div>
        <span class="pre-sig-badge neutral" id="pvbadge-${g.id}">—</span>
      </div>
    </div>
  </div>`;
}
async function loadPreviewH2h(g){
  try{
    const [hzD,ftD]=await Promise.all([
      fetch(`/api/h2h?home=${encodeURIComponent(g.home)}&away=${encodeURIComponent(g.away)}`).then(r=>r.json()),
      fetch(`/api/h2h?home=${encodeURIComponent(g.home)}&away=${encodeURIComponent(g.away)}&type=ft`).then(r=>r.json()),
    ]);
    const note=document.getElementById('pvh2h-'+g.id);
    const ftNote=document.getElementById('pvfth2h-'+g.id);
    const card=document.getElementById('pvc-'+g.id);
    if(!note||!card)return;
    if(hzD.found){
      note.textContent=`HZ H2H Ø ${hzD.avg} (${hzD.count}×)`;
      note.className='h2h-note found';
      card.classList.remove('no-h2h');
      card.dataset.h2h=hzD.avg;
      const lineEl=document.getElementById('pvline-'+g.id);
      if(lineEl&&!lineEl.value)lineEl.value=hzD.avg;
      calcPreSignal(g.id);
    }else{
      note.innerHTML='<span class="h2h-missing">H2H fehlt — Backfill nötig</span>';
      note.className='h2h-note';
    }
    if(ftNote){
      if(ftD.found){
        ftNote.textContent=`FT H2H Ø ${ftD.avg} (${ftD.count}×)`;
        ftNote.className='h2h-note found';
        ftNote.style.fontSize='8px';
      }else{
        ftNote.textContent='FT H2H —';
        ftNote.style.color='var(--dim)';
      }
    }
    // Odds feed: override line with bookie odds only if user hasn't typed anything
    try{
      const oddsD=await fetch(`/api/odds?home=${encodeURIComponent(g.home)}&away=${encodeURIComponent(g.away)}`).then(r=>r.json());
      if(oddsD.found){
        const lineEl=document.getElementById('pvline-'+g.id);
        if(lineEl&&!lineEl.value){
          lineEl.value=oddsD.line;
          lineEl.title=`Odds: ${oddsD.line} (${oddsD.bookmaker||'TheOddsAPI'})`;
          calcPreSignal(g.id);
        }
      }
    }catch(e){}
  }catch(e){
    const note=document.getElementById('pvh2h-'+g.id);
    if(note)note.textContent='H2H: Fehler';
  }
}
function calcPreSignal(id){
  const card=document.getElementById('pvc-'+id);
  const badge=document.getElementById('pvbadge-'+id);
  if(!card||!badge)return;
  const h2h=parseFloat(card.dataset.h2h);
  const line=parseFloat(document.getElementById('pvline-'+id)?.value);
  if(!Number.isFinite(h2h)||!Number.isFinite(line)||h2h===0||line===0){badge.textContent='—';badge.className='pre-sig-badge neutral';return;}
  const buf=+(h2h-line).toFixed(1);
  if(buf>=5){
    badge.textContent=`UNDER ▾ +${buf}`;
    badge.className='pre-sig-badge under';
  }else if(buf<=-5){
    badge.textContent=`OVER ▴ ${buf}`;
    badge.className='pre-sig-badge over';
  }else{
    badge.textContent=`NEUTRAL ${buf>=0?'+':''}${buf}`;
    badge.className='pre-sig-badge neutral';
  }
}

// ── Live calculation while typing (debounced 400ms) ──
let _debHz=null,_debFt=null;
function _liveHz(){
  clearTimeout(_debHz);
  _debHz=setTimeout(()=>{
    const line=parseFloat(document.getElementById('hLine').value);
    if(!line)return;
    renderSignal(hzEngine({
      h2h:parseFloat(document.getElementById('hH2H').value)||null,
      line,
      q1:parseFloat(document.getElementById('hQ1').value)||0,
      q2:parseFloat(document.getElementById('hQ2').value)||0,
      timer:parseFloat(document.getElementById('hTimer').value)||0,
      fouls:parseFloat(document.getElementById('hFouls').value)||0,
      ft:parseFloat(document.getElementById('hFT').value)||null,
      fg:parseFloat(document.getElementById('hFG').value)||null,
      lineDrop:document.getElementById('chkDrop').classList.contains('on'),
      lineRise:document.getElementById('chkRise').classList.contains('on'),
    }));
  },400);
}
function _liveFt(){
  clearTimeout(_debFt);
  _debFt=setTimeout(()=>{
    const line=parseFloat(document.getElementById('fLine').value);
    if(!line)return;
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
  },400);
}

// ── Signal Log ──
const _signalLog=[];
const _MAX_LOG=50;
function _tsNow(){
  const d=new Date();
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}
function _genId(){return Date.now().toString(36)+Math.random().toString(36).slice(2,5);}
function logSignal(sig,ctx=''){
  const id=_genId();
  const entry={id,ts:_tsNow(),dir:sig.dir,stufe:sig.stufe,type:sig.type||'HZ',buf:sig.buffer,ctx};
  _signalLog.unshift(entry);
  if(_signalLog.length>_MAX_LOG)_signalLog.length=_MAX_LOG;
  document.getElementById('logCount').textContent=_signalLog.length;
  renderSignalLog();
  // Auto-track all non-SKIP signals for P&L recording
  if(sig.dir!=='SKIP'){
    const tracked=_loadTracked();
    tracked.push({...entry,result:null});
    _saveTracked(tracked);
  }
  if(sig.dir!=='SKIP'){
    _doNotify(sig,ctx);
    _doTabTitle(sig);
    if(sig.stufe==='A'){
      _playBeep(sig.dir);
      _pushToTelegram(sig,ctx);
    }
  }
}
function renderSignalLog(){
  const w=document.getElementById('sigLogWrap');
  if(!_signalLog.length){
    w.innerHTML='<div class="empty" style="font-size:10px;padding:8px 14px;">Noch kein Signal berechnet</div>';
    return;
  }
  w.innerHTML=_signalLog.map(e=>`<div class="sig-log-entry">
    <span class="sig-log-time">${e.ts}</span>
    <span class="sig-log-dir ${e.dir.toLowerCase()}">${e.dir}</span>
    <span class="sig-log-stufe ${e.stufe.toLowerCase()}">ST-${e.stufe}</span>
    <span class="sig-log-type">${e.type}</span>
    <span class="sig-log-buf">${e.buf!=null?(e.buf>=0?'+':'')+e.buf.toFixed(1):'—'}</span>
    ${e.ctx?`<span class="sig-log-ctx">${e.ctx}</span>`:''}
  </div>`).join('');
}
function clearLog(){
  _signalLog.length=0;
  document.getElementById('logCount').textContent=0;
  renderSignalLog();
}

// ── Browser Notifications ──
let _notifOn=localStorage.getItem('hz_notif')==='1';
function toggleNotif(){
  if(!_notifOn){
    Notification.requestPermission().then(p=>{
      _notifOn=p==='granted';
      localStorage.setItem('hz_notif',_notifOn?'1':'0');
      _updateNotifBtn();
    });
  }else{
    _notifOn=false;localStorage.setItem('hz_notif','0');_updateNotifBtn();
  }
}
function _updateNotifBtn(){
  const btn=document.getElementById('notifBtn');if(!btn)return;
  btn.textContent=_notifOn?'🔔 AN':'🔕 AUS';
  btn.classList.toggle('active',_notifOn);
}
function _doNotify(sig,ctx){
  if(!_notifOn||Notification.permission!=='granted')return;
  const title=`${sig.dir} STUFE ${sig.stufe} · ${sig.type}`;
  const buf=sig.buffer!=null?(sig.buffer>=0?'+':'')+sig.buffer.toFixed(1):'—';
  const body=`Buffer: ${buf}${ctx?' · '+ctx:''}`;
  try{new Notification(title,{body,tag:'hz-signal'});}catch(e){}
}

// ── Sound Alerts ──
let _soundOn=localStorage.getItem('hz_sound')==='1';
let _audioCtx=null;
function _getAudioCtx(){
  if(!_audioCtx){try{_audioCtx=new(window.AudioContext||window.webkitAudioContext)();}catch(e){}}
  return _audioCtx;
}
function _playBeep(dir){
  if(!_soundOn)return;
  const ctx=_getAudioCtx();if(!ctx)return;
  const freq=dir==='UNDER'?880:620;
  const osc=ctx.createOscillator();const gain=ctx.createGain();
  osc.connect(gain);gain.connect(ctx.destination);
  osc.type='sine';osc.frequency.value=freq;
  gain.gain.setValueAtTime(0.25,ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.45);
  osc.start(ctx.currentTime);osc.stop(ctx.currentTime+0.45);
}
function toggleSound(){
  _soundOn=!_soundOn;localStorage.setItem('hz_sound',_soundOn?'1':'0');
  _updateSoundBtn();
  if(_soundOn)_playBeep('UNDER');
}
function _updateSoundBtn(){
  const btn=document.getElementById('soundBtn');if(!btn)return;
  btn.textContent=_soundOn?'🔊 AN':'🔇 AUS';
  btn.classList.toggle('active',_soundOn);
}

// ── Telegram Push ──
async function _pushToTelegram(sig,ctx){
  try{
    await fetch('/api/telegram/push',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...sig,label:ctx||''}),
    });
  }catch(e){}
}
async function testTelegram(){
  const btn=document.getElementById('tgTestBtn');
  if(btn){btn.textContent='…';btn.disabled=true;}
  try{
    const r=await fetch('/api/telegram/test').then(res=>res.json());
    if(r.sent){alert('✅ Telegram Test gesendet!');}
    else{alert('❌ Telegram nicht konfiguriert — TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID setzen.');}
  }catch(e){
    alert('❌ Fehler beim Telegram Test: '+e.message);
  }finally{
    if(btn){btn.textContent='📱 TG';btn.disabled=false;}
  }
}

// ── Tab title alert (Stufe A only) ──
let _tabRestoreTimer=null;
function _doTabTitle(sig){
  if(sig.stufe!=='A')return;
  const icon=sig.dir==='UNDER'?'▾':'▴';
  document.title=`${icon} ${sig.dir} · HZ/FT Trading`;
  clearTimeout(_tabRestoreTimer);
  _tabRestoreTimer=setTimeout(()=>{document.title='HZ / FT Trading';},12000);
}

// ── Statistics & P&L Tracking ──
const TRACKED_KEY='hz_tracked_signals';
function _loadTracked(){
  try{return JSON.parse(localStorage.getItem(TRACKED_KEY)||'[]');}
  catch(e){return [];}
}
function _saveTracked(arr){
  // Cap at 500 entries to stay within typical localStorage size limits (~5MB)
  try{localStorage.setItem(TRACKED_KEY,JSON.stringify(arr.slice(-500)));}
  catch(e){}
}
function markResult(id,result){
  const arr=_loadTracked();
  const e=arr.find(x=>x.id===id);
  if(!e)return;
  e.result=(e.result===result)?null:result; // toggle off if same
  _saveTracked(arr);
  renderStats();
}
function clearTracked(){
  if(!confirm('Tracking-Daten wirklich löschen?'))return;
  localStorage.removeItem(TRACKED_KEY);
  renderStats();
}
function toggleStats(){
  const ov=document.getElementById('statsOverlay');
  ov.classList.toggle('open');
  if(ov.classList.contains('open'))renderStats();
}
async function renderStats(){
  const body=document.getElementById('statsBody');
  if(!body)return;
  const tracked=_loadTracked();
  const session=[..._signalLog];

  // Session summary
  const sDir={UNDER:0,OVER:0,SKIP:0};
  const sStufe={A:0,B:0,C:0};
  const sType={HZ:0,FT:0};
  for(const s of session){
    sDir[s.dir]=(sDir[s.dir]||0)+1;
    sStufe[s.stufe]=(sStufe[s.stufe]||0)+1;
    sType[s.type]=(sType[s.type]||0)+1;
  }

  // P&L stats
  const won=tracked.filter(t=>t.result==='WON').length;
  const lost=tracked.filter(t=>t.result==='LOST').length;
  const voided=tracked.filter(t=>t.result==='VOID').length;
  const pending=tracked.filter(t=>!t.result).length;
  const decided=won+lost;
  const winRate=decided>0?(won/decided*100).toFixed(1)+'%':'—';
  const winClass=decided>0?(won/decided>=0.5?'green':'red'):'';

  const aList=tracked.filter(t=>t.stufe==='A');
  const aWon=aList.filter(t=>t.result==='WON').length;
  const aLost=aList.filter(t=>t.result==='LOST').length;
  const aDec=aWon+aLost;
  const aRate=aDec>0?(aWon/aDec*100).toFixed(1)+'%':'—';
  const aClass=aDec>0?(aWon/aDec>=0.5?'green':'red'):'';

  // Backend H2H stats
  let hz_mu='—',ft_mu='—',hz_n='—',ft_n='—',hz_avg='—',ft_avg='—',hz_min='—',hz_max='—',ft_min='—',ft_max='—';
  try{
    const st=await fetch('/api/stats').then(r=>r.json());
    hz_mu=st.hz_matchups??'—';ft_mu=st.ft_matchups??'—';
    hz_n=st.hz_games??'—';ft_n=st.ft_games??'—';
    hz_avg=st.hz_avg??'—';ft_avg=st.ft_avg??'—';
    hz_min=st.hz_min??'—';hz_max=st.hz_max??'—';
    ft_min=st.ft_min??'—';ft_max=st.ft_max??'—';
  }catch(e){}

  const _sb=(val,lbl,cls='')=>`<div class="stat-box"><div class="stat-box-val ${cls}">${val}</div><div class="stat-box-lbl">${lbl}</div></div>`;

  const trackedHtml=tracked.length===0
    ?'<div class="empty" style="font-size:10px;padding:12px;">Noch keine Signale verfolgt — werden automatisch beim Berechnen hinzugefügt</div>'
    :[...tracked].reverse().map(t=>`<div class="tracked-entry">
        <span style="color:var(--dim);min-width:38px;flex-shrink:0">${t.ts||''}</span>
        <span class="tracked-dir ${(t.dir||'').toLowerCase()}">${t.dir||'?'}</span>
        <span style="font-size:8px;color:var(--dim2);flex-shrink:0">ST-${t.stufe||'?'}</span>
        <span style="font-size:8px;color:var(--dim2);flex-shrink:0">${t.type||'HZ'}</span>
        ${t.buf!=null?`<span style="color:var(--text);flex-shrink:0">${t.buf>=0?'+':''}${(+t.buf).toFixed(1)}</span>`:''}
        <span style="color:var(--dim);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:8px">${t.ctx||''}</span>
        <div class="tracked-result-btns">
          <button class="result-btn ${t.result==='WON'?'won':''}" onclick="markResult('${t.id}','WON')">WON</button>
          <button class="result-btn ${t.result==='LOST'?'lost':''}" onclick="markResult('${t.id}','LOST')">LOST</button>
          <button class="result-btn ${t.result==='VOID'?'void':''}" onclick="markResult('${t.id}','VOID')">VOID</button>
        </div>
      </div>`).join('');

  body.innerHTML=`
    <div class="stats-section">
      <div class="stats-section-title">Session · Signale</div>
      <div class="stats-grid">
        ${_sb(session.length,'Gesamt')}
        ${_sb(sDir.UNDER||0,'UNDER','blue')}
        ${_sb(sDir.OVER||0,'OVER','red')}
        ${_sb(sStufe.A||0,'Stufe A','green')}
        ${_sb(sStufe.B||0,'Stufe B','gold')}
        ${_sb(sStufe.C||0,'Skip/C','')}
        ${_sb(sType.HZ||0,'HZ','')}
        ${_sb(sType.FT||0,'FT','')}
      </div>
    </div>

    <div class="stats-section">
      <div class="stats-section-title">P&L · Tracking (persistent)</div>
      <div class="stats-grid" style="margin-bottom:10px">
        ${_sb(tracked.length,'Verfolgt','')}
        ${_sb(won,'Gewonnen','green')}
        ${_sb(lost,'Verloren','red')}
        ${_sb(voided,'Void','')}
        ${_sb(pending,'Ausstehend','gold')}
        ${_sb(winRate,'Win-Rate',winClass)}
        ${_sb(aRate,'Win-Rate A',aClass)}
      </div>
      <div class="tracked-list">${trackedHtml}</div>
      ${tracked.length>0?`<div class="stats-action-row"><button class="stats-action-btn" onclick="clearTracked()">✕ Tracking leeren</button></div>`:''}
    </div>

    <div class="stats-section">
      <div class="stats-section-title">H2H Datenbank</div>
      <div class="stats-grid">
        ${_sb(hz_mu,'HZ Matchups','')}
        ${_sb(ft_mu,'FT Matchups','')}
        ${_sb(hz_n,'HZ Spiele','')}
        ${_sb(ft_n,'FT Spiele','')}
        ${_sb(hz_avg,'HZ Ø Total','gold')}
        ${_sb(ft_avg,'FT Ø Total','gold')}
        ${_sb(hz_min,'HZ Min','')}
        ${_sb(hz_max,'HZ Max','')}
        ${_sb(ft_min,'FT Min','')}
        ${_sb(ft_max,'FT Max','')}
      </div>
    </div>

    <div class="stats-section">
      <div class="stats-section-title">Backfill</div>
      <div class="backfill-row">
        <select class="bf-select" id="bfDays">
          <option value="7">7 Tage</option>
          <option value="14">14 Tage</option>
          <option value="21">21 Tage</option>
          <option value="28">28 Tage</option>
        </select>
        <input class="bf-input" type="number" id="bfOffset" value="0" min="0" max="180" placeholder="Offset" title="Wie viele Tage in der Vergangenheit überspringen (0 = heute)">
        <button class="stats-action-btn" id="bfStartBtn" onclick="startBackfill()">▶ Start Backfill</button>
      </div>
      <div class="backfill-progress" id="bfProgress"></div>
    </div>
  `;
}

// ── Backfill ──
async function startBackfill(){
  const days=parseInt(document.getElementById('bfDays')?.value)||7;
  const offset=parseInt(document.getElementById('bfOffset')?.value)||0;
  const prog=document.getElementById('bfProgress');
  const btn=document.getElementById('bfStartBtn');
  if(prog)prog.textContent=`Sende Anfrage… (${days} Tage, Offset ${offset})`;
  if(btn)btn.disabled=true;
  try{
    const r=await fetch(`/api/backfill?days=${days}&offset=${offset}`).then(res=>res.json());
    if(prog)prog.textContent=`✓ Backfill fertig — ${r.rows_written||0} Zeilen, ${r.hz_matchups||0} HZ Matchups`;
    // reload cache after backfill
    await fetch('/api/reload-cache');
    loadHealth();
  }catch(e){
    if(prog)prog.textContent=`✗ Fehler: ${e.message}`;
  }finally{
    if(btn)btn.disabled=false;
  }
}

// ── Startup ──
document.addEventListener('DOMContentLoaded',()=>{
  // open HZ manual form by default
  document.getElementById('manualHz').classList.add('open');
  document.getElementById('mToggleHz').classList.add('open');

  // wire live-calc listeners on all manual inputs
  ['hH2H','hLine','hQ1','hQ2','hTimer','hFouls','hFT','hFG'].forEach(id=>{
    document.getElementById(id).addEventListener('input',_liveHz);
  });
  document.getElementById('chkDrop').addEventListener('click',()=>setTimeout(_liveHz,50));
  document.getElementById('chkRise').addEventListener('click',()=>setTimeout(_liveHz,50));
  ['fH2H','fLine','fQ3H','fQ3A','fHZ','fFouls','fFTH','fFTA'].forEach(id=>{
    document.getElementById(id).addEventListener('input',_liveFt);
  });

  // health check first, then load live data
  loadHealth().then(()=>loadLive());
  // initialise toggle button states from saved preferences
  _updateNotifBtn();
  _updateSoundBtn();
});
</script>
</body>
</html>"""


# ─── API Helper ───────────────────────────────────────────────────────────────

_API_HEADERS = {
    "x-apisports-key":  API_KEY,
    "x-rapidapi-host":  "v1.basketball.api-sports.io",
}

async def api_get(endpoint: str, params: dict) -> dict:
    """Rate-limited GET against API-Sports — reuses the persistent httpx client."""
    client = _http_client or httpx.AsyncClient(timeout=API_TIMEOUT)
    sem    = _api_semaphore or asyncio.Semaphore(LIVE_API_CONCURRENCY)
    async with sem:
        r = await client.get(f"{API_BASE}/{endpoint}", headers=_API_HEADERS, params=params)
        r.raise_for_status()
        return r.json()


def _normalize_game(g: dict, league_id: int, league_name: str) -> dict:
    """Extract and normalise relevant fields from a raw API game object."""
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


# ─── Signal Engine (Python) ───────────────────────────────────────────────────
# Mirrors the JS hzEngine / ftEngine in the HTML exactly.
# Consumed by /api/signal/hz and /api/signal/ft — use these for the Telegram bot.

def _hz_engine(
    *,
    h2h:       Optional[float],
    line:      float,
    q1:        float,
    q2:        float,
    timer:     float,
    fouls:     int,
    ft_pct:    Optional[float],
    fg_pct:    Optional[float],
    line_drop: bool,
    line_rise: bool,
    is_ht:     bool = False,
) -> dict:
    # At HT: Q2 is fully played — use actual q2, bypass entry-time checks
    time_left = 0.0 if is_ht else max(0.0, 10.0 - timer)
    q2_proj   = q2 if is_ht else (q2 + (q2 / timer) * time_left if timer > 0.5 and q2 > 0 else q1)
    proj      = q1 + q2_proj
    buffer    = proj - line
    h2h_buf   = (h2h - line) if (h2h is not None and h2h > 0) else None

    fouls_oc     = fouls >= HZ_FOULS_THRESHOLD
    ft_oc        = ft_pct is not None and ft_pct >= HZ_FT_PCT_CATALYST
    line_mc      = line_drop or line_rise
    h2h_over_cat = h2h_buf is not None and h2h_buf <= HZ_H2H_OVER_BUFFER
    fg_skip      = fg_pct is not None and fg_pct > HZ_FG_SKIP
    entry_ok     = is_ht or time_left >= HZ_ENTRY_MIN
    entry_a      = is_ht or time_left >= HZ_ENTRY_OPTIMAL

    dir_    = "SKIP"
    stufe   = "C"
    reasons: list[str] = []

    if buffer >= HZ_BUFFER_UNDER and entry_ok and fouls < HZ_FOULS_THRESHOLD and not fg_skip:
        dir_ = "UNDER"
        if entry_a:
            if h2h_buf is not None and h2h_buf < HZ_H2H_UNDER_KONTRA:
                stufe = "B"
                reasons = [
                    f"Buffer +{buffer:.1f} >= {HZ_BUFFER_UNDER}",
                    f"H2H {h2h} < Linie -> kontra",
                ]
            else:
                stufe = "A"
                reasons = [f"Buffer +{buffer:.1f} >= {HZ_BUFFER_UNDER}"]
                if is_ht:
                    reasons.append("Halbzeit — Ergebnis steht")
                else:
                    reasons += [f"Entry {time_left:.1f}min", f"Fouls {fouls} < {HZ_FOULS_THRESHOLD}"]
                if h2h_buf is not None and h2h_buf >= HZ_H2H_CONFIRM_BUFFER:
                    reasons.append(f"H2H +{h2h_buf:.1f} bestaetigt")
        else:
            stufe = "B"
            reasons = [f"Buffer +{buffer:.1f}", f"Entry {time_left:.1f}min spaet"]

    elif buffer <= -HZ_BUFFER_OVER and entry_ok:
        dir_ = "OVER"
        if fouls_oc or ft_oc or line_mc or h2h_over_cat:
            stufe = "A"
            if fouls_oc:
                reasons.append(f"Fouls {fouls} >= {HZ_FOULS_THRESHOLD}")
            if ft_oc:
                reasons.append(f"FT% {ft_pct}%")
            if line_mc:
                reasons.append("Linie bewegt")
            if h2h_over_cat:
                reasons.append(f"H2H {h2h_buf:.1f} unter Linie")
        else:
            stufe = "B"
            reasons = [f"Buffer {buffer:.1f} unter Linie", "Kein Katalysator"]
        if is_ht:
            reasons.append("Halbzeit — Ergebnis steht")
        else:
            reasons.append(f"Entry {time_left:.1f}min")

    else:
        if fg_skip:
            reasons.append(f"FG% {fg_pct}% > {HZ_FG_SKIP} -> Skip")
        if not is_ht and not entry_ok:
            reasons.append(f"Entry {time_left:.1f}min < {HZ_ENTRY_MIN}")
        if abs(buffer) < HZ_BUFFER_OVER:
            reasons.append(f"Buffer {buffer:.1f} < {HZ_BUFFER_OVER}")
        if fouls >= HZ_FOULS_THRESHOLD and buffer > 0:
            reasons.append(f"Fouls >={HZ_FOULS_THRESHOLD} -> OVER pruefen")
        if not reasons:
            reasons.append("Kein Signal")

    return {
        "dir":       dir_,
        "stufe":     stufe,
        "type":      "HZ",
        "proj":      round(proj, 1),
        "buffer":    round(buffer, 1),
        "time_left": round(time_left, 1),
        "fouls":     fouls,
        "reasons":   reasons,
    }


def _ft_engine(
    *,
    h2h:      Optional[float],
    line:     float,
    q3h:      float,
    q3a:      float,
    hz:       float,
    fouls:    int,
    ft_pct_h: Optional[float],
    ft_pct_a: Optional[float],
) -> dict:
    q3_total = q3h + q3a
    current  = hz + q3_total
    gap      = abs(q3h - q3a)
    buffer   = current - line
    h2h_buf  = (h2h - line) if (h2h is not None and h2h > 0) else None
    ft_ok    = (
        ft_pct_h is not None and ft_pct_h >= FT_FT_PCT_THRESHOLD and
        ft_pct_a is not None and ft_pct_a >= FT_FT_PCT_THRESHOLD
    )

    dir_    = "SKIP"
    stufe   = "C"
    reasons: list[str] = []

    if gap > FT_GAP_MAX:
        reasons.append(f"Gap {gap} > {FT_GAP_MAX} -> Garbage Time Skip")
        return {
            "dir": dir_, "stufe": stufe, "type": "FT",
            "proj": current, "buffer": round(buffer, 1),
            "time_left": None, "fouls": fouls, "reasons": reasons,
        }

    if buffer >= FT_BUFFER_UNDER_A and ft_ok:
        dir_  = "UNDER"
        stufe = "A"
        reasons.append(f"Buffer +{buffer:.1f} >= {FT_BUFFER_UNDER_A}")
        reasons.append(f"FT% Heim {ft_pct_h}% / Gast {ft_pct_a}% >= {FT_FT_PCT_THRESHOLD}")
        if h2h_buf is not None and h2h_buf >= FT_H2H_CONFIRM_BUFFER:
            reasons.append(f"H2H +{h2h_buf:.1f} bestaetigt")

    elif buffer >= FT_BUFFER_UNDER_B:
        dir_  = "UNDER"
        stufe = "A" if ft_ok else "B"
        reasons.append(f"Buffer +{buffer:.1f} >= {FT_BUFFER_UNDER_B}")
        if not ft_ok:
            reasons.append(f"FT% unter {FT_FT_PCT_THRESHOLD} -> Stufe B")

    elif buffer <= -FT_BUFFER_OVER and ft_ok:
        dir_  = "OVER"
        stufe = "A"
        reasons.append(f"Buffer {buffer:.1f} <= -{FT_BUFFER_OVER}")
        reasons.append(f"FT% Heim {ft_pct_h}% / Gast {ft_pct_a}% >= {FT_FT_PCT_THRESHOLD}")
        if fouls >= FT_FOULS_CATALYST:
            reasons.append(f"Fouls {fouls} >= {FT_FOULS_CATALYST}")

    elif buffer <= -FT_BUFFER_OVER:
        dir_  = "OVER"
        stufe = "B"
        reasons.append(f"Buffer {buffer:.1f} <= -{FT_BUFFER_OVER}")
        reasons.append(f"FT% nicht erfuellt -> Stufe B")

    else:
        reasons.append(f"Buffer {buffer:.1f} — min +/-{FT_BUFFER_UNDER_A} fuer FT")

    return {
        "dir":       dir_,
        "stufe":     stufe,
        "type":      "FT",
        "proj":      current,
        "buffer":    round(buffer, 1),
        "time_left": None,
        "fouls":     fouls,
        "reasons":   reasons,
    }


# ─── Telegram Notifications ───────────────────────────────────────────────────

TELEGRAM_API_BASE = "https://api.telegram.org"


def _fmt_buf(buf: float) -> str:
    return f"+{buf:.1f}" if buf >= 0 else f"{buf:.1f}"


def _format_signal_msg(sig: dict, label: str = "") -> str:
    """Format a signal result dict into a readable Telegram HTML message."""
    dir_ = sig.get("dir", "?")
    if dir_ == "UNDER":
        emoji = "🔵"
    elif dir_ == "OVER":
        emoji = "🔴"
    else:
        emoji = "⚪"

    buf     = sig.get("buffer")
    buf_str = _fmt_buf(buf) if buf is not None else "—"
    proj    = sig.get("proj")
    fouls   = sig.get("fouls")

    lines: list[str] = [
        f"{emoji} <b>{dir_} · STUFE {sig.get('stufe','?')} · {sig.get('type','?')}</b>",
    ]
    if label:
        lines.append(label)
    lines.append(
        f"Proj: {proj if proj is not None else '—'} | Buffer: {buf_str}"
        + (f" | Fouls: {fouls}" if fouls is not None else "")
    )
    time_left = sig.get("time_left")
    if time_left is not None:
        lines.append(f"Zeit Q2: {time_left}min")

    reasons = sig.get("reasons") or []
    for r in reasons:
        lines.append(f"• {r}")

    return "\n".join(lines)


async def _send_telegram(text: str) -> bool:
    """
    Send a message via the Telegram Bot API.
    Returns True on success, False if not configured or on error.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url    = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        client = _http_client or httpx.AsyncClient(timeout=API_TIMEOUT)
        resp   = await client.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        })
        if not resp.is_success:
            log.warning("Telegram send failed: %s — %s", resp.status_code, resp.text[:200])
            return False
        log.info("📱 Telegram message sent")
        return True
    except Exception as e:
        log.warning("Telegram error: %s", e)
        return False

def _matchup_key(home: str, away: str) -> str:
    return "|".join(sorted([home.lower().strip(), away.lower().strip()]))


def _add_seen_ft_id(key: str) -> None:
    """Add a game key with FIFO eviction once SEEN_FT_IDS_MAX is reached."""
    if key in _seen_ft_ids:
        return
    _seen_ft_ids[key] = True
    if len(_seen_ft_ids) > SEEN_FT_IDS_MAX:
        _seen_ft_ids.popitem(last=False)  # remove oldest entry


def _set_stats_cache(game_id: int, value: tuple) -> None:
    """Write to _game_stats_cache with FIFO eviction at GAME_STATS_CACHE_MAX."""
    _game_stats_cache[game_id] = value
    if len(_game_stats_cache) > GAME_STATS_CACHE_MAX:
        _game_stats_cache.popitem(last=False)


def _reset_worksheet() -> None:
    """Force a fresh connection on next Sheets access."""
    global _ws
    _ws = None


def _get_worksheet():
    global _ws
    if _ws is not None:
        return _ws
    if not (SHEETS_ID and CREDS_JSON):
        return None
    try:
        import gspread
        gc = gspread.service_account_from_dict(json.loads(CREDS_JSON))
        sh = gc.open_by_key(SHEETS_ID)
        try:
            _ws = sh.worksheet(SHEETS_TAB)
            first_row = _ws.row_values(1)
            if first_row != SHEETS_HEADER:
                log.warning("⚠️  Sheet header mismatch — got: %s", first_row)
        except gspread.WorksheetNotFound:
            log.info("Creating new worksheet '%s'", SHEETS_TAB)
            _ws = sh.add_worksheet(title=SHEETS_TAB, rows=SHEETS_ROWS_INIT, cols=SHEETS_COLS_INIT)
            _ws.append_row(SHEETS_HEADER)
        log.info("✅ Google Sheets connected: %s", SHEETS_TAB)
        return _ws
    except Exception as e:
        log.warning("Sheets init failed: %s", e)
        _ws = None
        return None


def _load_h2h_from_sheet() -> None:
    """Load all H2H data from Sheet into memory. Replaces caches atomically."""
    global _h2h_cache, _ft_h2h_cache
    ws = _get_worksheet()
    if ws is None:
        return
    try:
        rows     = ws.get_all_records()
        h2h_new: dict        = {}
        ft_new:  dict        = {}
        seen_new: OrderedDict = OrderedDict()

        for row in rows:
            home     = str(row.get("home", "")).strip()
            away     = str(row.get("away", "")).strip()
            ht_total = row.get("ht_total")
            ft_total = row.get("ft_total")
            game_key = f"{row.get('date', '')}-{home}-{away}"

            seen_new[game_key] = True
            if len(seen_new) > SEEN_FT_IDS_MAX:
                seen_new.popitem(last=False)

            if not (home and away):
                continue
            key = _matchup_key(home, away)
            if ht_total:
                val = float(ht_total)
                if 0 < val <= H2H_HZ_MAX:
                    h2h_new.setdefault(key, []).append(val)
                else:
                    log.warning("Skipping corrupt ht_total=%.0f for %s vs %s", val, home, away)
            if ft_total:
                val = float(ft_total)
                if 0 < val <= H2H_FT_MAX:
                    ft_new.setdefault(key, []).append(val)
                else:
                    log.warning("Skipping corrupt ft_total=%.0f for %s vs %s", val, home, away)

        # Atomic replacement
        _h2h_cache    = h2h_new
        _ft_h2h_cache = ft_new
        _seen_ft_ids.clear()
        _seen_ft_ids.update(seen_new)
        log.info("✅ H2H cache loaded — HZ:%d matchups  FT:%d matchups  seen:%d games",
                 len(_h2h_cache), len(_ft_h2h_cache), len(_seen_ft_ids))
    except Exception as e:
        log.warning("H2H load failed: %s — resetting Sheets connection", e)
        _reset_worksheet()


# ─── FT Extraction (split into focused helpers) ───────────────────────────────

def _build_ft_row(g: dict, league_id: int, name: str, target: str) -> Optional[list]:
    """
    Parse one raw game object. Returns a Sheets row if it's a new FT game,
    None if already seen, incomplete, or not FT status.
    Also updates the in-memory H2H caches immediately.
    """
    if g.get("status", {}).get("short", "") != "FT":
        return None
    ng       = _normalize_game(g, league_id, name)
    home     = ng["home"]
    away     = ng["away"]
    ft_total = ng["total_home"] + ng["total_away"]
    if ft_total == 0:
        return None
    game_key = f"{target}-{home}-{away}"
    if game_key in _seen_ft_ids:
        return None

    _add_seen_ft_id(game_key)
    q2_total     = ng["q2_home"] + ng["q2_away"]
    ht_total_val = ng["q1_total"] + q2_total
    key = _matchup_key(home, away)
    if 0 < ht_total_val <= H2H_HZ_MAX:
        _h2h_cache.setdefault(key, []).append(float(ht_total_val))
    else:
        log.warning("Suspicious ht_total=%.0f for %s vs %s — not cached", ht_total_val, home, away)
    if 0 < ft_total <= H2H_FT_MAX:
        _ft_h2h_cache.setdefault(key, []).append(float(ft_total))
    else:
        log.warning("Suspicious ft_total=%.0f for %s vs %s — not cached", ft_total, home, away)

    return [target, home, away, ng["league_name"],
            ng["q1_total"], q2_total, ht_total_val, ft_total]


async def _fetch_ft_for_league(
    league_id: int, name: str, season: str, target: str
) -> list[list]:
    """Fetch and process FT games for a single league on one date."""
    try:
        data = await api_get("games", {"league": league_id, "season": season, "date": target})
        rows = []
        for g in (data.get("response") or []):
            row = _build_ft_row(g, league_id, name, target)
            if row:
                rows.append(row)
        return rows
    except Exception as e:
        log.debug("FT fetch failed — league:%s date:%s — %s", league_id, target, e)
        return []


async def _write_rows_to_sheet(rows: list[list]) -> None:
    """Append rows to Google Sheet; resets connection on any write failure."""
    ws = await asyncio.to_thread(_get_worksheet)
    if not ws:
        return
    try:
        await asyncio.to_thread(ws.append_rows, rows, value_input_option="RAW")
        log.info("✅ Wrote %d rows to Sheet", len(rows))
    except Exception as e:
        log.warning("Sheets write failed: %s — resetting connection", e)
        _reset_worksheet()


async def _extract_ft_games(date_str: Optional[str] = None) -> int:
    """
    Fetch FT games across all leagues for one date, write new rows to Sheet.
    All league fetches run concurrently (bounded by _api_semaphore).
    Returns number of new rows written.
    """
    if not API_KEY:
        return 0
    target = date_str or _date.today().isoformat()
    log.info("Extracting FT games for %s …", target)

    tasks   = [_fetch_ft_for_league(lid, name, season, target)
               for lid, (name, season) in LEAGUES.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    new_rows: list[list] = []
    for r in results:
        if isinstance(r, list):
            new_rows.extend(r)

    if new_rows:
        await _write_rows_to_sheet(new_rows)

    log.info("FT extract done — %s: %d new rows", target, len(new_rows))
    return len(new_rows)


# ─── Background Scheduler ─────────────────────────────────────────────────────

async def _scheduler_loop() -> None:
    try:
        await asyncio.to_thread(_load_h2h_from_sheet)
    except Exception as e:
        log.warning("Initial H2H load failed: %s", e)
    while True:
        try:
            await _extract_ft_games()
        except Exception as e:
            log.warning("Scheduler error: %s", e)
        await asyncio.sleep(SCHEDULER_INTERVAL)


# ─── Automated Signal Scan ────────────────────────────────────────────────────

async def _auto_signal_for_game(g: dict, sig_type: str) -> Optional[dict]:
    """
    Compute a signal for a live game using the H2H average as the reference line.

    Returns a signal dict (same shape as _hz_engine / _ft_engine output) or None
    when there is insufficient H2H data or the game data is incomplete.
    """
    home = g["home"]
    away = g["away"]
    key  = _matchup_key(home, away)

    if sig_type == "hz":
        vals = _h2h_cache.get(key, [])
        if len(vals) < H2H_MIN_SAMPLES:
            return None
        line = round(sum(vals) / len(vals), 1)

        stats   = await get_game_stats(g["id"])
        fouls   = stats.get("total_fouls", 0) if stats.get("found") else 0
        ft_pct  = stats.get("avg_ft_pct")     if stats.get("found") else None
        fg_pct  = stats.get("avg_fg_pct")     if stats.get("found") else None
        is_ht   = g.get("status") == "HT"
        timer   = float(g.get("timer") or 0)

        return _hz_engine(
            h2h=line, line=line,
            q1=float(g.get("q1_total", 0)),
            q2=float(g.get("q2_live", 0)),
            timer=timer, fouls=fouls, ft_pct=ft_pct, fg_pct=fg_pct,
            line_drop=False, line_rise=False, is_ht=is_ht,
        )

    else:  # ft
        vals = _ft_h2h_cache.get(key, [])
        if len(vals) < H2H_MIN_SAMPLES:
            return None
        line = round(sum(vals) / len(vals), 1)

        stats      = await get_game_stats(g["id"])
        fouls      = stats.get("total_fouls", 0) if stats.get("found") else 0
        home_ft    = stats.get("home_ft_pct")    if stats.get("found") else None
        away_ft    = stats.get("away_ft_pct")    if stats.get("found") else None

        return _ft_engine(
            h2h=line, line=line,
            q3h=float(g.get("q3_home", 0)),
            q3a=float(g.get("q3_away", 0)),
            hz=float(g.get("ht_total", 0)),
            fouls=fouls, ft_pct_h=home_ft, ft_pct_a=away_ft,
        )


async def _auto_scan_once() -> int:
    """
    One auto-scan cycle: compute signals for all live HZ / Q3BT games.

    For each game the H2H average from the cache is used as the reference line.
    Only Stufe-A (or the configured AUTO_SCAN_STUFE) signals are sent via Telegram
    and each game is rate-limited to one notification per AUTO_SENT_TTL seconds.

    Returns the number of Telegram messages successfully sent.
    """
    if not API_KEY:
        return 0

    now = time()

    results = await asyncio.gather(
        *[_fetch_live_for_league(lid, name, season)
          for lid, (name, season) in LEAGUES.items()],
        return_exceptions=True,
    )

    hz_games: list = []
    q3_games: list = []
    seen_ids: set  = set()
    for r in results:
        if not isinstance(r, tuple):
            continue
        hz, q3, _ = r
        for g in hz:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                hz_games.append(g)
        for g in q3:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                q3_games.append(g)

    sent_count = 0

    for g, sig_type in [(g, "hz") for g in hz_games] + [(g, "ft") for g in q3_games]:
        dedup_key = (g["id"], sig_type)
        if now - _auto_sent.get(dedup_key, 0) < AUTO_SENT_TTL:
            continue

        try:
            sig = await _auto_signal_for_game(g, sig_type)
        except Exception as e:
            log.debug("auto-signal %s %s vs %s: %s", sig_type, g["home"], g["away"], e)
            continue

        if sig is None or sig["dir"] == "SKIP":
            continue
        if AUTO_SCAN_STUFE == "A" and sig["stufe"] != "A":
            continue

        league = g.get("league_name", "")
        status = g.get("status", "HT") if sig_type == "hz" else "Q3 Break"
        label  = f"🏀 {g['home']} vs {g['away']} ({league}) · {status}"
        sig_with_note = {
            **sig,
            "reasons": list(sig.get("reasons", [])) + ["Auto-Scan · H2H als Referenzlinie"],
        }
        msg = _format_signal_msg(sig_with_note, label)
        ok  = await _send_telegram(msg)
        if ok:
            _auto_sent[dedup_key] = now
            sent_count += 1
            log.info(
                "🤖 Auto-signal: %s vs %s — %s ST-%s (%s)",
                g["home"], g["away"], sig["dir"], sig["stufe"], sig_type.upper(),
            )

    return sent_count


async def _auto_scan_loop() -> None:
    """
    Background loop that repeatedly calls _auto_scan_once() every AUTO_SCAN_INTERVAL seconds.
    Disabled when API_SPORTS_KEY is not set.
    """
    if not API_KEY:
        log.info("🤖 Auto-scan disabled (no API_SPORTS_KEY)")
        return
    log.info(
        "🤖 Auto-scan loop started — interval: %ds, min_stufe: %s, h2h_min: %d",
        AUTO_SCAN_INTERVAL, AUTO_SCAN_STUFE, H2H_MIN_SAMPLES,
    )
    while True:
        try:
            sent = await _auto_scan_once()
            if sent:
                log.info("🤖 Auto-scan cycle — %d signal(s) sent", sent)
            else:
                log.debug("🤖 Auto-scan cycle — no signals")
        except Exception as e:
            log.warning("Auto-scan loop error: %s", e)
        await asyncio.sleep(AUTO_SCAN_INTERVAL)


# ─── Live Games Helpers ───────────────────────────────────────────────────────

async def _fetch_live_for_league(
    league_id: int, name: str, season: str,
) -> tuple[list, list, list]:
    """
    Fetch all live games for one league.
    Returns (hz_games, q3bt_games, other_live_games).
    """
    hz, q3, others = [], [], []
    try:
        data = await api_get("games", {"league": league_id, "season": season, "live": "all"})
        for g in (data.get("response") or []):
            status = g.get("status", {}).get("short", "")
            ng     = _normalize_game(g, league_id, name)
            if status in ("HT", "Q2"):
                hz.append(ng)
            elif status == "Q3BT" or (
                # Some leagues return generic "BT" for all quarter breaks;
                # distinguish Q3 break from Q1 break by checking if Q3 has scores
                status == "BT" and (ng.get("q3_home", 0) > 0 or ng.get("q3_away", 0) > 0)
            ):
                q3.append(ng)
            else:
                others.append(ng)
    except Exception as e:
        log.debug("Live fetch failed — league:%s — %s", league_id, e)
    return hz, q3, others


async def _fetch_today_for_league(
    league_id: int, name: str, season: str,
    today_str: str, already_seen: set,
) -> list:
    """Fetch today's scheduled games, skipping IDs already returned by live endpoint."""
    try:
        data = await api_get("games", {"league": league_id, "season": season, "date": today_str})
        results = []
        for g in (data.get("response") or []):
            gid = g.get("id")
            if gid not in already_seen:
                already_seen.add(gid)
                results.append(_normalize_game(g, league_id, name))
        return results
    except Exception as e:
        log.debug("Today fetch failed — league:%s — %s", league_id, e)
        return []


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML


@app.get("/api/health")
async def health():
    return {
        "status":              "ok",
        "api_key_set":         bool(API_KEY),
        "sheets_configured":   bool(SHEETS_ID and CREDS_JSON),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "hz_matchups":         len(_h2h_cache),
        "ft_matchups":         len(_ft_h2h_cache),
        "seen_ft_ids":         len(_seen_ft_ids),
    }


@app.get("/api/stats")
async def get_stats():
    """
    Aggregated statistics for the H2H cache and system status.
    Used by the frontend Statistics panel.
    """
    hz_vals = [v for vals in _h2h_cache.values() for v in vals]
    ft_vals = [v for vals in _ft_h2h_cache.values() for v in vals]
    return {
        "hz_matchups":         len(_h2h_cache),
        "ft_matchups":         len(_ft_h2h_cache),
        "hz_games":            len(hz_vals),
        "ft_games":            len(ft_vals),
        "hz_avg":              round(sum(hz_vals) / len(hz_vals), 1) if hz_vals else None,
        "ft_avg":              round(sum(ft_vals) / len(ft_vals), 1) if ft_vals else None,
        "hz_min":              round(min(hz_vals), 1) if hz_vals else None,
        "hz_max":              round(max(hz_vals), 1) if hz_vals else None,
        "ft_min":              round(min(ft_vals), 1) if ft_vals else None,
        "ft_max":              round(max(ft_vals), 1) if ft_vals else None,
        "api_key_set":         bool(API_KEY),
        "sheets_configured":   bool(SHEETS_ID and CREDS_JSON),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
    }


@app.get("/api/leagues")
async def get_leagues():
    return {
        "leagues": [
            {"id": k, "name": v[0], "season": v[1]}
            for k, v in LEAGUES.items()
        ]
    }


@app.get("/api/live")
async def get_live_games():
    if not API_KEY:
        return {
            "games":  [],
            "today":  [],
            "q3":     [],
            "source": "no_key",
            "count":  0,
        }

    today_str = _date.today().isoformat()

    # Phase 1 — all live games concurrently (semaphore-limited)
    live_results = await asyncio.gather(
        *[_fetch_live_for_league(lid, name, season)
          for lid, (name, season) in LEAGUES.items()],
        return_exceptions=True,
    )

    live_hz:    list = []
    live_q3:    list = []
    live_other: list = []
    seen_ids:   set  = set()

    for r in live_results:
        if not isinstance(r, tuple):
            continue
        hz, q3, others = r
        for g in hz:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                live_hz.append(g)
        for g in q3:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                live_q3.append(g)
        for g in others:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                live_other.append(g)

    # Phase 2 — today's schedule (fills in NS/FT games not in live feed)
    today_results = await asyncio.gather(
        *[_fetch_today_for_league(lid, name, season, today_str, seen_ids)
          for lid, (name, season) in LEAGUES.items()],
        return_exceptions=True,
    )

    today_all: list = list(live_other)
    for r in today_results:
        if isinstance(r, list):
            today_all.extend(r)

    log.info("Live poll done — HZ:%d  Q3BT:%d  other:%d  today:%d",
             len(live_hz), len(live_q3), len(live_other), len(today_all))

    return {
        "games":  live_hz,
        "q3":     live_q3,
        "other":  live_other,
        "today":  today_all[:TODAY_GAMES_LIMIT],
        "source": "live",
        "count":  len(live_hz),
    }


@app.get("/api/h2h")
async def get_h2h(home: str, away: str, type: str = "hz"):
    key   = _matchup_key(home, away)
    cache = _ft_h2h_cache if type == "ft" else _h2h_cache
    vals  = cache.get(key, [])
    avg   = round(sum(vals) / len(vals), 1) if vals else None
    return {"avg": avg, "count": len(vals), "found": avg is not None, "type": type}


def _safe_pct(val) -> Optional[float]:
    """Convert percentage value to float — API-Sports returns strings like '43.8' or None."""
    if val is None or val == "" or val == "0":
        return None
    try:
        f = float(val)
        return round(f, 1) if f > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_team_stats(t: dict) -> dict:
    """
    Extract fouls and shooting percentages from one team's statistics block.

    API-Sports basketball stats response structure:
      t = {
        "team": {"id": 1, "name": "..."},
        "statistics": [          <-- nested array, we take index 0
          {
            "field_goals":       {"made": 35, "attempts": 80, "percentage": "43.8"},
            "freethrows_goals":  {"made": 14, "attempts": 18, "percentage": "77.8"},
            "personal_fouls":    18,
            ...
          }
        ]
      }
    """
    # Drill into the nested statistics array
    stats_list = t.get("statistics") or []
    s  = stats_list[0] if stats_list else {}
    fg = s.get("field_goals") or {}
    ft = s.get("freethrows_goals") or {}

    return {
        "team_id":   t.get("team", {}).get("id"),
        "team_name": t.get("team", {}).get("name", ""),
        "fouls":     s.get("personal_fouls") or 0,
        "ft_pct":    _safe_pct(ft.get("percentage")),
        "ft_made":   ft.get("total") or ft.get("made") or 0,
        "ft_att":    ft.get("attempts") or 0,
        "fg_pct":    _safe_pct(fg.get("percentage")),
    }


@app.get("/api/game-stats/{game_id}")
async def get_game_stats(game_id: int):
    """
    Live stats for a game: fouls, FT%, FG% per team.
    Response is cached for GAME_STATS_CACHE_TTL seconds — safe to call on every card click.
    """
    cached = _game_stats_cache.get(game_id)
    if cached and (time() - cached[0]) < GAME_STATS_CACHE_TTL:
        log.debug("game-stats cache hit — id:%s", game_id)
        return cached[1]

    if not API_KEY:
        return {"found": False}

    try:
        data  = await api_get("games/statistics", {"id": game_id})
        teams = data.get("response") or []
        if not teams:
            result = {"found": False}
            _set_stats_cache(game_id, (time(), result))
            return result

        parsed      = [_parse_team_stats(t) for t in teams]
        total_fouls = sum(p["fouls"] for p in parsed)
        ft_pcts     = [p["ft_pct"] for p in parsed if p["ft_pct"] is not None]
        fg_pcts     = [p["fg_pct"] for p in parsed if p["fg_pct"] is not None]

        result = {
            "found":       True,
            "teams":       parsed,
            "total_fouls": total_fouls,
            "avg_ft_pct":  round(sum(ft_pcts) / len(ft_pcts), 1) if ft_pcts else None,
            "avg_fg_pct":  round(sum(fg_pcts) / len(fg_pcts), 1) if fg_pcts else None,
            "home_ft_pct": parsed[0]["ft_pct"] if len(parsed) > 0 else None,
            "away_ft_pct": parsed[1]["ft_pct"] if len(parsed) > 1 else None,
        }
        _game_stats_cache[game_id] = (time(), result)
        log.debug("game-stats fetched — id:%s  fouls:%s", game_id, total_fouls)
        return result

    except Exception as e:
        log.warning("game-stats %s: %s", game_id, e)
        return {"found": False, "error": str(e)}


@app.get("/api/signal/hz")
async def signal_hz(
    line:      float           = Query(...,  description="Bookie HZ line"),
    q1:        float           = Query(0,    description="Q1 total points"),
    q2:        float           = Query(0,    description="Q2 current points"),
    timer:     float           = Query(0,    description="Q2 time elapsed (minutes)"),
    fouls:     int             = Query(0,    description="Total fouls both teams"),
    h2h:       Optional[float] = Query(None, description="H2H average HZ total"),
    ft_pct:    Optional[float] = Query(None, description="Average FT% both teams"),
    fg_pct:    Optional[float] = Query(None, description="Average FG% both teams"),
    line_drop: bool            = Query(False, description="Line dropped >=8 points"),
    line_rise: bool            = Query(False, description="Line is rising"),
    is_ht:     bool            = Query(False, description="Game is at halftime (Q2 complete)"),
):
    """
    HZ Signal Engine as a JSON API.
    Example: /api/signal/hz?line=91.5&q1=52&q2=28&timer=4&fouls=5
    At halftime: add &is_ht=true — uses actual q2 total, bypasses entry-time gate.
    Returns: dir (UNDER/OVER/SKIP), stufe (A/B/C), proj, buffer, time_left, reasons[]
    """
    return _hz_engine(
        h2h=h2h, line=line, q1=q1, q2=q2, timer=timer,
        fouls=fouls, ft_pct=ft_pct, fg_pct=fg_pct,
        line_drop=line_drop, line_rise=line_rise, is_ht=is_ht,
    )


@app.get("/api/signal/ft")
async def signal_ft(
    line:     float           = Query(...,  description="Bookie FT line"),
    q3h:      float           = Query(0,    description="Q3 home score"),
    q3a:      float           = Query(0,    description="Q3 away score"),
    hz:       float           = Query(0,    description="HZ total"),
    fouls:    int             = Query(0,    description="Total fouls both teams"),
    h2h:      Optional[float] = Query(None, description="H2H average FT total"),
    ft_pct_h: Optional[float] = Query(None, description="Home team FT%"),
    ft_pct_a: Optional[float] = Query(None, description="Away team FT%"),
):
    """
    FT Signal Engine as a JSON API.
    Example: /api/signal/ft?line=182.5&hz=90&q3h=25&q3a=22&ft_pct_h=78&ft_pct_a=75
    Returns: dir (UNDER/OVER/SKIP), stufe (A/B/C), proj, buffer, reasons[]
    """
    return _ft_engine(
        h2h=h2h, line=line, q3h=q3h, q3a=q3a,
        hz=hz, fouls=fouls, ft_pct_h=ft_pct_h, ft_pct_a=ft_pct_a,
    )


# ─── Telegram Endpoints ───────────────────────────────────────────────────────

@app.get("/api/telegram/test")
async def telegram_test():
    """
    Send a test message to the configured Telegram chat.
    Use this to verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are correct.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(
            status_code=400,
            detail="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured",
        )
    ok = await _send_telegram("🏀 <b>HZ/FT Trading — Telegram OK!</b>\nBenachrichtigungen sind aktiv.")
    if not ok:
        raise HTTPException(status_code=502, detail="Telegram API call failed — check token and chat_id")
    return {"sent": True, "chat_id": TELEGRAM_CHAT_ID}


@app.post("/api/telegram/push")
async def telegram_push(payload: dict = Body(...)):
    """
    Push a pre-computed signal to Telegram.
    Called by the frontend after calculating a Stufe-A signal.

    Expected payload fields (same shape as _hz_engine / _ft_engine output):
      dir, stufe, type, proj, buffer, time_left, fouls, reasons — plus optional 'label' (game context).
    """
    dir_ = payload.get("dir", "SKIP")
    if dir_ == "SKIP":
        return {"sent": False, "reason": "skip_signal"}
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"sent": False, "reason": "telegram_not_configured"}
    label = payload.get("label", "")
    msg   = _format_signal_msg(payload, label)
    ok    = await _send_telegram(msg)
    return {"sent": ok}


@app.get("/api/live-scan")
async def live_scan():
    """
    Scan all live HZ/Q3BT games and send a Telegram summary when games are found.
    Call this from an external cron job (e.g. every 2–5 minutes) to receive
    automatic alerts whenever games enter the halftime or Q3 break window.

    No bookie lines required — this is a 'games need attention' notification.
    Returns the list of live games found regardless of Telegram config.
    """
    if not API_KEY:
        return {"hz": [], "q3": [], "count": 0, "telegram_sent": False, "source": "no_api_key"}

    results = await asyncio.gather(
        *[_fetch_live_for_league(lid, name, season)
          for lid, (name, season) in LEAGUES.items()],
        return_exceptions=True,
    )

    hz_games: list = []
    q3_games: list = []
    seen_ids: set  = set()

    for r in results:
        if not isinstance(r, tuple):
            continue
        hz, q3, _ = r
        for g in hz:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                hz_games.append(g)
        for g in q3:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                q3_games.append(g)

    sent = False
    if (hz_games or q3_games) and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        lines: list[str] = ["🏀 <b>Live Scan — Signal-Fenster offen</b>"]
        if hz_games:
            lines.append("\n<b>HZ · Halbzeit / Q2:</b>")
            for g in hz_games:
                status = g.get("status", "?")
                pts    = g.get("ht_total", 0) or g.get("q2_live", 0)
                timer  = g.get("timer")
                t_str  = f" · Q2 {timer}min" if (status == "Q2" and timer) else f" · {status}"
                lines.append(f"• {g['home']} vs {g['away']} ({g['league_name']}){t_str} — {pts}pts live")
        if q3_games:
            lines.append("\n<b>FT · Q3 Break:</b>")
            for g in q3_games:
                pts = g.get("ht_total", 0) + g.get("q3_home", 0) + g.get("q3_away", 0)
                lines.append(f"• {g['home']} vs {g['away']} ({g['league_name']}) — {pts}pts")
        lines.append("\nJetzt App öffnen → Signal berechnen!")
        sent = await _send_telegram("\n".join(lines))

    log.info("Live scan — HZ:%d  Q3:%d  telegram_sent:%s", len(hz_games), len(q3_games), sent)
    return {
        "hz":            hz_games,
        "q3":            q3_games,
        "count":         len(hz_games) + len(q3_games),
        "telegram_sent": sent,
        "source":        "live",
    }


@app.get("/api/auto-scan")
async def auto_scan_trigger():
    """
    Manually trigger one auto-scan cycle and return the results.

    The background loop runs automatically every AUTO_SCAN_INTERVAL seconds.
    Use this endpoint to trigger an immediate scan, check the current config,
    or verify that Telegram delivery is working.
    """
    sent = await _auto_scan_once()
    return {
        "sent":          sent,
        "interval_s":    AUTO_SCAN_INTERVAL,
        "min_stufe":     AUTO_SCAN_STUFE,
        "h2h_min":       H2H_MIN_SAMPLES,
        "dedup_entries": len(_auto_sent),
        "hz_matchups":   len(_h2h_cache),
        "ft_matchups":   len(_ft_h2h_cache),
    }


@app.get("/api/backfill")
async def backfill(
    days:   int = Query(default=7, ge=1, le=BACKFILL_MAX_DAYS),
    offset: int = Query(default=0, ge=0, le=180),
):
    """
    Backfill Google Sheet with historical FT data.
    Keep batches <=7 days to stay within Render Free 512 MB RAM.

    Recommended sequence (in separate requests):
      /api/backfill?days=7&offset=0    → 1–7 days ago
      /api/backfill?days=7&offset=7    → 8–14 days ago
      /api/backfill?days=7&offset=14   → 15–21 days ago
    """
    if not API_KEY:
        raise HTTPException(status_code=400, detail="API_SPORTS_KEY not set")

    today = _date.today()
    total = 0
    log.info("🔄 Backfill started — days:%d offset:%d", days, offset)

    for i in range(1 + offset, days + offset + 1):
        target = (today - timedelta(days=i)).isoformat()
        try:
            written  = await _extract_ft_games(target)
            total   += written
        except Exception as e:
            log.warning("Backfill %s: %s", target, e)
        await asyncio.sleep(BACKFILL_SLEEP)

    await asyncio.to_thread(_load_h2h_from_sheet)
    log.info("✅ Backfill complete — %d rows written", total)
    return {
        "status":         "done",
        "days_processed": days,
        "offset":         offset,
        "range":          f"{offset + 1}–{offset + days} days ago",
        "rows_written":   total,
        "hz_matchups":    len(_h2h_cache),
        "ft_matchups":    len(_ft_h2h_cache),
    }


@app.get("/api/trigger-extract")
async def trigger_extract():
    written = await _extract_ft_games()
    await asyncio.to_thread(_load_h2h_from_sheet)
    return {
        "status":       "ok",
        "rows_written": written,
        "hz_matchups":  len(_h2h_cache),
        "ft_matchups":  len(_ft_h2h_cache),
    }


@app.get("/api/reload-cache")
async def reload_cache():
    """Force reload H2H cache from Google Sheet. Call after backfill if matchups show 0."""
    _reset_worksheet()
    await asyncio.to_thread(_load_h2h_from_sheet)
    return {
        "status":      "ok",
        "hz_matchups": len(_h2h_cache),
        "ft_matchups": len(_ft_h2h_cache),
    }


@app.get("/api/odds")
async def get_odds(home: str = Query(...), away: str = Query(...)):
    """
    Fetch the current totals line from TheOddsAPI for a given matchup.
    Requires ODDS_API_KEY env var. Returns {"found": false} when key is absent or no match.
    """
    if not ODDS_API_KEY:
        return {"found": False, "reason": "ODDS_API_KEY not set"}

    home_n = home.lower().strip()
    away_n = away.lower().strip()

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            resp = await client.get(
                f"{ODDS_API_BASE}/sports/basketball_euroleague/odds/",
                params={
                    "apiKey":   ODDS_API_KEY,
                    "regions":  "eu",
                    "markets":  "totals",
                    "oddsFormat": "decimal",
                },
            )
            resp.raise_for_status()
            events = resp.json()

        for ev in events:
            h = (ev.get("home_team") or "").lower()
            a = (ev.get("away_team") or "").lower()
            home_match = home_n in h or h in home_n
            away_match = away_n in a or a in away_n
            if home_match and away_match:
                for bm in (ev.get("bookmakers") or []):
                    for mkt in (bm.get("markets") or []):
                        if mkt.get("key") == "totals":
                            for out in (mkt.get("outcomes") or []):
                                if (out.get("name") or "").lower() == "over":
                                    point = out.get("point")
                                    if point is not None:
                                        return {
                                            "found": True,
                                            "line":  float(point),
                                            "bookmaker": bm.get("title", ""),
                                        }
        return {"found": False, "reason": "no matching game"}
    except Exception as e:
        log.warning("TheOddsAPI error: %s", e)
        return {"found": False, "reason": str(e)}


@app.get("/api/debug-stats/{game_id}")
async def debug_stats(game_id: int):
    """
    Return the raw API-Sports statistics response for a game.
    Use this to inspect the exact response structure if stats are not parsing correctly.
    Example: /api/debug-stats/12345
    """
    if not API_KEY:
        return {"error": "API_SPORTS_KEY not set"}
    try:
        data = await api_get("games/statistics", {"id": game_id})
        teams = data.get("response") or []
        return {
            "game_id":      game_id,
            "teams_count":  len(teams),
            "raw_response": teams,
            # Show what _parse_team_stats would extract for each team
            "parsed":       [_parse_team_stats(t) for t in teams] if teams else [],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/debug-sheets")
async def debug_sheets():
    """Diagnose Sheets connection — shows all tabs, row count, first 3 rows."""
    if not (SHEETS_ID and CREDS_JSON):
        return {"error": "SHEETS_ID or CREDS_JSON not configured"}
    try:
        import gspread
        gc       = gspread.service_account_from_dict(json.loads(CREDS_JSON))
        sh       = gc.open_by_key(SHEETS_ID)
        all_tabs = [ws.title for ws in sh.worksheets()]
        try:
            ws   = sh.worksheet(SHEETS_TAB)
            rows = ws.get_all_records()
            return {
                "status":      "ok",
                "all_tabs":    all_tabs,
                "target_tab":  SHEETS_TAB,
                "total_rows":  len(rows),
                "first_3_rows": rows[:3],
            }
        except Exception as e:
            return {
                "status":     "tab_error",
                "all_tabs":   all_tabs,
                "target_tab": SHEETS_TAB,
                "error":      str(e),
            }
    except Exception as e:
        return {"status": "connection_error", "error": str(e)}


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        _port = int(os.environ.get("PORT", "10000"))
    except ValueError:
        log.error("PORT environment variable must be a valid integer; defaulting to 10000")
        _port = 10000
    uvicorn.run("app:app", host="0.0.0.0", port=_port, log_level="info")
