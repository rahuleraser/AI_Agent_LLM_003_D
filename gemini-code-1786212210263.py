import time
import logging
from dhanhq import dhanhq

# --- CONFIGURATION ---
CLIENT_ID = "YOUR_DHAN_CLIENT_ID"
ACCESS_TOKEN = "YOUR_DHAN_ACCESS_TOKEN"

# Yes Bank Specific Settings
TARGET_SEC_ID = "11915"       # Dhan Security ID for YESBANK on NSE_EQ
TARGET_EXCHANGE = "NSE_EQ"
TARGET_QTY = 10               # Only monitor if exactly 10 shares are held

STOP_LOSS_PAISA = 0.30        # Maximum allowed drop from peak (30 Paisa)
SCAN_INTERVAL_SEC = 30        # Scan delay in seconds
MAX_SCANS = 10                # Run exactly 10 times

# Initialize Dhan Client
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# In-memory dictionary to store trailing tracking state
position_tracker = {}

def fetch_open_positions():
    """Fetch active intraday buy positions from Dhan."""
    try:
        response = dhan.get_positions()
        if response.get('status') == 'success' and 'data' in response:
            return response['data']
        return []
    except Exception as e:
        logging.error(f"Error fetching positions: {e}")
        return []

def get_live_ltp(security_id, exchange_segment="NSE_EQ"):
    """Fetch current Last Traded Price (LTP) for a security."""
    try:
        instruments = [(exchange_segment, str(security_id))]
        quote = dhan.get_ltp(instruments)
        if quote.get('status') == 'success' and 'data' in quote:
            data = quote['data']
            return data.get(str(security_id), {}).get('last_price', None)
        return None
    except Exception as e:
        logging.error(f"Error fetching LTP for {security_id}: {e}")
        return None

def exit_position(security_id, exchange_segment, quantity, product_type):
    """Square off position by placing a market sell order."""
    try:
        response = dhan.place_order(
            security_id=str(security_id),
            exchange_segment=exchange_segment,
            transaction_type=dhan.SELL,
            quantity=int(quantity),
            order_type=dhan.MARKET,
            product_type=product_type,
            price=0
        )
        logging.info(f"[EXIT TRIGGERED] Sold {quantity} of Security ID {security_id}. Response: {response}")
        return True
    except Exception as e:
        logging.error(f"[EXIT FAILED] Could not exit {security_id}: {e}")
        return False

def run_scanner():
    logging.info(f"Starting Dhan 30-Second Scanner for YESBANK (SecID: {TARGET_SEC_ID}). Configured for {MAX_SCANS} scans.")
    
    scan_count = 0
    
    while scan_count < MAX_SCANS:
        scan_count += 1
        logging.info(f"--- Executing Scan {scan_count} of {MAX_SCANS} ---")
        
        try:
            positions = fetch_open_positions()
            
            for pos in positions:
                sec_id = str(pos.get('securityId'))
                exchange = pos.get('exchangeSegment', 'NSE_EQ')
                net_qty = int(pos.get('netQty', 0))
                position_type = pos.get('positionType', '')
                
                # Filter for YESBANK, 10 quantity, and LONG position
                if sec_id == TARGET_SEC_ID and exchange == TARGET_EXCHANGE and net_qty == TARGET_QTY and position_type in ['LONG', 'BUY']:
                    buy_price = float(pos.get('buyAvg', 0.0))
                    product_type = pos.get('productType', 'INTRADAY')
                    
                    current_ltp = get_live_ltp(sec_id, exchange)
                    if not current_ltp:
                        continue
                        
                    # Initialize tracking if not already tracked
                    if sec_id not in position_tracker:
                        position_tracker[sec_id] = {
                            'buy_price': buy_price,
                            'highest_price': buy_price,
                            'current_sl': buy_price - STOP_LOSS_PAISA,
                            'qty': net_qty
                        }
                        logging.info(
                            f"[TRACKING NEW] YESBANK | Buy: ₹{buy_price:.2f} | Initial SL: ₹{position_tracker[sec_id]['current_sl']:.2f}"
                        )

                    state = position_tracker[sec_id]
                    
                    # 1. IMMEDIATE TRAILING PROFIT LOGIC
                    # If current market price rises above our previously logged high water mark
                    if current_ltp > state['highest_price']:
                        state['highest_price'] = current_ltp
                        
                        # Automatically trail the stop loss upward from the new high
                        new_sl = current_ltp - STOP_LOSS_PAISA
                        
                        if new_sl > state['current_sl']:
                            state['current_sl'] = new_sl
                            logging.info(
                                f"[SL AUTO-UPGRADED] YESBANK | New High: ₹{current_ltp:.2f} | Trailed SL to: ₹{state['current_sl']:.2f}"
                            )

                    # 2. CHECK STOP LOSS / PROFIT BOOKING TRIGGER
                    if current_ltp <= state['current_sl']:
                        pnl = (current_ltp - state['buy_price']) * net_qty
                        logging.warning(
                            f"[TRIGGER] YESBANK | LTP: ₹{current_ltp:.2f} hit SL: ₹{state['current_sl']:.2f} | Est P&L: ₹{pnl:.2f}"
                        )
                        success = exit_position(sec_id, exchange, net_qty, product_type)
                        if success:
                            del position_tracker[sec_id]

            # Cleanup closed positions from local state
            active_yesbank = [str(p.get('securityId')) for p in positions if int(p.get('netQty', 0)) > 0]
            if TARGET_SEC_ID not in active_yesbank and TARGET_SEC_ID in position_tracker:
                del position_tracker[TARGET_SEC_ID]

        except Exception as e:
            logging.error(f"Error during scan loop: {e}")

        # Sleep only if there are more scans remaining
        if scan_count < MAX_SCANS:
            time.sleep(SCAN_INTERVAL_SEC)
            
    logging.info("Maximum scan count (10) reached. Exiting program successfully.")

if __name__ == "__main__":
    run_scanner()
