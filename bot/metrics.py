import numpy as np
import pandas as pd

PERIODS_PER_YEAR = 365  # crypto trades every day


def equity_stats(equity: pd.Series) -> dict:
    if len(equity) < 2:
        return {}
    rets = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    total = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 else np.nan
    dd = equity / equity.cummax() - 1
    vol = rets.std() * np.sqrt(PERIODS_PER_YEAR)
    downside = rets[rets < 0].std() * np.sqrt(PERIODS_PER_YEAR)
    return {
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": dd.min(),
        "volatility": vol,
        "sharpe": rets.mean() * PERIODS_PER_YEAR / vol if vol > 0 else np.nan,
        "sortino": rets.mean() * PERIODS_PER_YEAR / downside if downside > 0 else np.nan,
        "calmar": cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
    }


def trade_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
    gross_loss = -losses.pnl.sum()
    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "avg_win_R": wins.r_multiple.mean() if len(wins) else 0.0,
        "avg_loss_R": losses.r_multiple.mean() if len(losses) else 0.0,
        "expectancy_R": trades.r_multiple.mean(),
        "profit_factor": wins.pnl.sum() / gross_loss if gross_loss > 0 else np.inf,
        "avg_bars_held": trades.bars_held.mean(),
        "largest_loss_R": trades.r_multiple.min(),
    }


def buy_and_hold(data: dict, symbols: list, index: pd.DatetimeIndex, initial: float) -> pd.Series:
    """Equal-weight buy & hold across symbols over the same dates (no rebalancing).
    Symbols that list later are held in cash until their first bar."""
    alloc = initial / len(symbols)
    parts = []
    for s in symbols:
        close = data[s]["close"].reindex(index).ffill()
        first = close.first_valid_index()
        if first is None:
            parts.append(pd.Series(alloc, index=index))
            continue
        units = alloc / close.loc[first]
        parts.append((close * units).fillna(alloc))
    return sum(parts)


def format_stats(stats: dict) -> str:
    pct = {"total_return", "cagr", "max_drawdown", "volatility", "win_rate"}
    lines = []
    for k, v in stats.items():
        if isinstance(v, float) and k in pct:
            lines.append(f"  {k:<16}{v:>10.1%}")
        elif isinstance(v, float):
            lines.append(f"  {k:<16}{v:>10.2f}")
        else:
            lines.append(f"  {k:<16}{v:>10}")
    return "\n".join(lines)
