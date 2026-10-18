"""Trend-following breakout, long only (spot).

Every column is known at the CLOSE of bar t. The backtester and the live runner
act on it at the OPEN of bar t+1, so there is no lookahead.
"""
import pandas as pd

from .config import StrategyConfig
from .indicators import atr, ema, prior_high


def compute_signals(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    out["ema_regime"] = ema(out["close"], cfg.regime_ema)
    out["atr"] = atr(out, cfg.atr_period)
    out["breakout_level"] = prior_high(out["high"], cfg.breakout_lookback)

    in_regime = out["close"] > out["ema_regime"]
    out["entry_signal"] = in_regime & (out["close"] > out["breakout_level"])
    out["regime_exit"] = (~in_regime) if cfg.exit_on_regime_break else False
    out["ready"] = out[["ema_regime", "atr", "breakout_level"]].notna().all(axis=1)
    out.loc[~out["ready"], ["entry_signal", "regime_exit"]] = False
    return out
