import os
from datetime import datetime
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

api_key    = os.getenv("BINANCE_API_KEY", "")
api_secret = os.getenv("BINANCE_API_SECRET", "")
testnet    = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

client = Client(api_key, api_secret, testnet=testnet)

# Balances (non-zero only)
account  = client.get_account()
balances = [b for b in account["balances"] if float(b["free"]) > 0]
for b in balances:
    print(f"{b['asset']}: {b['free']}")

# Recent orders
print("\n--- Recent Orders ---")
orders = client.get_all_orders(symbol="BTCUSDT", limit=10)
for o in orders:
    print(o["symbol"], o["side"], o["status"], o["price"])

# Trade history (filled trades only)
print("\n--- Trade History ---")
trades = client.get_my_trades(symbol="BTCUSDT", limit=20)
for t in trades:
    side = "BUY " if t["isBuyer"] else "SELL"
    ts   = datetime.fromtimestamp(t["time"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts}  {side}  qty={t['qty']}  price={t['price']}  commission={t['commission']} {t['commissionAsset']}")
