# YESBANK Intraday Trailing Bot (Dhan API)

Python CLI trading bot for YESBANK on NSE. It buys 10 shares for intraday, then
scans the live market every 30 seconds and uses a **trailing stop-loss of
30 paisa** to maximise profit in an up-market and minimise loss in a down-market.

> Built as an evolution of the original script `gemini-code-1786212210263.py`
> (kept in this repo for reference).

## What it does

For each trade cycle:

1. **Check market** - reads current LTP, day high and day low.
2. **Buy** - places a LIMIT order for 10 shares at `current price - 2 paisa`.
3. **Monitor** - after the buy fills, scans live price every 30 seconds.
4. **Up direction** - once profit exceeds 30 paisa, the stop keeps moving up to
   `latest peak - 30 paisa`, locking in maximum profit.
5. **Down direction** - the moment price falls 30 paisa below the latest peak,
   it sells (books a small loss quickly).
6. **Repeat** - up to 10 cycles; the script **halts after 3 losing trades**.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Test offline with the dummy simulation (NO real orders, NO credentials)
python main.py

# 3. Try different simulated market conditions
python main.py --scenario up      # trending-up market  -> trailing profits
python main.py --scenario down    # trending-down market -> quick loss booking + 3-loss halt
python main.py --seed 5           # another reproducible random market
```

### Go live (real Dhan account)

```bash
# 1. Fill in your credentials
cp .env.example .env        # edit DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN

# 2. Run against the real Dhan API
python main.py --mode live
```

## CLI options

| Option              | Description                                              | Default  |
|---------------------|----------------------------------------------------------|----------|
| `--mode sim/live`   | dummy paper-trading feed or real Dhan API                | `sim`    |
| `--cycles N`        | max buy->sell cycles                                     | 10       |
| `--interval N`      | scan interval in seconds (`0` = instant, sim only)       | 30       |
| `--seed N`          | simulation random seed (reproducible)                    | 11       |
| `--scenario`        | `mixed`, `up`, `down`                                    | `mixed`  |
| `--log-level`       | `DEBUG`, `INFO`, `WARNING`, `ERROR`                      | `INFO`   |

## How to modify it later

Everything you would normally want to change is in **`config.py`**:

| Setting                       | Meaning                                        | Default   |
|-------------------------------|------------------------------------------------|-----------|
| `QTY`                         | shares per cycle                               | 10        |
| `BUY_OFFSET_PAISA`            | buy limit = LTP - N paisa                      | 2         |
| `STOP_LOSS_PAISA`             | sell N paisa below the latest peak             | 30        |
| `TRAIL_ACTIVATION_PAISA`      | start trailing after N paisa profit            | 30        |
| `SCAN_INTERVAL_SEC`           | live market scan interval                      | 30        |
| `MAX_CYCLES`                  | total trade cycles                             | 10        |
| `MAX_LOSS_CYCLES`             | halt the script after N losing trades          | 3         |
| `SECURITY_ID` / `EXCHANGE_SEGMENT` | instrument to trade                       | 11915 / NSE_EQ |

Want to trail 50 paisa instead of 30? Change `STOP_LOSS_PAISA = 50`.
Want a different stock? Change `SECURITY_ID`, `SYMBOL`, `QTY` and the quantity
limits. The strategy code itself (`strategy.py`) never hard-codes numbers.

## Project layout

```
main.py              # CLI entry point
config.py            # ALL tuning parameters
strategy.py          # trading logic (buy / 30s scan / trailing stop / cycles)
dhan_feed.py         # live Dhan API feed (market data + orders)
simulator.py         # dummy paper-trading feed for offline testing
tests/test_strategy.py  # unit tests for the strategy rules
gemini-code-1786212210263.py  # original reference script
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Important notes

- **Run `--mode sim` first.** The dummy feed uses a random-walk market so you
  can watch every rule fire without risking money.
- Live mode is built on the `dhanhq` library; order-status fields are parsed
  defensively. Always paper-trade before going live.
- Intraday positions must be squared off before market close; the trailing
  logic exits every cycle automatically.
- Trading involves financial risk. This tool only automates your strategy - it
  does not guarantee profit. Use at your own discretion.
