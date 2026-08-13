"""
dhan_feed.py - Live market feed & order execution on the Dhan trading API.

Implements the SAME interface as SimFeed (simulator.py) so the strategy
never knows whether it is talking to the real market or the dummy feed:

    get_quote()          -> {"ltp", "day_high", "day_low"}
    place_buy_limit()    -> order_id
    wait_for_buy_fill()  -> (filled, fill_price)
    place_sell_market()  -> executed sell price
"""
import logging
import time

from dhanhq import dhanhq

log = logging.getLogger("dhan")

# Order statuses that mean the order executed / was cancelled.
FILLED_STATUSES = {"FILLED", "TRADED", "TRADED_FULLY"}
DEAD_STATUSES = {"REJECTED", "CANCELLED", "CANCELED"}


class DhanFeed:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dhan = dhanhq(cfg.DHAN_CLIENT_ID, cfg.DHAN_ACCESS_TOKEN)

    # ------------------------- helpers --------------------------------- #
    @staticmethod
    def _as_float(value, default=None):
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    # ------------------------- market data ----------------------------- #
    def get_quote(self):
        resp = self.dhan.quote_data({self.cfg.EXCHANGE_SEGMENT: self.cfg.SECURITY_ID})
        if resp.get("status") != "success":
            raise RuntimeError(f"Dhan quote error: {resp.get('remarks')}")

        data = resp.get("data")
        if isinstance(data, dict):
            item = data.get(self.cfg.SECURITY_ID) or data
            data = item if isinstance(item, dict) else {}
        elif isinstance(data, list):
            data = data[0] if data else {}
        else:
            data = {}

        ohlc = data.get("ohlc") or {}
        ltp = self._as_float(data.get("lastPrice"))
        if ltp is None:
            ltp = self._as_float(data.get("lastTradedPrice"))
        if ltp is None:
            ltp = self._as_float(ohlc.get("close"))
        if ltp is None:
            raise RuntimeError(f"Could not read LTP from Dhan quote: {data}")

        return {
            "ltp": ltp,
            "day_high": self._as_float(ohlc.get("high"), 0.0),
            "day_low": self._as_float(ohlc.get("low"), 0.0),
        }

    # ------------------------- orders ---------------------------------- #
    def place_buy_limit(self, price, qty):
        resp = self.dhan.place_order(
            security_id=self.cfg.SECURITY_ID,
            exchange_segment=self.cfg.EXCHANGE_SEGMENT,
            transaction_type=self.dhan.BUY,
            quantity=int(qty),
            order_type=self.dhan.LIMIT,
            product_type=self.cfg.PRODUCT_TYPE,
            price=float(round(price, 2)),
        )
        if resp.get("status") != "success":
            raise RuntimeError(f"Buy order rejected: {resp.get('remarks')}")
        return (resp.get("data") or {}).get("orderId")

    def _order_status(self, order_id):
        resp = self.dhan.get_order_by_id(order_id)
        if resp.get("status") != "success":
            return "UNKNOWN", None
        data = resp.get("data") or {}
        status = (data.get("orderStatus") or "UNKNOWN").upper()
        avg = self._as_float(data.get("averageTradedPrice") or data.get("tradedPrice"))
        return status, avg

    def wait_for_buy_fill(self, order_id):
        deadline = time.time() + self.cfg.ORDER_FILL_TIMEOUT_SEC
        while time.time() < deadline:
            status, avg = self._order_status(order_id)
            if status in FILLED_STATUSES:
                return True, (avg if avg is not None else 0.0)
            if status in DEAD_STATUSES:
                return False, None
            time.sleep(self.cfg.ORDER_POLL_SEC)
        return False, None

    def place_sell_market(self, qty):
        resp = self.dhan.place_order(
            security_id=self.cfg.SECURITY_ID,
            exchange_segment=self.cfg.EXCHANGE_SEGMENT,
            transaction_type=self.dhan.SELL,
            quantity=int(qty),
            order_type=self.dhan.MARKET,
            product_type=self.cfg.PRODUCT_TYPE,
            price=0.0,
        )
        if resp.get("status") != "success":
            raise RuntimeError(f"Sell order rejected: {resp.get('remarks')}")

        order_id = (resp.get("data") or {}).get("orderId")
        deadline = time.time() + self.cfg.ORDER_FILL_TIMEOUT_SEC
        last_avg = None
        while time.time() < deadline:
            status, avg = self._order_status(order_id)
            if avg is not None:
                last_avg = avg
            if status in FILLED_STATUSES:
                return avg if avg is not None else (last_avg or 0.0)
            if status in DEAD_STATUSES:
                raise RuntimeError("Sell order was rejected/cancelled")
            time.sleep(self.cfg.ORDER_POLL_SEC)

        if last_avg is not None:
            return last_avg
        raise RuntimeError("Sell order not confirmed before timeout")
