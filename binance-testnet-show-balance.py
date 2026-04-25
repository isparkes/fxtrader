import os
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
orders = client.get_all_orders(symbol="BTCUSDT", limit=10)
for o in orders:
    print(o["symbol"], o["side"], o["status"], o["price"])
