"""
strategy.py - The trading logic.

Rules implemented (all values live in config.py):
  1. At the start of every cycle fetch the current price, day high and day low.
  2. Buy `QTY` shares with a LIMIT order at  (current LTP - BUY_OFFSET_PAISA).
  3. Once bought, scan the live market every SCAN_INTERVAL_SEC seconds.
  4. UP direction: keep trailing the stop 30 paisa below the latest peak, so a
     rising market keeps locking in more profit (maximum profit objective).
  5. DOWN direction: sell the moment LTP falls 30 paisa below the latest peak,
     so a losing trade is closed quickly (minimum loss objective).
  6. Repeat for MAX_CYCLES trades; stop the whole script after MAX_LOSS_CYCLES
     losing trades.

The feed object can be a live DhanFeed or the dummy SimFeed - the strategy is
identical for both.
"""
import logging
import time

log = logging.getLogger("strategy")


class TrailingTrader:
    def __init__(self, cfg, feed, sleep_fn=None):
        self.cfg = cfg
        self.feed = feed
        self.sleep = sleep_fn if sleep_fn is not None else time.sleep
        self.loss_count = 0
        self.results = []
        self.stop_reason = "completed all cycles"
        self._last_monitor_state = None

    # ------------------------------------------------------------------ #
    # helpers                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _rupees(paisa):
        return paisa / 100.0

    # ------------------------------------------------------------------ #
    # top-level loop                                                     #
    # ------------------------------------------------------------------ #
    def run(self):
        log.info("=" * 76)
        log.info("[START] %s | qty=%d | buy offset=%d paisa | stop=%d paisa "
                 "| trail activation=%d paisa | scan=%ds | cycles=%d | max losses=%d",
                 self.cfg.SYMBOL, self.cfg.QTY, self.cfg.BUY_OFFSET_PAISA,
                 self.cfg.STOP_LOSS_PAISA, self.cfg.TRAIL_ACTIVATION_PAISA,
                 self.cfg.SCAN_INTERVAL_SEC, self.cfg.MAX_CYCLES,
                 self.cfg.MAX_LOSS_CYCLES)

        cycle_no = 0
        while cycle_no < self.cfg.MAX_CYCLES and self.loss_count < self.cfg.MAX_LOSS_CYCLES:
            cycle_no += 1
            self.run_cycle(cycle_no)

        self._print_summary(cycle_no)
        return self.results

    def run_cycle(self, cycle_no):
        log.info("=" * 76)
        log.info("[CYCLE %d/%d] START | losses so far: %d/%d",
                 cycle_no, self.cfg.MAX_CYCLES, self.loss_count, self.cfg.MAX_LOSS_CYCLES)

        try:
            quote = self.feed.get_quote()
        except Exception as exc:
            log.error("[CYCLE %d] Could not fetch market data: %s. Skipping cycle.", cycle_no, exc)
            return None

        log.info("[CYCLE %d] MARKET | %s LTP=%.2f | Day High=%.2f | Day Low=%.2f",
                 cycle_no, self.cfg.SYMBOL, quote["ltp"], quote["day_high"], quote["day_low"])

        # ---------------- BUY leg ------------------------------------ #
        target = round(quote["ltp"] - self._rupees(self.cfg.BUY_OFFSET_PAISA), 2)
        fill_price = self._buy_with_retries(cycle_no, target)
        if fill_price is None:
            log.warning("[CYCLE %d] Buy never filled. Aborting cycle.", cycle_no)
            return None

        # ---------------- MONITOR leg -------------------------------- #
        sell_price = self._monitor_position(cycle_no, fill_price)
        if sell_price is None:
            log.error("[CYCLE %d] No exit executed. Aborting cycle.", cycle_no)
            return None

        # ---------------- RESULT ------------------------------------- #
        pnl = round((sell_price - fill_price) * self.cfg.QTY, 2)
        outcome = "PROFIT" if pnl >= 0 else "LOSS"
        if outcome == "LOSS":
            self.loss_count += 1

        record = {
            "cycle": cycle_no,
            "buy": round(fill_price, 2),
            "sell": round(sell_price, 2),
            "pnl": pnl,
            "outcome": outcome,
        }
        self.results.append(record)
        log.info("[CYCLE %d] RESULT | buy %.2f | sell %.2f | P&L Rs. %.2f | %s",
                 cycle_no, fill_price, sell_price, pnl, outcome)

        if self.loss_count >= self.cfg.MAX_LOSS_CYCLES:
            self.stop_reason = f"stopped after {self.loss_count} losing trades"
            log.warning("[STOP] %d losing trades reached -> halting the script.", self.loss_count)
        return record

    # ------------------------------------------------------------------ #
    # buy leg                                                            #
    # ------------------------------------------------------------------ #
    def _buy_with_retries(self, cycle_no, initial_price):
        price = initial_price
        for attempt in range(1, self.cfg.MAX_BUY_RETRIES + 1):
            log.info("[CYCLE %d] BUY | attempt %d/%d | LIMIT %d share(s) @ %.2f (LTP - %d paisa)",
                     cycle_no, attempt, self.cfg.MAX_BUY_RETRIES,
                     self.cfg.QTY, price, self.cfg.BUY_OFFSET_PAISA)
            try:
                order_id = self.feed.place_buy_limit(price, self.cfg.QTY)
                filled, fill_price = self.feed.wait_for_buy_fill(order_id)
            except Exception as exc:
                log.error("[CYCLE %d] Buy order error: %s", cycle_no, exc)
                return None

            if filled:
                log.info("[CYCLE %d] BUY FILLED | %d share(s) @ %.2f",
                         cycle_no, self.cfg.QTY, fill_price)
                return fill_price

            log.info("[CYCLE %d] BUY | not filled yet -> re-quote at fresh LTP - %d paisa",
                     cycle_no, self.cfg.BUY_OFFSET_PAISA)
            try:
                price = round(self.feed.get_quote()["ltp"] - self._rupees(self.cfg.BUY_OFFSET_PAISA), 2)
            except Exception as exc:
                log.error("[CYCLE %d] Re-quote error: %s", cycle_no, exc)
                return None
        return None

    # ------------------------------------------------------------------ #
    # monitor leg (30-second scanning + trailing stop)                   #
    # ------------------------------------------------------------------ #
    def _monitor_position(self, cycle_no, fill_price):
        state = {
            "peak": round(fill_price, 2),
            "stop": round(fill_price - self._rupees(self.cfg.STOP_LOSS_PAISA), 2),
            "trail_updates": 0,
            "scans": 0,
        }
        self._last_monitor_state = state
        log.info("[CYCLE %d] TRACKING | bought @ %.2f | initial stop %.2f (%d paisa below buy)",
                 cycle_no, fill_price, state["stop"], self.cfg.STOP_LOSS_PAISA)

        while state["scans"] < self.cfg.MAX_MONITOR_SCANS:
            try:
                quote = self.feed.get_quote()
            except Exception as exc:
                log.error("[CYCLE %d] Quote error during monitor: %s", cycle_no, exc)
                self.sleep(self.cfg.SCAN_INTERVAL_SEC)
                continue

            ltp = quote["ltp"]
            state["scans"] += 1

            # ----- UP direction: trail the stop behind the peak ----- #
            if ltp > state["peak"]:
                state["peak"] = ltp
                profit_paisa = round((ltp - fill_price) * 100, 1)
                if profit_paisa >= self.cfg.TRAIL_ACTIVATION_PAISA:
                    new_stop = round(ltp - self._rupees(self.cfg.STOP_LOSS_PAISA), 2)
                    if new_stop > state["stop"]:
                        old_stop = state["stop"]
                        state["stop"] = new_stop
                        state["trail_updates"] += 1
                        log.info("[CYCLE %d] [SL UP] peak %.2f (profit %.0f paisa) "
                                 "-> stop %.2f -> %.2f | locked min profit %.2f",
                                 cycle_no, ltp, profit_paisa, old_stop, new_stop,
                                 round((new_stop - fill_price) * self.cfg.QTY, 2))
                    else:
                        log.info("[CYCLE %d] [NEW HIGH] LTP %.2f (profit %.0f paisa, "
                                 "already trailing at stop %.2f)",
                                 cycle_no, ltp, profit_paisa, state["stop"])
                else:
                    log.info("[CYCLE %d] [NEW HIGH] LTP %.2f (profit %.0f paisa, "
                             "trailing starts at %d paisa)",
                             cycle_no, ltp, profit_paisa, self.cfg.TRAIL_ACTIVATION_PAISA)
            else:
                log.info("[CYCLE %d] SCAN %d | LTP %.2f | peak %.2f | stop %.2f "
                         "| profit %.0f paisa",
                         cycle_no, state["scans"], ltp, state["peak"], state["stop"],
                         round((ltp - fill_price) * 100, 1))

            # ----- DOWN direction: book exit 30 paisa below peak ----- #
            if ltp <= state["stop"]:
                log.warning("[CYCLE %d] [TRIGGER] LTP %.2f <= stop %.2f | selling %d share(s)",
                            cycle_no, ltp, state["stop"], self.cfg.QTY)
                try:
                    sell_price = self.feed.place_sell_market(self.cfg.QTY)
                except Exception as exc:
                    log.error("[CYCLE %d] Sell order failed: %s", cycle_no, exc)
                    return None
                log.info("[CYCLE %d] SELL FILLED @ %.2f", cycle_no, sell_price)
                return sell_price

            self.sleep(self.cfg.SCAN_INTERVAL_SEC)

        # Safety: force square-off if the scanner ran for too long.
        log.warning("[CYCLE %d] Monitor hit %d scans without an exit -> forcing square-off.",
                    cycle_no, self.cfg.MAX_MONITOR_SCANS)
        try:
            return self.feed.place_sell_market(self.cfg.QTY)
        except Exception as exc:
            log.error("[CYCLE %d] Force square-off failed: %s", cycle_no, exc)
            return None

    # ------------------------------------------------------------------ #
    # summary                                                            #
    # ------------------------------------------------------------------ #
    def _print_summary(self, cycles_attempted):
        log.info("=" * 76)
        log.info("[SUMMARY] cycles attempted: %d | stop reason: %s",
                 cycles_attempted, self.stop_reason)
        if not self.results:
            log.info("[SUMMARY] No completed trades.")
            return

        wins = [r for r in self.results if r["outcome"] == "PROFIT"]
        losses = [r for r in self.results if r["outcome"] == "LOSS"]
        total = round(sum(r["pnl"] for r in self.results), 2)
        log.info("[SUMMARY] completed trades: %d | wins: %d | losses: %d | net P&L: Rs. %.2f",
                 len(self.results), len(wins), len(losses), total)
        for r in self.results:
            log.info("[SUMMARY]   Cycle %2d | buy %.2f | sell %.2f | P&L Rs. %6.2f | %s",
                     r["cycle"], r["buy"], r["sell"], r["pnl"], r["outcome"])
