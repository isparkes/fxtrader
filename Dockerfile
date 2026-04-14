FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY daemon.py indicator.py mailer.py ./

# signals.jsonl is written at runtime — mount a volume if you want persistence
ENTRYPOINT ["python", "daemon.py"]
CMD []
