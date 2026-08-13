"""
main.py - CLI entry point for the YESBANK intraday trailing bot.

Usage:
    python main.py                        # offline dummy simulation (safe)
    python main.py --mode live            # real Dhan API trading
    python main.py --scenario up          # simulated trending-up market
    python main.py --scenario down        # simulated trending-down market
    python main.py --cycles 5 --interval 2 --seed 7

All strategy values can be changed in config.py.
"""
import argparse
import logging
import sys


def parse_args():
    p = argparse.ArgumentParser(
        description="YESBANK intraday trailing bot (Dhan API). "
                    "Run in --mode sim first to test without real money.")
    p.add_argument("--mode", choices=["sim", "live"], default="sim",
                   help="'sim' = dummy paper-trading feed (default), 'live' = real Dhan API")
    p.add_argument("--cycles", type=int, default=None,
                   help="override MAX_CYCLES (default from config.py)")
    p.add_argument("--interval", type=int, default=None,
                   help="override scan interval in seconds (default 30). "
                        "Use 0 for instant scanning in sim mode")
    p.add_argument("--seed", type=int, default=None,
                   help="simulation random seed (reproducible results)")
    p.add_argument("--scenario", choices=["mixed", "up", "down"], default=None,
                   help="simulated market scenario: mixed (default), up, down")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="logging verbosity (default INFO)")
    return p.parse_args()


def setup_logging(level):
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    args = parse_args()
    setup_logging(args.log_level)
    log = logging.getLogger("main")

    from config import Config
    cfg = Config()

    if args.cycles is not None:
        cfg.MAX_CYCLES = args.cycles
    if args.interval is not None:
        cfg.SCAN_INTERVAL_SEC = args.interval

    if args.mode == "live":
        if cfg.DHAN_CLIENT_ID.startswith("YOUR_") or cfg.DHAN_ACCESS_TOKEN.startswith("YOUR_"):
            log.error("DHAN credentials missing. Create a .env file from .env.example "
                      "and set DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN before live trading.")
            sys.exit(1)
        if cfg.SCAN_INTERVAL_SEC <= 0:
            log.error("Live mode needs a positive scan interval (e.g. 30).")
            sys.exit(1)
        from dhan_feed import DhanFeed
        feed = DhanFeed(cfg)
        log.info("Running in LIVE mode - real orders will be placed on %s %s.",
                 cfg.EXCHANGE_SEGMENT, cfg.SYMBOL)
    else:
        from simulator import SimFeed, SimMarket
        scenario = args.scenario or "mixed"
        seed = args.seed if args.seed is not None else cfg.SIM_SEED
        log.info("Running DUMMY SIMULATION | scenario=%s | seed=%s | NO real orders placed.",
                 scenario, seed)
        feed = SimFeed(cfg, SimMarket(cfg, seed=seed, scenario=scenario))

    trader = TrailingTrader(cfg, feed)
    trader.run()


if __name__ == "__main__":
    from strategy import TrailingTrader
    main()
