from datetime import datetime, timedelta, timezone

import pytest

from live.trend_bot import PaperExchange, Settings, closed_daily_closes, decide, run_once

NOW = datetime(2026, 10, 18, 0, 10, tzinfo=timezone.utc)


class FakePublic:
    """Daily candles ending with today's forming candle."""

    def __init__(self, closes, last=None, now=NOW):
        self.closes, self.last, self.now = closes, last or closes[-1], now

    def fetch_ohlcv(self, symbol, tf, limit):
        today = self.now.replace(hour=0, minute=0)
        n = len(self.closes)
        rows = [[int((today - timedelta(days=n - i)).timestamp() * 1000), 0, 0, 0, c, 0]
                for i, c in enumerate(self.closes)]
        rows.append([int(today.timestamp() * 1000), 0, 0, 0, 999999, 0])  # forming candle
        return rows[-limit:]

    def fetch_ticker(self, symbol):
        return {"last": self.last}


def cfg(tmp_path, **kw):
    env = {"BOT_STATE_DIR": str(tmp_path), "BOT_SMA": "5", "PAPER_START_USDT": "10", **kw}
    return Settings(env)


def paper(tmp_path, closes, last=None):
    return PaperExchange(FakePublic(closes, last), str(tmp_path / "paper.json"), 10.0)


def test_forming_candle_is_dropped():
    rows = closed_daily_closes(FakePublic([1, 2, 3, 4, 5, 6]), "BTC/USDT", 5, NOW)
    assert [c for _, c in rows] == [2, 3, 4, 5, 6]


def test_decide():
    up = [(None, c) for c in [1, 2, 3, 4, 10]]
    down = [(None, c) for c in [10, 9, 8, 7, 1]]
    assert decide(up, 5) == 1.0 and decide(down, 5) == 0.0
    with pytest.raises(ValueError):
        decide(up[:3], 5)


def test_buys_in_uptrend_then_sells_in_downtrend(tmp_path):
    c = cfg(tmp_path)
    ex = paper(tmp_path, [100, 101, 102, 103, 110])
    assert run_once(c, ex, NOW) == "traded"
    assert ex.bal["USDT"] < 0.1 and ex.bal["BTC"] > 0

    ex.pub = FakePublic([110, 105, 100, 95, 80], last=80, now=NOW + timedelta(days=1))
    assert run_once(c, ex, NOW + timedelta(days=1)) == "traded"
    assert 0 <= ex.bal["BTC"] < 1e-6   # only sub-step-size dust remains
    assert 0 < ex.bal["USDT"] < 10   # lost money on this round trip, fees included


def test_idempotent_same_candle(tmp_path):
    c = cfg(tmp_path)
    ex = paper(tmp_path, [100, 101, 102, 103, 110])
    run_once(c, ex, NOW)
    assert run_once(c, ex, NOW) == "already_done"


def test_stop_file_blocks_trading(tmp_path):
    (tmp_path / "STOP").write_text("")
    ex = paper(tmp_path, [100, 101, 102, 103, 110])
    assert run_once(cfg(tmp_path), ex, NOW) == "stopped"
    assert ex.bal["BTC"] == 0


def test_stale_data_aborts(tmp_path):
    ex = paper(tmp_path, [100, 101, 102, 103, 110])
    assert run_once(cfg(tmp_path), ex, NOW + timedelta(days=5)) == "stale"


def test_below_min_notional_does_not_trade(tmp_path):
    ex = paper(tmp_path, [100, 101, 102, 103, 110])
    ex.bal = {"USDT": 3.0, "BTC": 0.0}
    assert run_once(cfg(tmp_path), ex, NOW) == "no_trade"


def test_live_mode_requires_explicit_confirmation(tmp_path):
    with pytest.raises(ValueError):
        Settings({"BOT_MODE": "live", "BINANCE_API_KEY": "k", "BINANCE_API_SECRET": "s"})
