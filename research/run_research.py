"""Compare strategies on 20 Binance coins (incl. dead ones: LUNA, FTT),
full period / in-sample / out-of-sample, starting from $10.

    python -m research.run_research
"""
import glob
import os

import numpy as np
import pandas as pd

from . import strategies as S
from .engine import Costs, load_universe, run

IS_END, OOS_START = "2022-12-31", "2023-01-01"
START_CASH = 10.0


def stats(eq: pd.Series) -> dict:
    eq = eq[eq.index >= eq.index[0]]
    r = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    mult = eq.iloc[-1] / eq.iloc[0]
    dd = (eq / eq.cummax() - 1).min()
    sharpe = r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan
    return {"final_$": eq.iloc[-1] * START_CASH / eq.iloc[0], "multiple": mult,
            "cagr": mult ** (1 / yrs) - 1 if mult > 0 else -1.0,
            "max_dd": dd, "sharpe": sharpe}


def main():
    syms = sorted(os.path.basename(f).split("_")[0] for f in glob.glob("data/*_1D.csv"))
    data = load_universe("data", syms)
    costs = Costs()

    strats = {
        "BTC buy&hold": S.btc_hold(data),
        "Top-10 equal-weight hold": S.equal_weight_hold(data),
        "BTC trend (SMA100)": S.btc_trend(data),
        "TS momentum vol-target": S.tsmom_vol_target(data),
        "XS momentum top-3 weekly": S.xs_momentum(data),
    }
    rows = []
    for name, w in strats.items():
        for period, kw in [("FULL", {}), ("IN-SAMPLE", {"end": IS_END}), ("OUT-OF-SAMPLE", {"start": OOS_START})]:
            # start each window once BTC has 200 bars so every strategy is live
            kw = {"start": "2018-05-01", **kw}
            res = run(data, w, initial=10_000.0, costs=costs, **kw)   # edge, free of min-notional limits
            rows.append({"strategy": name, "period": period, **stats(res.equity),
                         "avg_gross": res.weights.abs().sum(axis=1).mean(),
                         "turnover/yr": res.turnover.sum() / ((res.equity.index[-1] - res.equity.index[0]).days / 365.25)})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    for period in ["FULL", "IN-SAMPLE", "OUT-OF-SAMPLE"]:
        print(f"\n=== {period} (start ${START_CASH:.0f}) ===")
        sub = df[df.period == period].drop(columns="period")
        print(sub.to_string(index=False, formatters={
            "final_$": "{:,.0f}".format, "multiple": "{:.1f}x".format, "cagr": "{:.1%}".format,
            "max_dd": "{:.1%}".format, "sharpe": "{:.2f}".format, "avg_gross": "{:.2f}".format,
            "turnover/yr": "{:.1f}".format}))
    os.makedirs("results", exist_ok=True)
    df.to_csv("results/strategy_comparison.csv", index=False)


if __name__ == "__main__":
    main()
