import numpy as np
import pandas as pd

from bot.backtest import run_backtest
from bot.config import BacktestConfig
from bot.strategy import compute_signals


def make_df(closes, highs=None, lows=None, opens=None):
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="D", tz="UTC")
    closes = np.asarray(closes, float)
    return pd.DataFrame({
        "open": closes if opens is None else opens,
        "high": closes * 1.01 if highs is None else highs,
        "low": closes * 0.99 if lows is None else lows,
        "close": closes,
        "volume": 1.0,
    }, index=idx)


def small_cfg():
    cfg = BacktestConfig(symbols=["X"])
    cfg.strategy.regime_ema, cfg.strategy.breakout_lookback, cfg.strategy.atr_period = 5, 5, 5
    cfg.costs.fee_rate = cfg.costs.slippage = 0.0
    return cfg


def test_signals_have_no_lookahead():
    """Changing future bars must not change any signal computed on past bars."""
    rng = np.random.default_rng(0)
    closes = 100 * np.cumprod(1 + rng.normal(0.002, 0.03, 400))
    cfg = small_cfg().strategy
    a = compute_signals(make_df(closes), cfg)
    future = closes.copy()
    future[300:] *= 3
    b = compute_signals(make_df(future), cfg)
    cols = ["entry_signal", "regime_exit", "breakout_level", "atr", "ema_regime"]
    pd.testing.assert_frame_equal(a.iloc[:300][cols], b.iloc[:300][cols])


def test_entry_fills_at_next_open_not_signal_close():
    closes = [100] * 20 + [110]  + [111] * 5
    opens = list(closes)
    opens[21] = 120                       # bar after the breakout opens much higher
    df = make_df(closes, opens=np.array(opens, float))
    cfg = small_cfg()
    res = run_backtest({"X": compute_signals(df, cfg.strategy)}, cfg)
    assert res.trades.iloc[0]["entry_price"] == 120
    assert res.trades.iloc[0]["entry_time"] == df.index[21]


def test_gap_through_stop_fills_at_open():
    closes = [100] * 20 + [110, 111, 112, 60, 60]
    opens = list(closes)
    opens[23] = 60                         # gap far below any stop
    lows = np.array(closes, float) * 0.99
    lows[23] = 59
    df = make_df(closes, opens=np.array(opens, float), lows=lows)
    cfg = small_cfg()
    res = run_backtest({"X": compute_signals(df, cfg.strategy)}, cfg)
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "stop_gap"
    assert t["exit_price"] == 60


def test_loss_per_trade_bounded_by_risk_when_no_gap():
    rng = np.random.default_rng(1)
    closes = 100 * np.cumprod(1 + rng.normal(0.003, 0.04, 800))
    cfg = small_cfg()
    res = run_backtest({"X": compute_signals(make_df(closes), cfg.strategy)}, cfg)
    stops = res.trades[res.trades.exit_reason == "stop"]
    assert len(stops) > 0
    assert stops.r_multiple.min() >= -1.0001
