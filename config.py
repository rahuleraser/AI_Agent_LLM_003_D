"""
config.py - ALL tunable parameters for the YESBANK intraday trailing bot.

This is the only file you need to edit to change how the bot behaves.
Every number used by the strategy lives here so the trading logic
(strategy.py) stays clean and easy to modify later.

Prices are stored in paisa for human clarity:
    1 Rupee  = 100 paisa
    0.30 Rs   = 30 paisa  (the trailing stop distance)
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


class Config:
    # ------------------------------------------------------------------ #
    # Dhan API credentials (fill these in a .env file, see .env.example) #
    # ------------------------------------------------------------------ #
    DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "YOUR_DHAN_CLIENT_ID")
    DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "YOUR_DHAN_ACCESS_TOKEN")

    # ------------------------------------------------------------------ #
    # Instrument details                                                 #
    # ------------------------------------------------------------------ #
    SYMBOL = "YESBANK"
    SECURITY_ID = "11915"          # Dhan security id for YESBANK on NSE_EQ
    EXCHANGE_SEGMENT = "NSE_EQ"

    # ------------------------------------------------------------------ #
    # Order settings                                                     #
    # ------------------------------------------------------------------ #
    QTY = 10                       # shares bought per cycle
    PRODUCT_TYPE = "INTRADAY"      # intraday product (square-off same day)

    BUY_OFFSET_PAISA = 2           # buy limit = LTP - 2 paisa
    ORDER_POLL_SEC = 2             # seconds between fill-status checks
    ORDER_FILL_TIMEOUT_SEC = 20    # max seconds to wait for a buy fill
    MAX_BUY_RETRIES = 3            # re-quote attempts if buy stays unfilled

    # ------------------------------------------------------------------ #
    # Trailing stop strategy (core rules, in paisa)                      #
    # ------------------------------------------------------------------ #
    STOP_LOSS_PAISA = 30           # sell when LTP falls 30 paisa below peak
    TRAIL_ACTIVATION_PAISA = 30    # only start trailing after 30 paisa profit
    SCAN_INTERVAL_SEC = 30         # live market scan interval (seconds)

    MAX_MONITOR_SCANS = 10         # scan only 10 times (every 30s), then square-off

    # ------------------------------------------------------------------ #
    # Run limits                                                         #
    # ------------------------------------------------------------------ #
    MAX_CYCLES = 10                # total buy -> sell cycles to attempt
    MAX_LOSS_CYCLES = 3            # stop the whole script after 3 losses

    # ------------------------------------------------------------------ #
    # Dummy simulation settings (used by --mode sim)                     #
    # ------------------------------------------------------------------ #
    SIM_SEED = 11                  # deterministic result for the same seed
    SIM_START_PRICE = 52.0         # starting simulated price
    SIM_VOLATILITY = 0.006         # per-tick price volatility
    SIM_UPTREND_BIAS = 0.005       # upward drift (makes trailing visible)
    SIM_MEAN_REVERSION = 0.002     # pulls price back toward the start price
    SIM_FILL_PROB = 0.35           # per-tick chance a buy limit fills (liquidity)
    SIM_SELL_SLIPPAGE = 0.01       # market-sell slippage in Rupees
