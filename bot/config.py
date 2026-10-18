"""All tunable parameters in one place. Change values here, not inside the logic."""
from dataclasses import dataclass, field


@dataclass
class StrategyConfig:
    regime_ema: int = 200          # only long when close > EMA(regime_ema)
    breakout_lookback: int = 20    # enter on close above prior N-bar high
    atr_period: int = 20
    stop_atr_mult: float = 3.0     # initial + trailing stop distance in ATRs
    exit_on_regime_break: bool = True  # also exit if close < regime EMA


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01       # fraction of equity lost if the stop is hit
    max_position_pct: float = 0.25     # max notional per position as fraction of equity
    max_gross_exposure: float = 1.0    # spot, no leverage: total notional <= equity
    dd_throttle_level: float = 0.20    # drawdown from peak at which risk is cut
    dd_throttle_factor: float = 0.5    # risk multiplier while beyond the throttle level
    dd_kill_level: float = 0.35        # drawdown at which no new entries are taken


@dataclass
class CostConfig:
    fee_rate: float = 0.001        # 0.10% per side (Binance spot taker, no BNB discount)
    slippage: float = 0.0005       # 0.05% adverse fill on every market order


@dataclass
class BacktestConfig:
    initial_equity: float = 10_000.0
    symbols: list = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"])
    data_dir: str = "data"
    timeframe: str = "1D"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
