"""Portfolio-level, bar-by-bar backtester.

Execution model (deliberately conservative):
  * Signals are computed on the close of bar t, orders fill at the open of bar t+1.
  * Every fill pays slippage and the taker fee.
  * If a bar opens beyond the stop, the fill is at the open (gap), not the stop.
  * A position entered on a bar can be stopped out on that same bar.
  * Sizing uses equity marked at the previous close (what you would actually know).
"""
import logging
import os
from dataclasses import dataclass

import pandas as pd

from .config import BacktestConfig
from .risk import position_size
from .strategy import compute_signals

log = logging.getLogger(__name__)
MIN_NOTIONAL = 10.0  # exchange minimum order size in USDT


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    exposure: pd.Series


def load_raw(cfg: BacktestConfig, drop_last_bar: bool = True) -> dict:
    """Load OHLCV CSVs. The last bar is dropped by default because the current
    day's candle is still forming."""
    raw = {}
    for sym in cfg.symbols:
        path = os.path.join(cfg.data_dir, f"{sym}_{cfg.timeframe}.csv")
        df = pd.read_csv(path, parse_dates=["time"]).set_index("time").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        raw[sym] = df.iloc[:-1] if drop_last_bar else df
    return raw


def attach_signals(raw: dict, cfg: BacktestConfig) -> dict:
    return {sym: compute_signals(df, cfg.strategy) for sym, df in raw.items()}


def load_data(cfg: BacktestConfig, drop_last_bar: bool = True) -> dict:
    return attach_signals(load_raw(cfg, drop_last_bar), cfg)


def run_backtest(data: dict, cfg: BacktestConfig, start=None, end=None) -> BacktestResult:
    fee, slip = cfg.costs.fee_rate, cfg.costs.slippage
    mult = cfg.strategy.stop_atr_mult

    dates = sorted(set().union(*[df.index for df in data.values()]))
    if start is not None:
        dates = [d for d in dates if d >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        dates = [d for d in dates if d <= pd.Timestamp(end, tz="UTC")]

    cash = cfg.initial_equity
    equity = peak = cfg.initial_equity
    positions: dict = {}
    last_close: dict = {}
    pending_entry: dict = {}   # sym -> ATR at signal bar
    pending_exit: set = set()
    trades, equity_curve, exposure_curve = [], {}, {}

    def close_position(sym, price, when, reason):
        nonlocal cash
        p = positions.pop(sym)
        proceeds = p["qty"] * price * (1 - fee)
        cash += proceeds
        cost = p["qty"] * p["entry_price"] + p["entry_fee"]
        pnl = proceeds - cost
        trades.append({
            "symbol": sym, "entry_time": p["entry_time"], "exit_time": when,
            "entry_price": p["entry_price"], "exit_price": price, "qty": p["qty"],
            "pnl": pnl, "return_pct": pnl / cost,
            "r_multiple": pnl / (p["qty"] * p["risk_per_unit"]),
            "bars_held": p["bars"], "exit_reason": reason,
        })
        log.debug("EXIT %s %s @ %.4f pnl=%.2f (%s)", when.date(), sym, price, pnl, reason)

    for d in dates:
        bars = {s: df.loc[d] for s, df in data.items() if d in df.index}

        # 1) exits decided at the previous close
        for sym in list(pending_exit):
            if sym in positions and sym in bars:
                close_position(sym, bars[sym]["open"] * (1 - slip), d, "regime_exit")
        pending_exit.clear()

        # 2) stop checks on existing positions
        for sym in list(positions):
            if sym not in bars:
                continue
            b, stop = bars[sym], positions[sym]["stop"]
            if b["open"] <= stop:
                close_position(sym, b["open"] * (1 - slip), d, "stop_gap")
            elif b["low"] <= stop:
                close_position(sym, stop * (1 - slip), d, "stop")

        # 3) entries decided at the previous close
        gross = sum(p["qty"] * last_close[s] for s, p in positions.items())
        for sym, sig_atr in sorted(pending_entry.items()):
            if sym in positions or sym not in bars:
                continue
            b = bars[sym]
            entry = b["open"] * (1 + slip)
            stop = entry - mult * sig_atr
            qty = position_size(equity, peak, entry, stop, gross, cash, cfg.risk, fee)
            if qty * entry < MIN_NOTIONAL:
                continue
            entry_fee = qty * entry * fee
            cash -= qty * entry + entry_fee
            gross += qty * entry
            positions[sym] = {"qty": qty, "entry_price": entry, "entry_time": d, "stop": stop,
                              "risk_per_unit": entry - stop, "entry_fee": entry_fee, "bars": 0}
            log.debug("ENTRY %s %s qty=%.6f @ %.4f stop=%.4f", d.date(), sym, qty, entry, stop)
            if b["low"] <= stop:  # stopped out on the entry bar
                close_position(sym, stop * (1 - slip), d, "stop")
        pending_entry.clear()

        # 4) mark to market at the close
        for sym, b in bars.items():
            last_close[sym] = b["close"]
        pos_value = sum(p["qty"] * last_close[s] for s, p in positions.items())
        equity = cash + pos_value
        peak = max(peak, equity)
        equity_curve[d] = equity
        exposure_curve[d] = pos_value / equity if equity > 0 else 0.0

        # 5) trail stops and generate signals for the next open
        for sym, b in bars.items():
            if not b["ready"]:
                continue
            if sym in positions:
                p = positions[sym]
                p["bars"] += 1
                p["stop"] = max(p["stop"], b["close"] - mult * b["atr"])
                if b["regime_exit"]:
                    pending_exit.add(sym)
            elif b["entry_signal"]:
                pending_entry[sym] = b["atr"]

    # mark open positions out at the final close so trade stats are complete
    if dates:
        for sym in list(positions):
            close_position(sym, last_close[sym] * (1 - slip), dates[-1], "end_of_data")

    return BacktestResult(
        equity=pd.Series(equity_curve, name="equity"),
        trades=pd.DataFrame(trades),
        exposure=pd.Series(exposure_curve, name="exposure"),
    )
