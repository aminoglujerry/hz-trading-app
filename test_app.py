"""
Test suite for HZ / FT Trading App.

Run with:  pytest test_app.py -v
"""

import pytest
from fastapi.testclient import TestClient

from app import (
    _hz_engine,
    _ft_engine,
    _format_signal_msg,
    _matchup_key,
    _add_seen_ft_id,
    _seen_ft_ids,
    _safe_pct,
    _parse_team_stats,
    LEAGUES,
    SEEN_FT_IDS_MAX,
    _h2h_cache,
    app,
    _auto_signal_for_game,
    H2H_MIN_SAMPLES,
    _ft_h2h_cache,
    _auto_sent,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """FastAPI TestClient that exercises the full lifespan context."""
    with TestClient(app) as c:
        yield c


# ─── _matchup_key ─────────────────────────────────────────────────────────────


class TestMatchupKey:
    def test_order_independent(self):
        assert _matchup_key("Team A", "Team B") == _matchup_key("Team B", "Team A")

    def test_case_insensitive(self):
        assert _matchup_key("lakers", "CELTICS") == _matchup_key("LAKERS", "celtics")

    def test_strips_whitespace(self):
        assert _matchup_key("  Lakers  ", "Celtics") == _matchup_key("Lakers", "Celtics")

    def test_separator(self):
        key = _matchup_key("Alpha", "Beta")
        assert "|" in key


# ─── _add_seen_ft_id ─────────────────────────────────────────────────────────


class TestAddSeenFtId:
    def setup_method(self):
        _seen_ft_ids.clear()

    def teardown_method(self):
        _seen_ft_ids.clear()

    def test_add_key(self):
        _add_seen_ft_id("2025-01-01-Home-Away")
        assert "2025-01-01-Home-Away" in _seen_ft_ids

    def test_duplicate_ignored(self):
        _add_seen_ft_id("key1")
        _add_seen_ft_id("key1")
        assert len(_seen_ft_ids) == 1

    def test_fifo_eviction(self):
        for i in range(SEEN_FT_IDS_MAX + 5):
            _add_seen_ft_id(f"key-{i}")
        assert len(_seen_ft_ids) <= SEEN_FT_IDS_MAX


# ─── _safe_pct ────────────────────────────────────────────────────────────────


class TestSafePct:
    def test_valid_string(self):
        assert _safe_pct("77.8") == 77.8

    def test_valid_float(self):
        assert _safe_pct(43.5) == 43.5

    def test_none_returns_none(self):
        assert _safe_pct(None) is None

    def test_empty_string_returns_none(self):
        assert _safe_pct("") is None

    def test_zero_string_returns_none(self):
        assert _safe_pct("0") is None

    def test_zero_float_returns_none(self):
        assert _safe_pct(0.0) is None

    def test_invalid_string_returns_none(self):
        assert _safe_pct("n/a") is None


# ─── _parse_team_stats ────────────────────────────────────────────────────────


class TestParseTeamStats:
    def _make_mock_team_response(self, *, fouls=5, fg_pct="50.0", ft_pct="78.0"):
        return {
            "team": {"id": 1, "name": "Test Team"},
            "statistics": [
                {
                    "personal_fouls": fouls,
                    "field_goals": {"percentage": fg_pct},
                    "freethrows_goals": {"percentage": ft_pct},
                }
            ],
        }

    def test_basic_parsing(self):
        result = _parse_team_stats(self._make_mock_team_response())
        assert result["fouls"] == 5
        assert result["fg_pct"] == 50.0
        assert result["ft_pct"] == 78.0

    def test_empty_statistics(self):
        result = _parse_team_stats({"team": {"id": 2, "name": "X"}, "statistics": []})
        assert result["fouls"] == 0
        assert result["fg_pct"] is None
        assert result["ft_pct"] is None


# ─── _hz_engine ───────────────────────────────────────────────────────────────


class TestHzEngine:
    """
    Buffer = proj − line.
    proj = q1 + q2_proj
    q2_proj (live) = q2 + (q2/timer) * time_left  where time_left = 10 − timer
    """

    # ── UNDER signals ──────────────────────────────────────────────────────────

    def test_under_a_no_h2h(self):
        # timer=6 → time_left=4 ≥ 3.5, buffer large, no fouls
        r = _hz_engine(
            h2h=None, line=91.5, q1=52, q2=28, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "A"

    def test_under_a_h2h_confirms(self):
        # h2h=96 → h2h_buf=+4.5 ≥ 3 → A confirmed
        r = _hz_engine(
            h2h=96.0, line=91.5, q1=52, q2=28, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "A"
        assert any("bestaetigt" in reason for reason in r["reasons"])

    def test_under_b_late_entry(self):
        # timer=6.8 → time_left=3.2 → entry_ok (≥2.5) but NOT entry_a (<3.5) → B
        # q2_proj = 30 + (30/6.8)*3.2 ≈ 44.1 → proj ≈ 99.1 → buffer ≈ +7.6 ≥ 5
        r = _hz_engine(
            h2h=None, line=91.5, q1=55, q2=30, timer=6.8,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "B"

    def test_under_b_h2h_kontra(self):
        # h2h below line → kontra → B even with good entry time
        r = _hz_engine(
            h2h=88.0, line=91.5, q1=52, q2=28, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "B"
        assert any("kontra" in reason for reason in r["reasons"])

    def test_under_blocked_by_fouls(self):
        # fouls=8 blocks UNDER
        r = _hz_engine(
            h2h=None, line=91.5, q1=52, q2=28, timer=6,
            fouls=8, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] != "UNDER"

    def test_under_blocked_by_fg_pct(self):
        # fg_pct=65 > HZ_FG_SKIP(60) → skip
        r = _hz_engine(
            h2h=None, line=91.5, q1=52, q2=28, timer=6,
            fouls=3, ft_pct=None, fg_pct=65.0,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "SKIP"
        assert any("FG%" in reason for reason in r["reasons"])

    # ── OVER signals ───────────────────────────────────────────────────────────

    def test_over_a_with_fouls_catalyst(self):
        # buffer ≤ -3, fouls ≥ 8 → OVER A
        r = _hz_engine(
            h2h=None, line=91.5, q1=42, q2=20, timer=6,
            fouls=9, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "A"
        assert any("Fouls" in reason for reason in r["reasons"])

    def test_over_a_with_ft_pct_catalyst(self):
        # FT% ≥ 85 → OVER A
        r = _hz_engine(
            h2h=None, line=91.5, q1=42, q2=20, timer=6,
            fouls=3, ft_pct=88.0, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "A"

    def test_over_a_with_line_move(self):
        # line_drop → line moved → OVER A
        r = _hz_engine(
            h2h=None, line=91.5, q1=42, q2=20, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=True, line_rise=False,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "A"

    def test_over_a_with_h2h_catalyst(self):
        # h2h_buf ≤ -3 → H2H over catalyst
        r = _hz_engine(
            h2h=86.0, line=91.5, q1=42, q2=20, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "A"

    def test_over_b_no_catalyst(self):
        # buffer ≤ -3 but no catalyst → B
        r = _hz_engine(
            h2h=None, line=91.5, q1=42, q2=20, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "B"

    # ── SKIP ───────────────────────────────────────────────────────────────────

    def test_skip_entry_too_late(self):
        # timer=9 → time_left=1 < 2.5 → SKIP
        r = _hz_engine(
            h2h=None, line=91.5, q1=52, q2=28, timer=9,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "SKIP"

    def test_skip_buffer_too_small(self):
        # q2_proj = 24 + (24/6)*4 = 40, proj = 50+40 = 90, buffer = 90-91.5 = -1.5
        # |buffer| < HZ_BUFFER_OVER(3) → not OVER, buffer < HZ_BUFFER_UNDER(5) → not UNDER → SKIP
        r = _hz_engine(
            h2h=None, line=91.5, q1=50, q2=24, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        assert r["dir"] == "SKIP"

    # ── Halftime mode ──────────────────────────────────────────────────────────

    def test_halftime_mode_under(self):
        # is_ht=True: q1+q2 = 54+42 = 96, line=91 → buffer=5 → UNDER A
        r = _hz_engine(
            h2h=None, line=91.0, q1=54, q2=42, timer=0,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False, is_ht=True,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "A"
        assert any("Halbzeit" in reason for reason in r["reasons"])

    def test_halftime_mode_time_left_zero(self):
        r = _hz_engine(
            h2h=None, line=91.0, q1=54, q2=42, timer=0,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False, is_ht=True,
        )
        assert r["time_left"] == 0.0

    # ── Return structure ───────────────────────────────────────────────────────

    def test_return_fields(self):
        r = _hz_engine(
            h2h=None, line=91.5, q1=52, q2=28, timer=6,
            fouls=3, ft_pct=None, fg_pct=None,
            line_drop=False, line_rise=False,
        )
        for field in ("dir", "stufe", "type", "proj", "buffer", "time_left", "fouls", "reasons"):
            assert field in r
        assert r["type"] == "HZ"
        assert isinstance(r["reasons"], list)


# ─── _ft_engine ───────────────────────────────────────────────────────────────


class TestFtEngine:
    """
    buffer = (hz + q3h + q3a) − line
    """

    # ── UNDER signals ──────────────────────────────────────────────────────────

    def test_under_a_with_ft_pct(self):
        # buffer = 90+30+28-140 = 8, ft_ok → A
        r = _ft_engine(
            h2h=None, line=140.0,
            q3h=30, q3a=28, hz=90, fouls=5,
            ft_pct_h=80.0, ft_pct_a=78.0,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "A"

    def test_under_a_h2h_confirms(self):
        # h2h_buf ≥ 5 adds confirmation reason
        r = _ft_engine(
            h2h=150.0, line=140.0,
            q3h=30, q3a=28, hz=90, fouls=5,
            ft_pct_h=80.0, ft_pct_a=78.0,
        )
        assert r["dir"] == "UNDER"
        assert any("bestaetigt" in reason for reason in r["reasons"])

    def test_under_b_buffer_only(self):
        # buffer ≥ FT_BUFFER_UNDER_B (10) but no ft_pct → B
        r = _ft_engine(
            h2h=None, line=136.0,
            q3h=30, q3a=28, hz=90, fouls=5,
            ft_pct_h=None, ft_pct_a=None,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "B"

    def test_under_b_buffer_above_a_threshold_no_ft_pct(self):
        # buffer 10.5, no ft_pct → B (FT_BUFFER_UNDER_B=10 requires no ft_ok)
        # current = 90+30+28 = 148, line=137.5 → buffer=10.5 ≥ FT_BUFFER_UNDER_B(10)
        r = _ft_engine(
            h2h=None, line=137.5,
            q3h=30, q3a=28, hz=90, fouls=5,
            ft_pct_h=None, ft_pct_a=None,
        )
        assert r["dir"] == "UNDER"
        assert r["stufe"] == "B"

    # ── OVER signals ───────────────────────────────────────────────────────────

    def test_over_a_with_ft_pct(self):
        # buffer = 90+20+18-140 = -12, ft_ok → OVER A
        r = _ft_engine(
            h2h=None, line=140.0,
            q3h=20, q3a=18, hz=90, fouls=5,
            ft_pct_h=80.0, ft_pct_a=78.0,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "A"

    def test_over_a_with_fouls_catalyst(self):
        # fouls ≥ 10 adds catalyst reason
        r = _ft_engine(
            h2h=None, line=140.0,
            q3h=20, q3a=18, hz=90, fouls=12,
            ft_pct_h=80.0, ft_pct_a=78.0,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "A"
        assert any("Fouls" in reason for reason in r["reasons"])

    def test_over_b_no_ft_pct(self):
        # buffer ≤ -8 but ft_ok=False → B
        r = _ft_engine(
            h2h=None, line=140.0,
            q3h=20, q3a=18, hz=90, fouls=5,
            ft_pct_h=None, ft_pct_a=None,
        )
        assert r["dir"] == "OVER"
        assert r["stufe"] == "B"

    # ── Garbage-time skip ──────────────────────────────────────────────────────

    def test_garbage_time_skip(self):
        # gap = |q3h − q3a| = 25 > FT_GAP_MAX (20) → SKIP
        r = _ft_engine(
            h2h=None, line=140.0,
            q3h=45, q3a=20, hz=90, fouls=5,
            ft_pct_h=80.0, ft_pct_a=78.0,
        )
        assert r["dir"] == "SKIP"
        assert any("Garbage" in reason for reason in r["reasons"])

    # ── Return structure ───────────────────────────────────────────────────────

    def test_return_fields(self):
        r = _ft_engine(
            h2h=None, line=140.0,
            q3h=30, q3a=28, hz=90, fouls=5,
            ft_pct_h=80.0, ft_pct_a=78.0,
        )
        for field in ("dir", "stufe", "type", "proj", "buffer", "time_left", "fouls", "reasons"):
            assert field in r
        assert r["type"] == "FT"
        assert r["time_left"] is None  # FT engine never sets a time_left value


# ─── API Endpoints ────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_status_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_response_fields(self, client):
        r = client.get("/api/health")
        data = r.json()
        for field in ("api_key_set", "sheets_configured", "hz_matchups", "ft_matchups", "seen_ft_ids"):
            assert field in data

    def test_api_key_not_set(self, client):
        # In test environment, API_SPORTS_KEY is not set
        r = client.get("/api/health")
        assert r.json()["api_key_set"] is False


class TestLeaguesEndpoint:
    def test_returns_leagues(self, client):
        r = client.get("/api/leagues")
        assert r.status_code == 200
        data = r.json()
        assert "leagues" in data
        assert len(data["leagues"]) == len(LEAGUES)

    def test_league_structure(self, client):
        r = client.get("/api/leagues")
        league = r.json()["leagues"][0]
        assert "id" in league
        assert "name" in league
        assert "season" in league


class TestH2hEndpoint:
    def test_no_cache_returns_not_found(self, client):
        r = client.get("/api/h2h?home=TeamX&away=TeamY")
        assert r.status_code == 200
        data = r.json()
        assert data["found"] is False
        assert data["avg"] is None
        assert data["count"] == 0

    def test_hz_type_default(self, client):
        r = client.get("/api/h2h?home=Alpha&away=Beta")
        assert r.json()["type"] == "hz"

    def test_ft_type(self, client):
        r = client.get("/api/h2h?home=Alpha&away=Beta&type=ft")
        assert r.json()["type"] == "ft"

    def test_h2h_with_cached_data(self, client):
        key = _matchup_key("CachedHome", "CachedAway")
        _h2h_cache[key] = [90.0, 92.0, 88.0]
        try:
            r = client.get("/api/h2h?home=CachedHome&away=CachedAway")
            data = r.json()
            assert data["found"] is True
            assert data["count"] == 3
            assert data["avg"] == pytest.approx(90.0, abs=0.2)
        finally:
            del _h2h_cache[key]


class TestSignalHzEndpoint:
    def test_returns_signal(self, client):
        # buffer = proj(52 + 28*(4/6)*10+28 ≈ ...) large UNDER scenario
        r = client.get("/api/signal/hz?line=91.5&q1=52&q2=28&timer=6&fouls=3")
        assert r.status_code == 200
        data = r.json()
        assert data["type"] == "HZ"
        assert data["dir"] in ("UNDER", "OVER", "SKIP")
        assert data["stufe"] in ("A", "B", "C")

    def test_missing_line_returns_422(self, client):
        r = client.get("/api/signal/hz?q1=52&q2=28&timer=6")
        assert r.status_code == 422

    def test_under_signal(self, client):
        r = client.get("/api/signal/hz?line=91.5&q1=52&q2=28&timer=6&fouls=3")
        assert r.json()["dir"] == "UNDER"

    def test_halftime_mode(self, client):
        r = client.get("/api/signal/hz?line=91.0&q1=54&q2=42&timer=0&fouls=3&is_ht=true")
        data = r.json()
        assert data["dir"] == "UNDER"
        assert data["time_left"] == 0.0

    def test_optional_params(self, client):
        r = client.get(
            "/api/signal/hz?line=91.5&q1=52&q2=28&timer=6&fouls=3"
            "&h2h=95.0&ft_pct=80.0&fg_pct=45.0&line_drop=false&line_rise=false"
        )
        assert r.status_code == 200


class TestSignalFtEndpoint:
    def test_returns_signal(self, client):
        r = client.get("/api/signal/ft?line=140.0&hz=90&q3h=30&q3a=28")
        assert r.status_code == 200
        data = r.json()
        assert data["type"] == "FT"
        assert data["dir"] in ("UNDER", "OVER", "SKIP")

    def test_missing_line_returns_422(self, client):
        r = client.get("/api/signal/ft?hz=90&q3h=30&q3a=28")
        assert r.status_code == 422

    def test_over_signal(self, client):
        r = client.get(
            "/api/signal/ft?line=140.0&hz=90&q3h=20&q3a=18&fouls=5"
            "&ft_pct_h=80.0&ft_pct_a=78.0"
        )
        assert r.json()["dir"] == "OVER"

    def test_garbage_time_skip(self, client):
        r = client.get("/api/signal/ft?line=140.0&hz=90&q3h=45&q3a=20&fouls=5")
        assert r.json()["dir"] == "SKIP"


class TestRootEndpoint:
    def test_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "<html" in r.text.lower()


# ─── Telegram helpers ─────────────────────────────────────────────────────────


class TestFormatSignalMsg:
    def test_under_signal(self):
        sig = {
            "dir": "UNDER", "stufe": "A", "type": "HZ",
            "proj": 96.0, "buffer": 5.5, "time_left": 4.2,
            "fouls": 4, "reasons": ["Buffer +5.5 >= 5", "H2H +3.2 bestaetigt"],
        }
        msg = _format_signal_msg(sig, "Real Madrid vs Barcelona (ACB)")
        assert "UNDER" in msg
        assert "STUFE A" in msg
        assert "HZ" in msg
        assert "Real Madrid" in msg
        assert "Buffer: +5.5" in msg
        assert "Zeit Q2: 4.2" in msg
        assert "Buffer +5.5 >= 5" in msg

    def test_over_signal(self):
        sig = {
            "dir": "OVER", "stufe": "B", "type": "FT",
            "proj": 130.0, "buffer": -9.0, "time_left": None,
            "fouls": 10, "reasons": ["Buffer -9.0 unter Linie"],
        }
        msg = _format_signal_msg(sig)
        assert "OVER" in msg
        assert "STUFE B" in msg
        assert "FT" in msg
        assert "Buffer: -9.0" in msg
        assert "Zeit Q2" not in msg  # time_left is None for FT

    def test_no_label(self):
        sig = {
            "dir": "UNDER", "stufe": "C", "type": "HZ",
            "proj": 80.0, "buffer": 3.0, "time_left": 5.0,
            "fouls": 2, "reasons": [],
        }
        msg = _format_signal_msg(sig)
        assert "UNDER" in msg

    def test_skip_signal(self):
        sig = {
            "dir": "SKIP", "stufe": "C", "type": "HZ",
            "proj": 85.0, "buffer": 1.0, "time_left": 8.0,
            "fouls": 3, "reasons": ["Kein Signal"],
        }
        msg = _format_signal_msg(sig, "Test Game")
        assert "SKIP" in msg


# ─── Telegram Endpoints ───────────────────────────────────────────────────────


class TestHealthTelegramField:
    def test_health_includes_telegram_configured(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "telegram_configured" in data

    def test_telegram_not_configured_in_test_env(self, client):
        # In test environment, TELEGRAM_BOT_TOKEN/CHAT_ID are not set
        r = client.get("/api/health")
        assert r.json()["telegram_configured"] is False


class TestTelegramTestEndpoint:
    def test_returns_400_when_not_configured(self, client):
        # No Telegram credentials in test env → 400
        r = client.get("/api/telegram/test")
        assert r.status_code == 400
        assert "TELEGRAM_BOT_TOKEN" in r.json()["detail"]


class TestTelegramPushEndpoint:
    def test_returns_not_configured_when_no_token(self, client):
        payload = {
            "dir": "UNDER", "stufe": "A", "type": "HZ",
            "proj": 96.0, "buffer": 5.5, "time_left": 4.2,
            "fouls": 4, "reasons": ["Buffer +5.5 >= 5"],
            "label": "Real Madrid vs Barcelona",
        }
        r = client.post("/api/telegram/push", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["sent"] is False
        assert data["reason"] == "telegram_not_configured"

    def test_skip_signal_not_sent(self, client):
        payload = {
            "dir": "SKIP", "stufe": "C", "type": "HZ",
            "proj": 85.0, "buffer": 1.0, "time_left": 8.0,
            "fouls": 3, "reasons": ["Kein Signal"], "label": "",
        }
        r = client.post("/api/telegram/push", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["sent"] is False
        assert data["reason"] == "skip_signal"

    def test_missing_body_returns_422(self, client):
        r = client.post("/api/telegram/push")
        assert r.status_code == 422


class TestLiveScanEndpoint:
    def test_returns_200_without_api_key(self, client):
        # No API key in test env → returns early with empty lists
        r = client.get("/api/live-scan")
        assert r.status_code == 200
        data = r.json()
        assert "hz" in data
        assert "q3" in data
        assert "count" in data
        assert "telegram_sent" in data
        assert data["telegram_sent"] is False
        assert data["source"] == "no_api_key"


class TestStatsEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200

    def test_response_fields(self, client):
        r = client.get("/api/stats")
        data = r.json()
        for field in (
            "hz_matchups", "ft_matchups", "hz_games", "ft_games",
            "hz_avg", "ft_avg", "hz_min", "hz_max", "ft_min", "ft_max",
            "api_key_set", "sheets_configured", "telegram_configured",
        ):
            assert field in data

    def test_empty_cache_returns_none_averages(self, client):
        # With no data in H2H caches, averages should be None
        from app import _h2h_cache, _ft_h2h_cache
        orig_hz = dict(_h2h_cache)
        orig_ft = dict(_ft_h2h_cache)
        _h2h_cache.clear()
        _ft_h2h_cache.clear()
        try:
            r = client.get("/api/stats")
            data = r.json()
            assert data["hz_avg"] is None
            assert data["ft_avg"] is None
            assert data["hz_matchups"] == 0
            assert data["ft_matchups"] == 0
        finally:
            _h2h_cache.update(orig_hz)
            _ft_h2h_cache.update(orig_ft)

    def test_populated_cache_returns_averages(self, client):
        from app import _h2h_cache, _ft_h2h_cache, _matchup_key
        key = _matchup_key("StatsHome", "StatsAway")
        _h2h_cache[key] = [90.0, 92.0, 88.0]
        _ft_h2h_cache[key] = [180.0, 184.0]
        try:
            r = client.get("/api/stats")
            data = r.json()
            assert data["hz_matchups"] >= 1
            assert data["ft_matchups"] >= 1
            assert data["hz_avg"] is not None
            assert data["ft_avg"] is not None
        finally:
            del _h2h_cache[key]
            del _ft_h2h_cache[key]


# ─── _auto_signal_for_game ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAutoSignalForGame:
    """Unit tests for _auto_signal_for_game — no live API calls needed."""

    _GAME_HZ = {
        "id": 9999,
        "home": "AutoHome",
        "away": "AutoAway",
        "status": "Q2",
        "timer": 5,
        "q1_total": 52,
        "q2_live": 28,
        "q3_home": 0,
        "q3_away": 0,
        "ht_total": 80,
    }
    _GAME_HT = {**_GAME_HZ, "status": "HT", "timer": None}
    _GAME_FT = {
        "id": 9998,
        "home": "FTHome",
        "away": "FTAway",
        "status": "Q3BT",
        "timer": None,
        "q1_total": 50,
        "q2_live": 44,
        "q3_home": 26,
        "q3_away": 22,
        "ht_total": 94,
    }

    async def test_hz_returns_none_when_no_h2h(self):
        """Without H2H entries the function must return None."""
        _h2h_cache.pop(_matchup_key("AutoHome", "AutoAway"), None)
        result = await _auto_signal_for_game(self._GAME_HZ, "hz")
        assert result is None

    async def test_hz_returns_none_when_too_few_samples(self):
        """Fewer than H2H_MIN_SAMPLES entries → None."""
        key = _matchup_key("AutoHome", "AutoAway")
        _h2h_cache[key] = [95.0] * (H2H_MIN_SAMPLES - 1)
        try:
            result = await _auto_signal_for_game(self._GAME_HZ, "hz")
            assert result is None
        finally:
            del _h2h_cache[key]

    async def test_hz_returns_signal_with_enough_h2h(self):
        """Enough H2H samples → signal dict is returned (any direction)."""
        key = _matchup_key("AutoHome", "AutoAway")
        # Q1=52, Q2=28 @ 5min → proj≈52+28+(28/5)*5=108, line=95 → buffer+13 → UNDER
        _h2h_cache[key] = [95.0] * H2H_MIN_SAMPLES
        try:
            result = await _auto_signal_for_game(self._GAME_HZ, "hz")
            assert result is not None
            assert result["dir"] in ("UNDER", "OVER", "SKIP")
            assert result["stufe"] in ("A", "B", "C")
            assert result["type"] == "HZ"
            assert "proj" in result
            assert "buffer" in result
            assert "reasons" in result
        finally:
            del _h2h_cache[key]

    async def test_hz_halftime_mode(self):
        """HT status triggers is_ht=True in the engine."""
        key = _matchup_key("AutoHome", "AutoAway")
        _h2h_cache[key] = [95.0] * H2H_MIN_SAMPLES
        try:
            result = await _auto_signal_for_game(self._GAME_HT, "hz")
            assert result is not None
            assert result["time_left"] == 0.0  # halftime → time_left always 0
        finally:
            del _h2h_cache[key]

    async def test_ft_returns_none_when_no_h2h(self):
        """Without FT H2H entries the function must return None."""
        _ft_h2h_cache.pop(_matchup_key("FTHome", "FTAway"), None)
        result = await _auto_signal_for_game(self._GAME_FT, "ft")
        assert result is None

    async def test_ft_returns_signal_with_enough_h2h(self):
        """Enough FT H2H samples → signal dict is returned."""
        key = _matchup_key("FTHome", "FTAway")
        _ft_h2h_cache[key] = [186.0] * H2H_MIN_SAMPLES
        try:
            result = await _auto_signal_for_game(self._GAME_FT, "ft")
            assert result is not None
            assert result["dir"] in ("UNDER", "OVER", "SKIP")
            assert result["type"] == "FT"
        finally:
            del _ft_h2h_cache[key]

    async def test_hz_signal_uses_h2h_avg_as_line(self):
        """The computed buffer must be relative to the H2H average line."""
        key = _matchup_key("AutoHome", "AutoAway")
        h2h_avg = 95.0
        _h2h_cache[key] = [h2h_avg] * H2H_MIN_SAMPLES
        try:
            result = await _auto_signal_for_game(self._GAME_HZ, "hz")
            assert result is not None
            # With q1=52, q2=28 at timer=5 → proj=52+28+(28/5)*5=108 → buffer=108-95=13
            assert result["buffer"] > 0
        finally:
            del _h2h_cache[key]


# ─── /api/auto-scan endpoint ──────────────────────────────────────────────────


class TestAutoScanEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/auto-scan")
        assert r.status_code == 200

    def test_response_fields(self, client):
        r = client.get("/api/auto-scan")
        data = r.json()
        for field in ("sent", "interval_s", "min_stufe", "h2h_min", "dedup_entries",
                      "hz_matchups", "ft_matchups"):
            assert field in data, f"missing field: {field}"

    def test_no_api_key_sends_nothing(self, client):
        # In test environment API_SPORTS_KEY is not set → sent must be 0
        r = client.get("/api/auto-scan")
        data = r.json()
        assert data["sent"] == 0

    def test_interval_is_positive(self, client):
        r = client.get("/api/auto-scan")
        assert r.json()["interval_s"] > 0

    def test_h2h_min_matches_constant(self, client):
        r = client.get("/api/auto-scan")
        assert r.json()["h2h_min"] == H2H_MIN_SAMPLES
