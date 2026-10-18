# crypto-trading-bot

Systematic crypto trading bot. Current stage: **research / backtesting only. Not live, not paper-trading yet.**

## Strategy v1: trend-following breakout (spot, long only)

| Rule | Value |
|---|---|
| Universe | BTC, ETH, SOL, BNB (USDT spot, daily bars) |
| Regime filter | Close > EMA(200) |
| Entry | Close > highest high of prior 20 bars, filled at **next bar's open** |
| Stop | 3 x ATR(20) below entry, trailed up at close - 3 x ATR, never lowered |
| Extra exit | Close < EMA(200), exits at next open |
| Sizing | 1% equity risk per trade, max 25% notional per coin, no leverage |
| Drawdown control | Risk halved past 20% DD, no new entries past 35% DD |
| Costs | 0.10% fee per side and 0.05% slippage on every fill |

All parameters live in `bot/config.py`.

## Results (Binance daily data from TradingView, 2017-08 to 2026-10-17)

| Period | CAGR | Max DD | Sharpe | Trades | Expectancy | B&H CAGR | B&H Max DD |
|---|---|---|---|---|---|---|---|
| Full | 9.8% | -10.0% | 1.00 | 139 | +0.66R | 69.9% | -78.6% |
| In-sample (to 2022) | 12.6% | -7.2% | 1.23 | 66 | +1.03R | 100.4% | -78.6% |
| **Out-of-sample (2023+)** | **6.0%** | **-9.9%** | **0.65** | 73 | +0.32R | 53.3% | -65.8% |

Parameter sweep (24 combinations of lookback, ATR multiple and EMA): **24/24 profitable** both in-sample and out-of-sample. That means the edge isn't a single lucky parameter set.

### What the numbers say

- The edge is real but small. Positive expectancy holds across every parameter set and out of sample.
- The edge is **decaying**: expectancy fell from 1.03R to 0.32R and Sharpe from 1.23 to 0.65 after 2022.
- **Out of sample it loses to plain buy & hold, even risk-adjusted** (Sharpe 0.65 vs 0.99). Its value is drawdown control (-10% vs -66%), not returns.
- Average exposure is only about 8%. The 1% risk with 3-ATR stops makes positions small, so most capital sits idle. That's the main lever to investigate next.

## Layout

```
bot/config.py       parameters
bot/indicators.py   EMA, ATR (Wilder), prior-N high
bot/strategy.py     signals, all known at bar close
bot/risk.py         position sizing and drawdown throttle
bot/backtest.py     portfolio event-loop backtester
bot/metrics.py      CAGR, DD, Sharpe, R-multiples, buy & hold benchmark
run_backtest.py     full / IS / OOS report and parameter sweep -> results/
tests/              lookahead, next-open fills, gap-through-stop, max loss per trade
```

```
pip install -r requirements.txt
python run_backtest.py
python -m pytest -q
```

## Known limitations

- Daily bars only. Intrabar order of high and low is unknown, so stops are assumed to be hit at the stop price unless the bar gaps through it.
- 4 coins means a small sample, and survivorship bias: these coins are winners chosen in hindsight.
- No funding or borrow costs, because it's spot only.
- No live data feed or exchange execution yet. Next steps: paper trading on testnet via ccxt, then a VPS deployment.
