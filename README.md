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
| `TELEGRAM_BOT_TOKEN` | Telegram Bot-Token für automatische Signal-Alerts |
| `TELEGRAM_CHAT_ID` | Telegram Chat-ID für Signal-Alerts |
| `AUTO_SCAN_INTERVAL` | Sekunden zwischen Auto-Scan-Zyklen (Standard: `120`) |
| `AUTO_SCAN_STUFE` | Mindest-Signalstufe für Auto-Alerts (`A` oder `B`, Standard: `A`) |

---

## Deploy auf Render

1. Repo auf GitHub pushen
2. Render → **New Web Service** → Repo verbinden
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `python app.py`
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

> **Hinweis:** `ht_total` = Q1 + Q2 (Halftime-Total, ~85–110 Punkte), **nicht** das Full-Game Total.  
> `ft_total` = komplettes Spielergebnis.

---

## Erstes Deployment: Sheet befüllen

Nach dem Deploy in mehreren Batches aufrufen (max. 14 Tage pro Request — 7 Tage empfohlen wegen Render Free-Tier 512 MB RAM-Limit):

```
GET https://<deine-render-url>/api/backfill?days=7&offset=0   → Tage 1–7
GET https://<deine-render-url>/api/backfill?days=7&offset=7   → Tage 8–14
GET https://<deine-render-url>/api/backfill?days=7&offset=14  → Tage 15–21
```

Danach läuft der Cache automatisch alle 30 Minuten (Background-Scheduler).  
Bei Bedarf manuell nachladen: `GET /api/reload-cache`

---

## API Endpoints

| Endpoint | Beschreibung |
|---|---|
| `GET /` | Trading UI |
| `GET /api/live` | Live HZ/Q2 Spiele + Q3-Break Kandidaten + Tagesplan |
| `GET /api/h2h?home=X&away=Y` | HZ H2H Durchschnitt für Matchup |
| `GET /api/h2h?home=X&away=Y&type=ft` | FT H2H Durchschnitt für Matchup |
| `GET /api/game-stats/{game_id}` | Live-Stats: Fouls, FT%, FG% pro Team (60s gecacht) |
| `GET /api/signal/hz` | HZ Signal Engine als JSON API (Parameter siehe unten) |
| `GET /api/signal/ft` | FT Signal Engine als JSON API (Parameter siehe unten) |
| `GET /api/auto-scan` | Manuell einen Auto-Scan-Zyklus auslösen + Status anzeigen |
| `GET /api/live-scan` | Aktive HZ/Q3BT-Spiele per Telegram melden (für externe Cron-Jobs) |
| `GET /api/backfill?days=7&offset=0` | Historische FT-Daten ins Sheet schreiben (max 14 Tage) |
| `GET /api/trigger-extract` | Manuell heutige FT-Spiele extrahieren |
| `GET /api/reload-cache` | H2H Cache aus dem Sheet neu laden |
| `GET /api/health` | Status: API Key, Sheets, Cache-Größen |
| `GET /api/leagues` | Alle konfigurierten Ligen |
| `GET /api/debug-stats/{game_id}` | Rohdaten der API-Sports Statistik-Antwort (Debug) |
| `GET /api/debug-sheets` | Sheets-Verbindung diagnostizieren |

### `/api/signal/hz` Parameter

| Parameter | Typ | Beschreibung |
|---|---|---|
| `line` | float | Bookie HZ-Linie (Pflicht) |
| `q1` | float | Q1 Total |
| `q2` | float | Q2 aktuelle Punkte |
| `timer` | float | Q2 vergangene Zeit (Minuten) |
| `fouls` | int | Fouls gesamt (beide Teams) |
| `h2h` | float | H2H Durchschnitt HZ-Total |
| `ft_pct` | float | Durchschnittliche FT% (beide Teams) |
| `fg_pct` | float | Durchschnittliche FG% (beide Teams) |
| `line_drop` | bool | Linie um ≥8 gefallen |
| `line_rise` | bool | Linie steigt |
| `is_ht` | bool | Spiel steht in der Halbzeit (Q2 abgeschlossen) |

### `/api/signal/ft` Parameter

| Parameter | Typ | Beschreibung |
|---|---|---|
| `line` | float | Bookie FT-Linie (Pflicht) |
| `q3h` | float | Q3 Punkte Heimteam |
| `q3a` | float | Q3 Punkte Auswärtsteam |
| `hz` | float | HZ-Total |
| `fouls` | int | Fouls gesamt (beide Teams) |
| `h2h` | float | H2H Durchschnitt FT-Total |
| `ft_pct_h` | float | FT% Heimteam |
| `ft_pct_a` | float | FT% Auswärtsteam |

---

## Signal Logic

### HZ (Halftime)

**Entry Window:** Optimal ≥ 3:30 Min (Q2) | Minimum 2:30 Min  
**Halftime-Modus:** Bei `is_ht=true` wird der echte Q2-Wert verwendet und das Entry-Gate übersprungen.

| Signal | Bedingung | Stufe |
|---|---|---|
| UNDER | Buffer ≥ 5, Fouls < 8, FG% ≤ 60, Entry ≥ 3:30 | A |
| UNDER | Buffer ≥ 5, Fouls < 8, Entry 2:30–3:30 oder H2H kontra | B |
| OVER | Buffer ≤ −3 + Katalysator (Fouls ≥ 8, FT% ≥ 85, Linie bewegt, H2H ≤ −3) | A |
| OVER | Buffer ≤ −3, kein Katalysator | B |
| SKIP | Buffer < 5, Entry < 2:30 oder FG% > 60 | C |

**Buffer** = Projektion − Bookie Line  
**Projektion** (Q2 läuft) = Q1 Total + (Q2 aktuell / vergangene Zeit) × 10  
**Projektion** (Halbzeit) = Q1 Total + Q2 tatsächlich

**H2H-Einfluss:**
- H2H-Buffer ≥ 3 → Bestätigung UNDER
- H2H-Buffer < 0 → Kontra (UNDER wird Stufe B)
- H2H-Buffer ≤ −3 → OVER-Katalysator

### FT (Fulltime)

**Entry:** Q3 Break

| Signal | Bedingung | Stufe |
|---|---|---|
| UNDER | Buffer ≥ 8, FT% beide ≥ 75% | A |
| UNDER | Buffer ≥ 10 (FT% egal) | B |
| OVER | Buffer ≤ −8, FT% beide ≥ 75% | A |
| OVER | Buffer ≤ −8, FT% nicht erfüllt | B |
| SKIP | Gap > 20 (Garbage Time) | C |

**Buffer** = (HZ Total + Q3 Total) − FT Bookie Line  
**OVER-Katalysator:** Fouls gesamt ≥ 10  
**H2H-Einfluss:** H2H-Buffer ≥ 5 → Bestätigung UNDER

---

## Auto-Signal (Automatisiertes Signal)

Der Server führt automatisch alle `AUTO_SCAN_INTERVAL` Sekunden (Standard: 120 s) einen vollständigen Signal-Scan durch:

1. Alle konfigurierten Ligen werden nach Live-Spielen im HZ (Halbzeit/Q2) und Q3-Break-Fenster durchsucht.
2. Für jedes gefundene Spiel wird der **H2H-Durchschnitt als Referenzlinie** herangezogen (mind. 3 Einträge im Cache).
3. Live-Spielstatistiken (Fouls, FT%, FG%) werden automatisch abgerufen.
4. Die Signal-Engines (`_hz_engine` / `_ft_engine`) berechnen ein Signal.
5. **Stufe-A-Signale** werden sofort via Telegram gesendet.

**Deduplication:** Für jedes Spiel wird maximal ein Signal pro 25 Minuten gesendet.

**Kein Bookie Line nötig:** Der H2H-Durchschnitt dient als automatische Referenzlinie.  
→ Weicht die aktuelle Scoring-Pace signifikant vom historischen Mittelwert ab, erzeugt die Engine ein Signal.

### Frontend-Auto-Kalkulation

Sobald eine Live-Karte (HZ oder FT) angeklickt wird:
- H2H-Durchschnitt und Live-Stats werden parallel geladen.
- Wenn ein H2H-Wert vorhanden ist, wird er automatisch als Bookie Line vorausgefüllt.
- Das Signal wird sofort berechnet und auf der Karte angezeigt.
- Die Bookie Line kann jederzeit manuell überschrieben und neu berechnet werden.

---



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
| 117 | LNB Pro B | 2025-2026 |
| 14 | BSL | 2025-2026 |
| 17 | Korisliiga | 2025-2026 |
| 18 | Korisliiga W | 2025-2026 |
| 24 | Pro B | 2025-2026 |
| 7 | Adriatic | 2025-2026 |
| 9 | Lega A2 | 2025-2026 |
| 10 | A1 GR | 2025-2026 |
| 13 | CBA | 2025-2026 |
| 20 | Orlen BP | 2025-2026 |
| 25 | NLA | 2025-2026 |
| 29 | NBL | 2025-2026 |
| 30 | Superliga | 2025-2026 |
| 31 | Divizia A | 2025-2026 |
| 32 | PBL | 2025-2026 |
| 33 | LKL | 2025-2026 |
| 34 | Premijer | 2025-2026 |
| 36 | SBL | 2025-2026 |
| 37 | Extraliga | 2025-2026 |
| 40 | Superleague | 2025-2026 |

---

## Local Development

```bash
pip install -r requirements.txt
API_SPORTS_KEY=xxx GOOGLE_SHEETS_ID=xxx GOOGLE_SHEETS_TAB=h2h_2025_2026 GOOGLE_CREDENTIALS_JSON='{}' uvicorn app:app --reload
```

Ohne API Key läuft die App im **Demo-Modus** mit Beispieldaten.
