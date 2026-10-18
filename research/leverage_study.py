"""Two questions:
1. Is BTC-trend robust to its one parameter (SMA length) and does it work on ETH?
2. What does it take to turn $10 into $1000, and what is the chance of blowing up?
   Historical run at 1x-5x leverage, then a block-bootstrap Monte Carlo of the
   strategy's daily returns to estimate P(hit $1000) vs P(ruin) over 3 and 5 years.

    python -m research.leverage_study
"""
import glob
import os

import numpy as np
import pandas as pd

from . import strategies as S
from .engine import Costs, load_universe, run, panel
from .run_research import stats

IS_END, OOS_START = "2022-12-31", "2023-01-01"


def asset_trend(data, sym, sma):
    close = panel(data, "close")
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    c = close[sym]
    w[sym] = (c > c.rolling(sma, min_periods=sma).mean()).astype(float)
    return w


def bootstrap_paths(daily_ret: np.ndarray, days: int, n_paths: int, block: int = 30, seed: int = 7):
    """Stationary-ish block bootstrap: keeps volatility clustering / trend runs."""
    rng = np.random.default_rng(seed)
    n = len(daily_ret)
    out = np.empty((n_paths, days))
    for p in range(n_paths):
        pos = 0
        while pos < days:
            start = rng.integers(0, n - block)
            take = min(block, days - pos)
            out[p, pos:pos + take] = daily_ret[start:start + take]
            pos += take
    return out


def main():
    syms = sorted(os.path.basename(f).split("_")[0] for f in glob.glob("data/*_1D.csv"))
    data = load_universe("data", syms)
    costs = Costs()

    print("=== 1. Robustness: trend filter, SMA length x asset (1x, $10k) ===")
    rows = []
    for sym in ["BTCUSDT", "ETHUSDT"]:
        for sma in [50, 75, 100, 150, 200]:
            w = asset_trend(data, sym, sma)
            for period, kw in [("IS", {"start": "2018-05-01", "end": IS_END}), ("OOS", {"start": OOS_START})]:
                st = stats(run(data, w, costs=costs, **kw).equity)
                rows.append({"asset": sym, "sma": sma, "period": period, "cagr": st["cagr"],
                             "max_dd": st["max_dd"], "sharpe": st["sharpe"]})
    rob = pd.DataFrame(rows).pivot_table(index=["asset", "sma"], columns="period",
                                         values=["cagr", "max_dd", "sharpe"])
    print((rob * pd.Series({c: 100 if c[0] != "sharpe" else 1 for c in rob.columns})).round(2).to_string())

    print("\n=== 2a. Historical: BTC trend SMA100 with leverage (perps, liquidation at lows) ===")
    base = asset_trend(data, "BTCUSDT", 100)
    lev_rows = []
    for lev in [1, 1.5, 2, 3, 5]:
        for period, kw in [("FULL", {"start": "2018-05-01"}), ("OOS", {"start": OOS_START})]:
            res = run(data, base * lev, initial=10.0, costs=Costs(min_notional=5.0), liquidation_floor=0.0, **kw)
            st = stats(res.equity)
            lev_rows.append({"leverage": lev, "period": period, "final_$": res.equity.iloc[-1],
                             "cagr": st["cagr"], "max_dd": st["max_dd"], "liquidated": res.ruined})
    print(pd.DataFrame(lev_rows).to_string(index=False, formatters={
        "final_$": "{:,.2f}".format, "cagr": "{:.1%}".format, "max_dd": "{:.1%}".format}))

    print("\n=== 2b. Monte Carlo: P($10 -> $1000) vs P(lose 90%+), 5,000 paths ===")
    # use 1x daily returns of the strategy; leverage applied per path with daily funding
    res1 = run(data, base, initial=10_000.0, costs=costs, start="2018-05-01")
    r = res1.equity.pct_change().dropna().to_numpy()
    in_mkt = res1.weights["BTCUSDT"].iloc[1:].to_numpy() > 0.5
    mc_rows = []
    for years in [3, 5]:
        days = 365 * years
        idx_paths = bootstrap_paths(np.arange(len(r)).astype(float), days, 5000)
        idx_paths = idx_paths.astype(int)
        R, M = r[idx_paths], in_mkt[idx_paths]
        for lev in [1, 2, 3, 5]:
            daily = lev * R - np.where(M, (lev - 1) * costs.funding_daily, 0.0)
            daily = np.maximum(daily, -1.0)
            eq = 10.0 * np.cumprod(1 + daily, axis=1)
            dead = (eq <= 1.0).any(axis=1)                       # -90% = effectively wiped
            hit = (eq >= 1000.0).any(axis=1)
            first_hit = np.where(eq >= 1000, np.arange(days), days).min(axis=1)
            first_dead = np.where(eq <= 1.0, np.arange(days), days).min(axis=1)
            mc_rows.append({"years": years, "leverage": lev,
                            "P(hit $1000)": (hit & (first_hit < first_dead)).mean(),
                            "P(wiped -90%)": dead.mean(),
                            "median_final_$": np.median(eq[:, -1]),
                            "P(lose money)": (eq[:, -1] < 10).mean()})
    print(pd.DataFrame(mc_rows).to_string(index=False, formatters={
        "P(hit $1000)": "{:.1%}".format, "P(wiped -90%)": "{:.1%}".format,
        "median_final_$": "{:,.0f}".format, "P(lose money)": "{:.1%}".format}))
    print("\nNote: daily bars understate intraday liquidation risk for leverage >= 3x,"
          " so the real wipe-out odds at high leverage are WORSE than shown.")


if __name__ == "__main__":
    main()
