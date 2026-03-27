# HZ Trading App

Basketball Halftime Trading Signal Engine — deployable on Render.

## Stack
- **Backend**: FastAPI + httpx (Python)
- **Frontend**: Vanilla HTML/CSS/JS (served as static)
- **Data**: API-Sports Basketball v1

## Local Development
```bash
pip install -r requirements.txt
API_SPORTS_KEY=your_key uvicorn app:app --reload
```
Open: http://localhost:8000

## Deploy on Render

1. Push this folder to GitHub
2. Render → New Web Service → connect repo
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. **Environment Variable**: `API_SPORTS_KEY` = your key

## Features
- Live HT/Q2 game loader (10 priority leagues)
- Signal Engine: UNDER/OVER/SKIP mit Stufe A/B/C
- Regeln: Buffer, Fouls, FT%, FG%, Linien-Bewegung
- Over-Bet Zähler (Stufe B bis 20)
- Einsatz-Kalkulator (Fix < 100€ Bankroll / % darüber)
- Trade Log mit Win/Loss Tracking
- Demo-Modus wenn kein API Key gesetzt

## Signal Logic
- **UNDER**: Projektion ≥ 5 Pts über Line, Fouls < 8, Entry 3:30–2:30, FG% ≤ 60
- **OVER**: Projektion ≥ 3 Pts unter Line, Katalysator (Fouls ≥ 8, FT% ≥ 85, Linie bewegt)
- **Stufe A**: 5€ / 5% — klares Signal, Entry ≥ 3:30
- **Stufe B**: 2.5€ / 2.5% — mittleres Signal, OVER bis 20 Bets
- **Stufe C**: SKIP

## Leagues (Priority)
| ID  | Liga        | Season    |
|-----|-------------|-----------|
| 120 | TBL / BSL   | 2025-2026 |
| 4   | ACB         | 2025-2026 |
| 6   | ABA Liga    | 2025-2026 |
| 23  | LNB Pro A   | 2025-2026 |
| 8   | Lega A      | 2025-2026 |
| 3   | EuroLeague  | 2025-2026 |
| 2   | EuroCup     | 2025-2026 |
| 15  | BBL         | 2025-2026 |
| 11  | GBL         | 2025-2026 |
| 22  | BCL         | 2025-2026 |
| 12  | NBA         | 2025      |
