"""BTC trend bot for Binance spot: hold BTC while the daily close is above its
100-day SMA, otherwise hold USDT. Run once a day, a few minutes after 00:00 UTC.

Modes (env BOT_MODE):
  paper   (default) real Binance prices, simulated fills, balances in state/paper.json
  testnet Binance spot testnet, needs testnet API keys
  live    real money. Also requires BOT_CONFIRM_LIVE=yes

Safety:
  * a file named STOP in the state dir disables all trading
  * each daily candle is processed once (idempotent if cron fires twice)
  * aborts if the newest closed candle is stale (exchange/data problem)
  * a single order is capped at MAX_ORDER_USDT
  * every decision, order and error is logged; fills go to trades.csv

    python -m live.trend_bot
"""
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("trend_bot")


class Settings:
    def __init__(self, env=os.environ):
        self.mode = env.get("BOT_MODE", "paper")
        self.symbol = env.get("BOT_SYMBOL", "BTC/USDT")
        self.sma = int(env.get("BOT_SMA", "100"))
        self.state_dir = env.get("BOT_STATE_DIR", "state")
        self.max_order_usdt = float(env.get("MAX_ORDER_USDT", "1000"))
        self.min_notional = float(env.get("MIN_NOTIONAL_USDT", "5"))
        self.paper_start_usdt = float(env.get("PAPER_START_USDT", "10"))
        self.api_key = env.get("BINANCE_API_KEY", "")
        self.api_secret = env.get("BINANCE_API_SECRET", "")
        self.confirm_live = env.get("BOT_CONFIRM_LIVE", "") == "yes"
        if self.mode not in ("paper", "testnet", "live"):
            raise ValueError(f"unknown BOT_MODE {self.mode}")
        if self.mode == "live" and not self.confirm_live:
            raise ValueError("live mode needs BOT_CONFIRM_LIVE=yes")
        if self.mode in ("testnet", "live") and not (self.api_key and self.api_secret):
            raise ValueError("BINANCE_API_KEY / BINANCE_API_SECRET not set")


def retry(fn, *args, attempts=5, base_delay=2.0, **kwargs):
    """Retry transient exchange/network errors with exponential backoff."""
    import ccxt
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
            if i == attempts - 1:
                raise
            delay = base_delay * 2 ** i
            log.warning("transient error %s, retry %d/%d in %.0fs", e, i + 1, attempts, delay)
            time.sleep(delay)


def closed_daily_closes(exchange, symbol, n, now=None):
    """Last n CLOSED daily candles as [(open_time_utc, close)], forming candle dropped."""
    now = now or datetime.now(timezone.utc)
    rows = retry(exchange.fetch_ohlcv, symbol, "1d", limit=n + 2)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    closed = [(datetime.fromtimestamp(r[0] / 1000, timezone.utc), r[4]) for r in rows]
    closed = [c for c in closed if c[0] < today]
    return closed[-n:]


def decide(closes, sma):
    """1.0 = hold BTC, 0.0 = hold USDT. Needs at least sma closed candles."""
    if len(closes) < sma:
        raise ValueError(f"need {sma} candles, got {len(closes)}")
    window = [c for _, c in closes[-sma:]]
    return 1.0 if closes[-1][1] > sum(window) / sma else 0.0


class PaperExchange:
    """Simulated fills against real public prices. Charges 0.1% fee + 0.05% slippage."""
    FEE, SLIP = 0.001, 0.0005

    def __init__(self, public_exchange, path, start_usdt):
        self.pub, self.path = public_exchange, path
        if os.path.exists(path):
            with open(path) as f:
                self.bal = json.load(f)
        else:
            self.bal = {"USDT": start_usdt, "BTC": 0.0}
            self._save()

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.bal, f)
        os.replace(tmp, self.path)  # atomic: a crash can't leave a half-written file

    def fetch_ohlcv(self, *a, **k):
        return self.pub.fetch_ohlcv(*a, **k)

    def fetch_ticker(self, symbol):
        return self.pub.fetch_ticker(symbol)

    def fetch_balance(self):
        return {"free": dict(self.bal)}

    def amount_to_precision(self, symbol, amount):
        # truncate like Binance's LOT_SIZE step, never round up past the balance
        return f"{int(amount * 1e6) / 1e6:.6f}"

    def create_market_buy_order_with_cost(self, symbol, cost):
        px = self.pub.fetch_ticker(symbol)["last"] * (1 + self.SLIP)
        qty = cost * (1 - self.FEE) / px
        self.bal["USDT"] -= cost
        self.bal["BTC"] += qty
        self._save()
        return {"id": f"paper-{int(time.time())}", "side": "buy", "average": px, "filled": qty, "cost": cost}

    def create_market_sell_order(self, symbol, amount):
        amount = float(amount)
        px = self.pub.fetch_ticker(symbol)["last"] * (1 - self.SLIP)
        self.bal["BTC"] -= amount
        self.bal["USDT"] += amount * px * (1 - self.FEE)
        self._save()
        return {"id": f"paper-{int(time.time())}", "side": "sell", "average": px, "filled": amount,
                "cost": amount * px}


def make_exchange(cfg: Settings):
    import ccxt
    if cfg.mode == "paper":
        return PaperExchange(ccxt.binance({"enableRateLimit": True}),
                             os.path.join(cfg.state_dir, "paper.json"), cfg.paper_start_usdt)
    ex = ccxt.binance({"apiKey": cfg.api_key, "secret": cfg.api_secret, "enableRateLimit": True,
                       "options": {"defaultType": "spot"}})
    if cfg.mode == "testnet":
        ex.set_sandbox_mode(True)
    return ex


def rebalance(exchange, cfg: Settings, target: float):
    base, quote = cfg.symbol.split("/")
    free = retry(exchange.fetch_balance)["free"]
    base_amt, quote_amt = float(free.get(base) or 0), float(free.get(quote) or 0)
    price = retry(exchange.fetch_ticker, cfg.symbol)["last"]
    base_val = base_amt * price
    log.info("balances: %s=%.8f (%.2f USDT) %s=%.2f price=%.2f target=%s",
             base, base_amt, base_val, quote, quote_amt, price, target)

    if target == 1.0 and quote_amt >= cfg.min_notional:
        cost = min(quote_amt * 0.998, cfg.max_order_usdt)   # leave a hair for fee rounding
        if cost < cfg.min_notional:
            return None
        log.info("BUY %s with %.2f %s", cfg.symbol, cost, quote)
        return retry(exchange.create_market_buy_order_with_cost, cfg.symbol, cost, attempts=1)
    if target == 0.0 and base_val >= cfg.min_notional:
        amount = min(base_amt, cfg.max_order_usdt / price)
        amount = exchange.amount_to_precision(cfg.symbol, amount)
        log.info("SELL %s %s", amount, base)
        return retry(exchange.create_market_sell_order, cfg.symbol, amount, attempts=1)
    log.info("no trade needed")
    return None


def journal(cfg, candle_day, target, order):
    path = os.path.join(cfg.state_dir, "trades.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["utc_time", "mode", "candle", "target", "side", "price", "filled", "cost", "order_id"])
        w.writerow([datetime.now(timezone.utc).isoformat(), cfg.mode, candle_day, target,
                    order.get("side"), order.get("average"), order.get("filled"), order.get("cost"),
                    order.get("id")])


def run_once(cfg: Settings, exchange, now=None):
    now = now or datetime.now(timezone.utc)
    os.makedirs(cfg.state_dir, exist_ok=True)
    if os.path.exists(os.path.join(cfg.state_dir, "STOP")):
        log.warning("STOP file present, not trading")
        return "stopped"

    state_path = os.path.join(cfg.state_dir, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}

    closes = closed_daily_closes(exchange, cfg.symbol, cfg.sma, now)
    last_day = closes[-1][0]
    if now - last_day > timedelta(days=2):
        log.error("stale data: newest closed candle %s", last_day.date())
        return "stale"
    if state.get("last_candle") == last_day.date().isoformat():
        log.info("candle %s already processed", last_day.date())
        return "already_done"

    target = decide(closes, cfg.sma)
    sma_val = sum(c for _, c in closes[-cfg.sma:]) / cfg.sma
    log.info("candle %s close=%.2f sma%d=%.2f -> target %s",
             last_day.date(), closes[-1][1], cfg.sma, sma_val, "BTC" if target else "USDT")
    order = rebalance(exchange, cfg, target)
    if order:
        journal(cfg, last_day.date().isoformat(), target, order)

    state.update({"last_candle": last_day.date().isoformat(), "target": target,
                  "updated": now.isoformat()})
    tmp = state_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, state_path)
    return "traded" if order else "no_trade"


def main():
    cfg = Settings()
    os.makedirs(cfg.state_dir, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(os.path.join(cfg.state_dir, "bot.log"))])
    log.info("start mode=%s symbol=%s sma=%d", cfg.mode, cfg.symbol, cfg.sma)
    try:
        log.info("result: %s", run_once(cfg, make_exchange(cfg)))
    except Exception:
        log.exception("run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
