"""Position sizing and portfolio-level risk limits."""
from .config import RiskConfig


def drawdown_multiplier(equity: float, peak: float, cfg: RiskConfig) -> float:
    """1.0 normally, reduced past the throttle level, 0 past the kill level."""
    dd = 1 - equity / peak if peak > 0 else 0.0
    if dd >= cfg.dd_kill_level:
        return 0.0
    if dd >= cfg.dd_throttle_level:
        return cfg.dd_throttle_factor
    return 1.0


def position_size(
    equity: float,
    peak_equity: float,
    entry_price: float,
    stop_price: float,
    gross_exposure: float,
    cash: float,
    cfg: RiskConfig,
    fee_rate: float,
) -> float:
    """Units to buy so a stop-out loses ~risk_per_trade of equity, subject to caps."""
    risk_per_unit = entry_price - stop_price
    if risk_per_unit <= 0 or entry_price <= 0:
        return 0.0
    mult = drawdown_multiplier(equity, peak_equity, cfg)
    if mult == 0.0:
        return 0.0

    qty = equity * cfg.risk_per_trade * mult / risk_per_unit
    max_notional = min(
        equity * cfg.max_position_pct,
        equity * cfg.max_gross_exposure - gross_exposure,
        cash / (1 + fee_rate),
    )
    qty = min(qty, max(max_notional, 0.0) / entry_price)
    return max(qty, 0.0)
