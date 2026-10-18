"""Strategies as target-weight generators. Everything uses data up to the close
of day t only; the engine executes at the open of t+1.

Parameters are standard values from the literature / common practice, fixed
before testing. They are NOT optimised on this data.
"""
import numpy as np
import pandas as pd

from .engine import panel


def eligible(data: dict, min_history: int = 200, top_n: int = 10) -> pd.DataFrame:
    """Coin is tradable on day t if it has min_history bars and ranks in the top_n
    by 30-day average dollar volume among coins listed at that time."""
    close = panel(data, "close")
    dollar_vol = (panel(data, "volume") * close).rolling(30, min_periods=30).mean()
    age = close.notna().cumsum()
    ok = (age >= min_history) & dollar_vol.notna()
    rank = dollar_vol.where(ok).rank(axis=1, ascending=False)
    return ok & (rank <= top_n)


def btc_hold(data):
    close = panel(data, "close")
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    w["BTCUSDT"] = 1.0
    return w


def equal_weight_hold(data, top_n=10):
    elig = eligible(data, top_n=top_n)
    return elig.div(elig.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def btc_trend(data, sma=100):
    """Hold BTC while it closes above its N-day SMA, else cash."""
    close = panel(data, "close")
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    btc = close["BTCUSDT"]
    w["BTCUSDT"] = (btc > btc.rolling(sma, min_periods=sma).mean()).astype(float)
    return w


def tsmom_vol_target(data, lookbacks=(20, 60, 120), vol_window=60, target_vol=0.5,
                     max_gross=1.0, top_n=10):
    """Time-series momentum: long each coin in proportion to how many lookback
    returns are positive, weighted by inverse volatility, scaled to a portfolio
    volatility target and capped at max_gross."""
    close = panel(data, "close")
    rets = close.pct_change(fill_method=None)
    elig = eligible(data, top_n=top_n)
    sig = sum((close / close.shift(lb) - 1 > 0).astype(float) for lb in lookbacks) / len(lookbacks)
    vol = rets.rolling(vol_window, min_periods=vol_window).std() * np.sqrt(365)
    raw = (sig / vol).where(elig).fillna(0.0)

    # normalise to gross 1, then scale by (vol target / estimated portfolio vol)
    w = raw.div(raw.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    port_ret = (w.shift(1) * rets).sum(axis=1)
    port_vol = port_ret.rolling(vol_window, min_periods=20).std() * np.sqrt(365)
    scale = (target_vol / port_vol).clip(upper=max_gross).fillna(0.0)
    # average signal strength also scales exposure: weak trends -> smaller book
    strength = (sig.where(elig) * elig).sum(axis=1) / elig.sum(axis=1).replace(0, np.nan)
    return w.mul(np.minimum(scale, max_gross * strength.fillna(0)), axis=0)


def xs_momentum(data, lookback=28, hold_k=3, rebalance_days=7, regime_sma=100, top_n=10):
    """Cross-sectional momentum rotation: every rebalance_days, hold the hold_k
    coins with the best lookback return (only if that return > 0), equal weight.
    Go to cash when BTC is below its regime SMA."""
    close = panel(data, "close")
    elig = eligible(data, top_n=top_n)
    mom = (close / close.shift(lookback) - 1).where(elig)
    btc = close["BTCUSDT"]
    risk_on = btc > btc.rolling(regime_sma, min_periods=regime_sma).mean()

    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    current = pd.Series(0.0, index=close.columns)
    for i, d in enumerate(close.index):
        if i % rebalance_days == 0:
            current = pd.Series(0.0, index=close.columns)
            if risk_on.loc[d]:
                m = mom.loc[d].dropna()
                picks = m[m > 0].nlargest(hold_k).index
                if len(picks):
                    current[picks] = 1.0 / len(picks)
        if not risk_on.loc[d]:
            current = current * 0.0   # regime break exits immediately, not at next rebalance
        w.loc[d] = current
    return w


def leveraged(w: pd.DataFrame, lev: float) -> pd.DataFrame:
    return w * lev
