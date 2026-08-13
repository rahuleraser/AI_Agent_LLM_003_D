"""
scripted_test.py - Run the strategy through a fixed, hand-written price path.

Unlike --mode sim (which uses a random walk), this feed replays EXACT prices,
so you can verify how the bot behaves for a specific market sequence before
going live.

Example (buy @ 20.93, market stuck at 20.88 for 10 scans):

    python scripts/scripted_test.py --buy-ltp 20.95 --prices 20.88 20.88 20.88 \
        20.88 20.88 20.88 20.88 20.88 20.88 20.88 --interval 30

Notes:
    - The buy fills at (--buy-ltp - 2 paisa) unless --fill is given.
    - After the supplied prices are exhausted, the last price repeats until the
      scan cap; pass --scans to control how many monitor scans to run.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from strategy import TrailingTrader


class ScriptedFeed:
    """Replays an exact price path: one buy-phase quote, then `prices` monitor quotes."""

    def __init__(self, buy_ltp, fill_price, prices, sell_slippage=0.01):
        self.buy_ltp = float(buy_ltp)
        self.fill_price = float(fill_price)
        self.prices = [float(p) for p in prices]
        self.sell_slippage = sell_slippage
        self.day_high = max([self.buy_ltp] + self.prices)
        self.day_low = min([self.buy_ltp] + self.prices)
        self._phase = "buy"
        self._idx = 0
        self.buy_price = None

    def get_quote(self):
        if self._phase == "buy":
            self._phase = "monitor"
            return {"ltp": self.buy_ltp, "day_high": self.day_high, "day_low": self.day_low}
        ltp = self.prices[min(self._idx, len(self.prices) - 1)]
        self._idx += 1
        return {"ltp": ltp, "day_high": self.day_high, "day_low": self.day_low}

    def place_buy_limit(self, price, qty):
        self.buy_price = round(price, 2)
        return "SCRIPT-BUY-1"

    def wait_for_buy_fill(self, order_id):
        return True, self.fill_price

    def place_sell_market(self, qty):
        current = self.prices[min(max(self._idx - 1, 0), len(self.prices) - 1)]
        return round(current - self.sell_slippage, 2)


def parse_args():
    p = argparse.ArgumentParser(description="Run the strategy against a fixed price path.")
    p.add_argument("--buy-ltp", type=float, default=20.95,
                   help="market LTP at buy time (buy limit = LTP - 2 paisa)")
    p.add_argument("--fill", type=float, default=None,
                   help="buy fill price (default = buy-ltp - 2 paisa)")
    p.add_argument("--prices", nargs="+", type=float, required=True,
                   help="monitor LTPs, one per scan (e.g. --prices 20.88 20.88 ...)")
    p.add_argument("--scans", type=int, default=None,
                   help="max monitor scans before force square-off (default = len(prices))")
    p.add_argument("--interval", type=int, default=None,
                   help="scan interval seconds (default from config.py = 30)")
    p.add_argument("--qty", type=int, default=None,
                   help="quantity per cycle (default from config.py = 10)")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = Config()
    fill = args.fill if args.fill is not None else round(args.buy_ltp - cfg.BUY_OFFSET_PAISA / 100.0, 2)
    if args.scans is None:
        args.scans = len(args.prices)
    if args.interval is not None:
        cfg.SCAN_INTERVAL_SEC = args.interval
    if args.qty is not None:
        cfg.QTY = args.qty
    cfg.MAX_MONITOR_SCANS = args.scans

    feed = ScriptedFeed(args.buy_ltp, fill, args.prices)
    TrailingTrader(cfg, feed).run()


if __name__ == "__main__":
    main()
