FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY daemon.py indicator_audusd.py indicator_eurusd.py indicator_gbpusd.py indicator_usdjpy.py mailer.py tradelog.py ./

# trades.jsonl (daemon state) and signals.jsonl are written at runtime —
# mount volumes if you want persistence across container restarts
ENTRYPOINT ["python", "daemon.py"]
CMD []
