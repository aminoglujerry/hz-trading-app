from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from typing import Optional

app = FastAPI(title="HZ Trading App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_SPORTS_KEY", "")
API_BASE = "https://v1.basketball.api-sports.io"

# Priority leagues: id -> (name, season)
LEAGUES = {
    120: ("BSL / TBL",    "2025-2026"),
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
}

async def api_get(endpoint: str, params: dict) -> dict:
    headers = {
        "x-apisports-key": API_KEY,
        "x-rapidapi-host": "v1.basketball.api-sports.io",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{API_BASE}/{endpoint}", headers=headers, params=params)
        r.raise_for_status()
        return r.json()

# ── ENDPOINTS ──

@app.get("/api/live")
async def get_live_games():
    """Fetch all HT + Q2 games from priority leagues."""
    if not API_KEY:
        # Return demo data if no key
        return {"games": _demo_games(), "source": "demo"}

    results = []
    seen_ids = set()

    for league_id, (name, season) in LEAGUES.items():
        try:
            data = await api_get("games", {
                "league": league_id,
                "season": season,
                "live": "all"
            })
            for g in (data.get("response") or []):
                gid = g.get("id")
                if gid in seen_ids:
                    continue
                status = g.get("status", {}).get("short", "")
                if status in ("HT", "Q2", "Q3", "Q4"):  # include Q2 too
                    seen_ids.add(gid)
                    results.append(_normalize_game(g, league_id, name))
        except Exception:
            continue

    return {"games": results, "source": "live", "count": len(results)}


@app.get("/api/games")
async def get_games(league: int, season: str = "2025-2026", date: Optional[str] = None):
    """Generic games fetch — for H2H history lookup."""
    if not API_KEY:
        return {"response": [], "error": "No API key configured"}
    params = {"league": league, "season": season}
    if date:
        params["date"] = date
    try:
        return await api_get("games", params)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/leagues")
async def get_leagues():
    return {"leagues": [
        {"id": k, "name": v[0], "season": v[1]}
        for k, v in LEAGUES.items()
    ]}


@app.get("/api/health")
async def health():
    return {"status": "ok", "api_key_set": bool(API_KEY)}


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
        {
            "id": 1001, "league_id": 4, "league_name": "ACB",
            "status": "HT", "timer": None,
            "home": "Real Madrid", "away": "FC Barcelona",
            "q1_home": 28, "q1_away": 24,
            "q2_home": 0, "q2_away": 0,
            "total_home": 28, "total_away": 24,
            "q1_total": 52, "q2_live": 0, "ht_total": 52,
        },
        {
            "id": 1002, "league_id": 120, "league_name": "TBL",
            "status": "Q2", "timer": 5,
            "home": "Fenerbahce", "away": "Galatasaray",
            "q1_home": 31, "q1_away": 27,
            "q2_home": 18, "q2_away": 14,
            "total_home": 49, "total_away": 41,
            "q1_total": 58, "q2_live": 32, "ht_total": 90,
        },
        {
            "id": 1003, "league_id": 6, "league_name": "ABA Liga",
            "status": "HT", "timer": None,
            "home": "Crvena zvezda", "away": "Partizan",
            "q1_home": 22, "q1_away": 26,
            "q2_home": 0, "q2_away": 0,
            "total_home": 22, "total_away": 26,
            "q1_total": 48, "q2_live": 0, "ht_total": 48,
        },
    ]


# Serve frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html") as f:
        return f.read()
