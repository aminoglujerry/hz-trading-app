# HZ / FT Trading App

Basketball live trading signal engine für Halftime (HZ) und Fulltime (FT) Märkte.  
Deployed auf Render, Daten via API-Sports, H2H-Cache via Google Sheets.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + httpx (Python) |
| Frontend | Vanilla HTML/CSS/JS (inline, kein Build-Step) |
| Live Data | API-Sports Basketball v1 |
| H2H Cache | Google Sheets (gspread + Service Account) |
| Hosting | Render Web Service |

---

## Environment Variables

Alle in Render unter **Environment** setzen:

| Variable | Beschreibung |
|---|---|
| `API_SPORTS_KEY` | API-Sports Key |
| `GOOGLE_SHEETS_ID` | Sheet-ID aus der URL (`/d/<ID>/`) |
| `GOOGLE_SHEETS_TAB` | Tab-Name exakt: `h2h_2025_2026` |
| `GOOGLE_CREDENTIALS_JSON` | Kompletter Service Account JSON als eine Zeile |

---

## Deploy auf Render

1. Repo auf GitHub pushen
2. Render → **New Web Service** → Repo verbinden
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Environment Variables setzen (siehe oben)
6. Deploy

---

## Google Sheets Setup

1. [Google Cloud Console](https://console.cloud.google.com) → neues Projekt
2. **APIs & Services** → Google Sheets API aktivieren
3. **Credentials** → Service Account erstellen → JSON-Key herunterladen
4. Den kompletten JSON-Inhalt als `GOOGLE_CREDENTIALS_JSON` in Render eintragen
5. Google Sheet öffnen → **Teilen** → Service Account Email als Editor hinzufügen

Sheet-Struktur (wird automatisch angelegt falls nicht vorhanden):

```
date | home | away | league | q1_total | q2_total | ht_total | ft_total
```

---

## Erstes Deployment: Sheet befüllen

Nach dem Deploy einmal aufrufen:

```
GET https://<deine-render-url>/api/backfill?days=60
```

Füllt das Sheet mit den letzten 60 Tagen FT-Daten aus allen konfigurierten Ligen.  
Danach läuft der Cache automatisch alle 30 Minuten.

---

## API Endpoints

| Endpoint | Beschreibung |
|---|---|
| `GET /` | Trading UI |
| `GET /api/live` | Live HZ/Q2 Spiele + Q3-Break Kandidaten + heute |
| `GET /api/h2h?home=X&away=Y` | HZ H2H Durchschnitt für Matchup |
| `GET /api/h2h?home=X&away=Y&type=ft` | FT H2H Durchschnitt für Matchup |
| `GET /api/backfill?days=30` | Historische FT-Daten in Sheet schreiben (max 90 Tage) |
| `GET /api/trigger-extract` | Manuell heutige FT-Spiele extrahieren |
| `GET /api/health` | Status: API Key, Sheets, Cache-Größe |
| `GET /api/leagues` | Alle konfigurierten Ligen |

---

## Signal Logic

### HZ (Halftime)

**Entry Window:** Alpha 7:00–5:00 Min | Beta 3:30–2:30 Min

| Signal | Bedingung | Stufe |
|---|---|---|
| UNDER | Buffer ≥ 5, Fouls < 8, FG% ≤ 60, Entry ≥ 3:30 | A |
| UNDER | Buffer ≥ 5, Fouls < 8, Entry 2:30–3:30 | B |
| UNDER | Buffer ≥ 5, H2H kontra | B |
| OVER | Buffer ≤ −3 + Katalysator (Fouls ≥ 8, FT% ≥ 85, Linie bewegt) | A |
| OVER | Buffer ≤ −3, kein Katalysator | B |
| SKIP | Buffer < 3, Entry < 2:30, FG% > 60 | C |

**Buffer** = Projektion − Bookie Line  
**Projektion** = Q1 Total + Q2-Pace × verbleibende Q2-Zeit

### FT (Fulltime)

**Entry:** Q3 Break

| Signal | Bedingung | Stufe |
|---|---|---|
| UNDER | Buffer ≥ 8, FT% beide ≥ 75% | A |
| UNDER | Buffer ≥ 10 (FT% egal) | A/B |
| OVER | Buffer ≤ −8, FT% beide ≥ 75% | A |
| OVER | Buffer ≤ −8, FT% nicht erfüllt | B |
| SKIP | Gap > 20 (Garbage Time) | C |

**Buffer** = (HZ Total + Q3 Total) − FT Bookie Line  
**Korrelationsregel:** HZ + FT selbe Richtung → max Stufe B

---

## Ligen

| ID | Liga | Season |
|---|---|---|
| 120 | TBL | 2025-2026 |
| 4 | ACB | 2025-2026 |
| 6 | ABA Liga | 2025-2026 |
| 23 | LNB Pro A | 2025-2026 |
| 8 | Lega A | 2025-2026 |
| 3 | EuroLeague | 2025-2026 |
| 2 | EuroCup | 2025-2026 |
| 15 | BBL | 2025-2026 |
| 11 | GBL | 2025-2026 |
| 22 | BCL | 2025-2026 |
| 12 | NBA | 2025 |
| 5 | VTB | 2025-2026 |
| 16 | Jeep Elite | 2025-2026 |
| 19 | NBB | 2025-2026 |
| 38 | Süper Lig | 2025-2026 |

---

## Local Development

```bash
pip install -r requirements.txt
API_SPORTS_KEY=xxx GOOGLE_SHEETS_ID=xxx GOOGLE_SHEETS_TAB=h2h_2025_2026 GOOGLE_CREDENTIALS_JSON='{}' uvicorn app:app --reload
```

Ohne API Key läuft die App im **Demo-Modus** mit Beispieldaten.
