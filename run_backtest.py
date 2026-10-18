"""Run the strategy: full history, in-sample vs out-of-sample, and a parameter
sensitivity sweep. Outputs go to results/.

    python run_backtest.py
"""
import copy
import itertools
import logging
import os

import pandas as pd

from bot.backtest import attach_signals, load_raw, run_backtest
from bot.config import BacktestConfig
from bot.metrics import buy_and_hold, equity_stats, format_stats, trade_stats

IS_END = "2022-12-31"     # parameters were fixed before looking at anything after this
OOS_START = "2023-01-01"


def report(name, data, cfg, start=None, end=None):
    res = run_backtest(data, cfg, start, end)
    bh = buy_and_hold(data, cfg.symbols, res.equity.index, cfg.initial_equity)
    print(f"\n=== {name}  ({res.equity.index[0].date()} -> {res.equity.index[-1].date()}) ===")
    print("Strategy:")
    print(format_stats({**equity_stats(res.equity), "avg_exposure": res.exposure.mean(),
                        **trade_stats(res.trades)}))
    print("Equal-weight buy & hold:")
    print(format_stats(equity_stats(bh)))
    return res, bh


def sweep(raw, base_cfg, start=None, end=None):
    rows = []
    for lb, m, ema_n in itertools.product([10, 20, 40, 55], [2.0, 3.0, 4.0], [100, 200]):
        cfg = copy.deepcopy(base_cfg)
        cfg.strategy.breakout_lookback, cfg.strategy.stop_atr_mult, cfg.strategy.regime_ema = lb, m, ema_n
        res = run_backtest(attach_signals(raw, cfg), cfg, start, end)
        st = equity_stats(res.equity)
        rows.append({"lookback": lb, "atr_mult": m, "regime_ema": ema_n,
                     "cagr": st["cagr"], "max_dd": st["max_drawdown"], "sharpe": st["sharpe"],
                     "trades": len(res.trades)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs("results", exist_ok=True)
    cfg = BacktestConfig()
    raw = load_raw(cfg)
    data = attach_signals(raw, cfg)

    full, full_bh = report("FULL HISTORY", data, cfg)
    report("IN-SAMPLE", data, cfg, end=IS_END)
    oos, _ = report("OUT-OF-SAMPLE", data, cfg, start=OOS_START)

    full.trades.to_csv("results/trades.csv", index=False)
    pd.DataFrame({"strategy": full.equity, "buy_hold": full_bh,
                  "exposure": full.exposure}).to_csv("results/equity.csv")

    print("\n=== Per-symbol (full history) ===")
    print(full.trades.groupby("symbol").agg(trades=("pnl", "size"), pnl=("pnl", "sum"),
                                            win_rate=("pnl", lambda x: (x > 0).mean()),
                                            expectancy_R=("r_multiple", "mean")).round(2))

    print("\n=== Yearly returns ===")
    yearly = pd.DataFrame({
        "strategy": full.equity.resample("YE").last().pct_change().fillna(
            full.equity.resample("YE").last().iloc[0] / cfg.initial_equity - 1),
        "buy_hold": full_bh.resample("YE").last().pct_change().fillna(
            full_bh.resample("YE").last().iloc[0] / cfg.initial_equity - 1),
    })
    print((yearly * 100).round(1).to_string())

    # sensitivity: a robust edge should hold up across neighbouring parameters
    for label, kw in [("IN-SAMPLE", {"end": IS_END}), ("OUT-OF-SAMPLE", {"start": OOS_START})]:
        sw = sweep(raw, cfg, **kw)
        sw.to_csv(f"results/sweep_{label.lower()}.csv", index=False)
        print(f"\n=== Parameter sweep {label}: {len(sw)} combos ===")
        print(f"  profitable combos: {(sw.cagr > 0).sum()}/{len(sw)}   "
              f"median CAGR {sw.cagr.median():.1%}   median maxDD {sw.max_dd.median():.1%}   "
              f"median Sharpe {sw.sharpe.median():.2f}")
        print(sw.sort_values("sharpe", ascending=False).head(5).round(3).to_string(index=False))
