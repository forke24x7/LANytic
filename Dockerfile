FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOST=0.0.0.0 DB_PATH=/data/lan.sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends arp-scan iproute2 tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app.py /app/app.py
COPY static /app/static
EXPOSE 8840
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8840')+'/healthz', timeout=3)"
CMD ["python", "app.py"]
