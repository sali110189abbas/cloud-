import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()  # Wilder smoothing


def prior_high(s: pd.Series, n: int) -> pd.Series:
    """Highest value of the previous n bars, excluding the current bar (no lookahead)."""
    return s.rolling(n, min_periods=n).max().shift(1)
