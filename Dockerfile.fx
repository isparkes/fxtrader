FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY daemon.py tradelib.py datalib.py oanda.py \
     indicator_*.py \
     logsetup.py mailer.py ./

# fx_trades.jsonl (daemon state) and fxtrader.log are written at runtime —
# mount volumes for persistence across container restarts.
# data/oanda/ parquet store must also be mounted or pre-seeded.
ENTRYPOINT ["python", "daemon.py"]
CMD []
