"""
simulator.py - Dummy / paper-trading market feed for offline testing.

It exposes the SAME interface as the live Dhan feed (dhan_feed.py), so the
strategy can be tested without a real Dhan account and without real money.

Run it with:
    python main.py --mode sim
    python main.py --mode sim --scenario up     # trending-up market
    python main.py --mode sim --scenario down   # trending-down market
    python main.py --mode sim --scenario mixed  # mixed / choppy market
"""
import logging
import random

log = logging.getLogger("sim")


class SimMarket:
    """Random-walk simulated price for YESBANK with day high/low tracking."""

    def __init__(self, cfg, seed=None, scenario="mixed"):
        self.cfg = cfg
        self.rng = random.Random(seed if seed is not None else cfg.SIM_SEED)
        self.scenario = scenario
        self.price = float(cfg.SIM_START_PRICE)
        self.day_open = self.price
        self.day_high = self.price
        self.day_low = self.price
        self.ticks = 0

    def _weights(self):
        return {
            "mixed": (0.42, 0.33, 0.25),
            "up":    (0.80, 0.10, 0.10),
            "down":  (0.10, 0.80, 0.10),
        }.get(self.scenario, (0.42, 0.33, 0.25))

    def tick(self):
        """Advance the simulated price one step and return the new LTP."""
        self.ticks += 1
        w_up, w_down, w_flat = self._weights()
        regime = self.rng.choices(["up", "down", "flat"], [w_up, w_down, w_flat])[0]

        if regime == "up":
            delta = self.rng.gauss(self.cfg.SIM_UPTREND_BIAS * 3, self.cfg.SIM_VOLATILITY)
        elif regime == "down":
            delta = -self.rng.gauss(self.cfg.SIM_UPTREND_BIAS, self.cfg.SIM_VOLATILITY)
        else:
            delta = self.rng.gauss(0.0, self.cfg.SIM_VOLATILITY * 0.5)

        # Mean reversion keeps the simulated price inside a believable band.
        drift_back = (self.day_open - self.price) * self.cfg.SIM_MEAN_REVERSION
        self.price = round(max(0.5, self.price * (1 + delta) + drift_back), 2)
        self.day_high = round(max(self.day_high, self.price), 2)
        self.day_low = round(min(self.day_low, self.price), 2)
        return self.price


class SimFeed:
    """Paper-trading feed built on top of SimMarket."""

    def __init__(self, cfg, market, slippage=None):
        self.cfg = cfg
        self.market = market
        self.slippage = slippage if slippage is not None else cfg.SIM_SELL_SLIPPAGE
        self._pending = {}
        self._order_seq = 0

    # ------------------------- market data ----------------------------- #
    def get_quote(self):
        ltp = self.market.tick()
        return {
            "ltp": ltp,
            "day_high": self.market.day_high,
            "day_low": self.market.day_low,
        }

    # ------------------------- orders ---------------------------------- #
    def place_buy_limit(self, price, qty):
        self._order_seq += 1
        order_id = f"SIM-BUY-{self._order_seq}"
        self._pending[order_id] = {
            "side": "BUY",
            "price": round(price, 2),
            "qty": int(qty),
            "status": "OPEN",
        }
        return order_id

    def wait_for_buy_fill(self, order_id):
        """
        Fill the limit buy when the simulated price dips to (or below) it.
        A per-tick fill probability models real liquidity so that in fast
        trending markets the order still gets filled instead of never.
        """
        max_ticks = max(1, int(self.cfg.ORDER_FILL_TIMEOUT_SEC // max(self.cfg.ORDER_POLL_SEC, 1)))
        for _ in range(max_ticks):
            quote = self.get_quote()
            order = self._pending.get(order_id)
            if order is None:
                return False, None
            if quote["ltp"] <= order["price"] or self.market.rng.random() < self.cfg.SIM_FILL_PROB:
                order["status"] = "FILLED"
                order["fill_price"] = order["price"]
                log.debug("[SIM] buy %s filled @ %.2f", order_id, order["price"])
                return True, order["price"]
        return False, None

    def place_sell_market(self, qty):
        """Fill immediately at the current simulated price minus slippage."""
        quote = self.get_quote()
        fill_price = round(quote["ltp"] - self.slippage, 2)
        log.debug("[SIM] sell %d shares filled @ %.2f", int(qty), fill_price)
        return fill_price
