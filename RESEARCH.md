# Strategy research: can a bot turn $10 into $1000?

Data: Binance daily candles (via TradingView) for 20 coins, 2017 to 2026-10-17, **including coins that died**
(LUNA, FTT; NEO, FIL and ETC lost 90%+). In-sample is up to 2022, out-of-sample is 2023 onward.
Costs: 0.10% fee and 0.05% slippage per trade, ~11%/yr funding on leverage, 5 USDT minimum order.
Parameters are textbook defaults, not optimised.

## 1. Strategy comparison (1x, no leverage)

| Strategy | Full CAGR | Full max DD | IS Sharpe | **OOS Sharpe** | OOS max DD |
|---|---|---|---|---|---|
| BTC buy & hold | 29.6% | -76.7% | 0.55 | 1.14 | -53.0% |
| Top-10 equal-weight hold | 5.8% | -88.3% | 0.36 | 0.67 | -65.3% |
| **BTC trend (SMA100)** | **45.7%** | **-38.9%** | **1.12** | **1.07** | **-36.8%** |
| Time-series momentum, vol-targeted, 10 coins | 28.2% | -50.1% | 0.87 | 0.87 | -32.2% |
| Cross-sectional momentum, top-3 weekly | 57.2% | -69.8% | 1.34 | 0.61 | -55.5% |
| Breakout v1 (`bot/`, 4 coins) | 9.8% | -10.0% | 1.23 | 0.65 | -9.9% |

- **Winner: BTC trend filter.** Hold BTC while the daily close is above the 100-day SMA, otherwise hold USDT.
  It's the only strategy that keeps a Sharpe above 1 both in and out of sample, and it roughly halves buy & hold's drawdown.
- It is **robust to its one parameter**: SMA 50/75/100/150/200 all give OOS Sharpe 1.04–1.39.
  On ETH it also works, but more weakly (OOS Sharpe 0.71–1.10).
- XS momentum looked best in-sample (23x) and then decayed. Its alt rotation also took the LUNA/FTT-type hits.
- Altcoin baskets underperform BTC once dead coins are included. That's the survivorship-bias trap in most "altcoin bot" backtests.

## 2. The $10 -> $1000 question (100x)

BTC trend at 1x turned $10 into **$242 over 8.5 years** (May 2018 to Oct 2026). Leverage via perps:

| Leverage | $10 became (2018-2026) | Max DD | $10 became (2023-2026 only) |
|---|---|---|---|
| 1x | $242 | -39% | $33 |
| 1.5x | $480 | -56% | $44 |
| 2x | $630 | -70% | $51 |
| 3x | $401 | -90% | $49 |
| 5x | **$1 (wiped)** | -99.5% | $9.6 |

More leverage stops helping beyond 2x. Volatility drag and drawdowns eat the gains, and 5x destroys the account.

Monte Carlo (5,000 block-bootstrapped paths of the strategy's own daily returns):

| Horizon | Leverage | P(reach $1000) | P(lose 90%+) | Median result |
|---|---|---|---|---|
| 3 yr | 1x | 0.0% | 0.0% | $31 |
| 3 yr | 2x | 4.9% | 1.2% | $48 |
| 3 yr | 3x | 14.3% | 13.2% | $42 |
| 5 yr | 1x | 1.1% | 0.0% | $67 |
| 5 yr | 2x | 22.6% | 2.1% | $134 |
| 5 yr | 3x | 33.7% | 17.8% | $109 |
| 5 yr | 5x | 23.6% | **69.4%** | $3 |

This is optimistic: it resamples a history that includes the 2020–21 bull run, and daily bars miss intraday liquidation wicks.

**Conclusion:** no tested strategy reliably does 100x. The realistic target with the best strategy is
roughly 30–45% a year at 1x. 2x leverage over 5 years gives about a 1-in-4 chance at 100x, with a -70% drawdown along the way.
Anything that claims 100x reliably in a backtest is overfit or hiding ruin risk.

## 3. Practical constraint with $10

Binance's minimum order is 5 USDT, so a $10 account can hold at most one position at a time. Multi-coin
strategies can't be run at this size. They need roughly $200+ to place every leg. BTC trend needs one position, so it works at $10.

## Sources

- AdaptiveTrend preprint (crypto trend following, unreviewed): https://arxiv.org/abs/2602.11708v1
- Momentum in crypto, time-series vs cross-sectional: https://www.journals.vu.lt/BATP/en/article/view/44540
- Time-series and cross-sectional momentum in crypto: https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf
- Perpetual futures pricing and funding: https://arxiv.org/html/2212.06888v5
- Funding-rate arbitrage failure modes: https://athenum.mataroa.blog/blog/funding-rate-arbitrage-how-the-perp-spot-basis-pays-and-when-it-does-not/
- Direction gating and volatility targeting for BTC: https://dash.harvard.edu/handle/1/42758586

Reproduce: `python -m research.run_research` and `python -m research.leverage_study`.
