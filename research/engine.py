"""Target-weight portfolio backtester.

A strategy returns a DataFrame of target weights (rows = dates, cols = symbols),
decided at the CLOSE of each date. The engine trades to those weights at the
NEXT bar's OPEN. Sum of weights > 1 means leverage (perps).

Costs and constraints modelled:
  * fee + slippage on every unit of turnover
  * funding on the borrowed part of a leveraged book, charged daily
  * minimum order notional (Binance: 5 USDT); smaller adjustments are skipped
  * delisted coins are force-sold at their last close
  * ruin: if equity marked at the day's LOWS falls to the liquidation floor,
    the account is dead (models a liquidation intraday, not just at close)
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Costs:
    fee: float = 0.001             # Binance spot taker per side
    slippage: float = 0.0005
    funding_daily: float = 0.0003  # ~11%/yr, typical perp funding paid by longs
    min_notional: float = 5.0
    rebalance_band: float = 0.02   # ignore weight changes smaller than this


def load_universe(data_dir: str, symbols: list, drop_last_bar: bool = True) -> dict:
    """Load OHLCV. A symbol with a multi-day hole was delisted (LUNA, FTT): it is
    cut at the hole so the backtest exits there instead of splicing on a relisted coin."""
    out = {}
    for s in symbols:
        df = pd.read_csv(f"{data_dir}/{s}_1D.csv", parse_dates=["time"]).set_index("time").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        gaps = np.where(df.index.to_series().diff().dt.days > 3)[0]
        if len(gaps):
            df = df.iloc[: gaps[0]]
        elif drop_last_bar:
            df = df.iloc[:-1]
        out[s] = df
    return out


def panel(data: dict, field: str) -> pd.DataFrame:
    return pd.DataFrame({s: df[field] for s, df in data.items()}).sort_index()


@dataclass
class Result:
    equity: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    ruined: bool


def run(data: dict, target_w: pd.DataFrame, initial: float = 10_000.0, costs: Costs = Costs(),
        start=None, end=None, liquidation_floor: float = 0.0) -> Result:
    opens = panel(data, "open")
    idx = opens.index
    if start is not None:
        idx = idx[idx >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        idx = idx[idx <= pd.Timestamp(end, tz="UTC")]
    syms = list(opens.columns)

    O = opens.loc[idx].to_numpy()
    L = panel(data, "low").reindex(index=idx, columns=syms).to_numpy()
    has_bar = ~np.isnan(O)
    O_ff = pd.DataFrame(O).ffill().to_numpy()
    # weights decided at close t trade at open t+1
    W = (target_w.reindex(columns=syms).reindex(idx).shift(1)
         .fillna(0.0).to_numpy())
    last_i = np.array([np.searchsorted(idx, data[s].index[-1], side="right") - 1 for s in syms])
    final_close = np.array([data[s]["close"].iloc[-1] for s in syms])

    rate = costs.fee + costs.slippage
    n, k = O.shape
    units = np.zeros(k)
    cash = float(initial)
    eq = np.full(n, np.nan)
    wts = np.zeros((n, k))
    tov = np.zeros(n)
    ruined = False

    for t in range(n):
        # delisted: sell at the final close
        dead = (t > last_i) & (units != 0)
        if dead.any():
            for j in np.where(dead)[0]:
                cash += units[j] * final_close[j] - abs(units[j] * final_close[j]) * rate
                units[j] = 0.0

        px = np.where(np.isnan(O_ff[t]), 0.0, O_ff[t])
        equity = cash + units @ px
        if equity <= max(liquidation_floor * initial, 0.0):
            ruined, eq[t] = True, max(equity, 0.0)
            break

        cur_w = units * px / equity
        target = W[t]
        diff = np.where(has_bar[t], target - cur_w, 0.0)
        notional = np.abs(diff) * equity
        closing = has_bar[t] & (target == 0) & (units != 0)
        trade = has_bar[t] & (((np.abs(diff) >= costs.rebalance_band) & (notional >= costs.min_notional)) | closing)
        if trade.any():
            d_units = np.where(trade, diff * equity / np.where(px > 0, px, 1), 0.0)
            d_units = np.where(closing, -units, d_units)
            traded = np.abs(d_units * px)
            units += d_units
            cash -= d_units @ px + traded.sum() * rate
            tov[t] = traded.sum() / equity

        # funding on the borrowed part of the book
        gross = np.abs(units) @ px
        eq_open = cash + units @ px
        cash -= max(gross - max(eq_open, 0.0), 0.0) * costs.funding_daily

        # liquidation check at the day's lows (longs only, conservative)
        low_px = np.where(np.isnan(L[t]), px, L[t])
        if gross > eq_open and cash + units @ np.where(units > 0, low_px, px) <= liquidation_floor * initial:
            ruined, eq[t] = True, 0.0
            break

        # equity is marked at each open, so returns are open-to-open
        eq[t] = cash + units @ px
        wts[t] = units * px / eq[t] if eq[t] > 0 else 0.0

    equity = pd.Series(eq, index=idx).dropna()
    if ruined:
        equity = pd.concat([equity, pd.Series(0.0, index=idx[len(equity):])])
    return Result(equity, pd.DataFrame(wts, index=idx, columns=syms), pd.Series(tov, index=idx), ruined)
