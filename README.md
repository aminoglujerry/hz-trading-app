# HZ Trading App

Basketball Halftime Trading Signal Engine — deployable on Render.

## Stack
- **Backend**: FastAPI + httpx (Python)
- **Frontend**: Vanilla HTML/CSS/JS (served as static)
- **Data**: API-Sports Basketball v1
- **H2H Cache**: Google Sheets (optional, seasonal cache updated every 3 days)

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
5. **Environment Variables**:
   - `API_SPORTS_KEY` = your API-Sports key
   - *(optional)* `GOOGLE_SHEETS_ID`, `GOOGLE_SHEETS_TAB`, `GOOGLE_CREDENTIALS_JSON` — see below

## Google Sheets Setup (H2H Seasonal Cache)

The app can read/write H2H averages to a Google Sheet so they persist across restarts and are updated every 3 days without spending API quota.

### Step 1: Create the Sheet

1. Go to [sheets.google.com](https://sheets.google.com)
2. Create a new spreadsheet: **"HZ-Trading-Cache"**
3. Rename the first tab to: **`h2h_2025_2026`**
4. Paste this header row in row 1:

```
home_team_id | away_team_id | league_id | h2h_avg | h2h_last_5 | h2h_games | trend | last_updated
```

### Step 2: Get a Google API Service Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project: **"HZ-Trading"**
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Download the **JSON key file**

### Step 3: Share the Sheet

Open the sheet → Share → add the service-account email from the JSON file (`xyz@hz-trading.iam.gserviceaccount.com`) as **Editor**.

### Step 4: Configure Environment Variables

Copy `.env.example` to `.env` and fill in:

```env
GOOGLE_SHEETS_ID=<the long ID from the sheet URL>
GOOGLE_SHEETS_TAB=h2h_2025_2026
# Choose one of:
GOOGLE_CREDENTIALS_JSON=/path/to/service_account.json   # local file path
# OR base64-encode the JSON file for Render:
# GOOGLE_CREDENTIALS_JSON=$(base64 -w0 service_account.json)
```

### How It Works

- **Cache read** (`/api/live/screened`): H2H data is fetched from the in-memory cache → Google Sheets → API (fallback), using **0 extra API calls** when cached.
- **Cache write**: On a cache miss the H2H is calculated from the API and written back to Sheets for next time.
- **Cronjob**: Every **Monday, Wednesday, and Friday at 02:00 UTC** a background thread refreshes all H2H pairs for the configured leagues.
- **Manual refresh**: `POST /api/h2h/refresh` triggers a background refresh immediately.

## Features
- Live HT/Q2 game loader (10 priority leagues)
- **H2H auto-populated** from Google Sheets cache (no extra API calls)
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
