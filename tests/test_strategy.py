"""
Unit tests for the trailing-stop strategy using a scripted FakeFeed.
Run with:
    python -m unittest discover -s tests -v
"""
import unittest

from config import Config
from strategy import TrailingTrader


class FakeFeed:
    """Scripted feed: pops LTPs from `quotes`, fills buys instantly, sells at `sell_price`."""

    def __init__(self, quotes=None, sell_price=0.0):
        self.quotes = list(quotes) if quotes else []
        self.sell_price = sell_price
        self.last_ltp = 0.0
        self.buy_price = None
        self.buy_count = 0
        self.sell_count = 0

    def get_quote(self):
        if self.quotes:
            self.last_ltp = self.quotes.pop(0)
        return {"ltp": self.last_ltp, "day_high": self.last_ltp + 1, "day_low": self.last_ltp - 1}

    def place_buy_limit(self, price, qty):
        self.buy_count += 1
        self.buy_price = round(price, 2)
        return f"order-{self.buy_count}"

    def wait_for_buy_fill(self, order_id):
        return True, self.buy_price

    def place_sell_market(self, qty):
        self.sell_count += 1
        return self.sell_price


def make_trader(feed, **overrides):
    cfg = Config()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return TrailingTrader(cfg, feed, sleep_fn=lambda _s: None)


class BuyOrderTest(unittest.TestCase):
    def test_buy_limit_is_ltp_minus_2_paisa(self):
        feed = FakeFeed(quotes=[52.00], sell_price=52.20)
        trader = make_trader(feed)
        trader.run_cycle(1)
        self.assertEqual(feed.buy_price, 51.98)


class TrailingTest(unittest.TestCase):
    def test_stop_trails_up_after_30_paisa_profit_and_exits_on_reversal(self):
        # Buy setup LTP 52.00, then a scripted monitor series.
        feed = FakeFeed(
            quotes=[52.00, 52.10, 52.25, 52.40, 52.45, 52.60, 52.20],
            sell_price=52.20,
        )
        trader = make_trader(feed)
        record = trader.run_cycle(1)

        self.assertEqual(feed.buy_price, 51.98)          # LTP - 2 paisa
        state = trader._last_monitor_state
        self.assertEqual(state["peak"], 52.60)            # tracked the top
        self.assertEqual(state["stop"], 52.30)            # 30 paisa below peak
        self.assertEqual(state["trail_updates"], 3)       # 52.40 -> 52.45 -> 52.60
        self.assertEqual(record["outcome"], "PROFIT")
        self.assertEqual(record["pnl"], 2.2)              # (52.20 - 51.98) * 10

    def test_no_trailing_below_activation_profit(self):
        # Price rises but never reaches +30 paisa -> stop stays at buy - 30 paisa.
        feed = FakeFeed(quotes=[52.00, 52.05, 52.12, 52.18, 51.60], sell_price=51.60)
        trader = make_trader(feed)
        record = trader.run_cycle(1)

        state = trader._last_monitor_state
        self.assertEqual(state["peak"], 52.18)
        self.assertEqual(state["stop"], 51.68)            # never trailed
        self.assertEqual(state["trail_updates"], 0)
        self.assertEqual(record["outcome"], "LOSS")
        self.assertEqual(record["pnl"], -3.8)             # (51.60 - 51.98) * 10


class LossStopTest(unittest.TestCase):
    def test_stops_after_three_losses(self):
        # Every cycle: buy-phase LTP 50.00, monitor immediately drops to 49.50.
        feed = FakeFeed(
            quotes=[50.00, 49.50, 50.00, 49.50, 50.00, 49.50],
            sell_price=49.50,
        )
        trader = make_trader(feed)
        trader.run()

        self.assertEqual(len(trader.results), 3)
        self.assertEqual(trader.loss_count, 3)
        self.assertTrue(all(r["outcome"] == "LOSS" for r in trader.results))
        self.assertEqual(trader.stop_reason, "stopped after 3 losing trades")

    def test_happy_run_completes_all_cycles_without_triggering_stop(self):
        # Every cycle is profitable: buy-phase LTP 50.00, monitor rises to 50.60.
        # 52.60 -> wait, use a simpler repeating profitable series.
        feed = FakeFeed(
            quotes=[50.00, 50.60] * 3,
            sell_price=50.60,
        )
        trader = make_trader(feed, MAX_CYCLES=3)
        trader.run()

        self.assertEqual(len(trader.results), 3)
        self.assertTrue(all(r["outcome"] == "PROFIT" for r in trader.results))
        self.assertEqual(trader.loss_count, 0)


class ScriptedScenarioTest(unittest.TestCase):
    def test_market_stuck_5_paisa_below_buy_never_triggers(self):
        # Buy fills at 20.93, market stuck at 20.88 for 10 scans.
        # 20.88 is only 5 paisa below buy -> stop (20.63) is NOT hit, so the
        # bot just keeps scanning until the force square-off cap.
        feed = FakeFeed(quotes=[20.95] + [20.88] * 10, sell_price=20.87)
        trader = make_trader(feed, MAX_MONITOR_SCANS=10)
        record = trader.run_cycle(1)

        state = trader._last_monitor_state
        self.assertEqual(feed.buy_price, 20.93)        # LTP - 2 paisa
        self.assertEqual(state["stop"], 20.63)         # buy - 30 paisa
        self.assertEqual(state["trail_updates"], 0)    # never went up
        self.assertEqual(state["scans"], 10)           # scanned all 10 values
        self.assertEqual(record["outcome"], "LOSS")    # force square-off result
        self.assertEqual(record["pnl"], -0.6)          # (20.87 - 20.93) * 10

    def test_exact_user_scenario_triggers_at_20_56(self):
        # Buy @ 20.93, market path: 20.88 20.92 20.96 20.88 20.82 20.88
        # 20.80 20.96 20.56 20.99. Stop stays 20.63 (profit never reaches
        # +30 paisa, so no trailing) -> exit triggers on the 20.56 scan.
        prices = [20.88, 20.92, 20.96, 20.88, 20.82, 20.88, 20.80, 20.96, 20.56, 20.99]
        feed = FakeFeed(quotes=[20.95] + prices, sell_price=20.55)
        trader = make_trader(feed, MAX_MONITOR_SCANS=len(prices))
        record = trader.run_cycle(1)

        state = trader._last_monitor_state
        self.assertEqual(feed.buy_price, 20.93)
        self.assertEqual(state["stop"], 20.63)         # buy - 30 paisa (never trailed)
        self.assertEqual(state["trail_updates"], 0)    # max profit was only 3 paisa
        self.assertEqual(state["scans"], 9)            # exited on the 9th scan (20.56)
        self.assertEqual(feed.sell_count, 1)
        self.assertEqual(record["outcome"], "LOSS")
        self.assertEqual(record["pnl"], -3.8)          # (20.55 - 20.93) * 10


if __name__ == "__main__":
    unittest.main()
