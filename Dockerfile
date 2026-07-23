FROM python:3.12.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY cbr_trading/requirements.txt cbr_trading/requirements.txt
COPY cbr_trading/requirements-db.txt cbr_trading/requirements-db.txt
COPY cbr_trading/requirements-live.txt cbr_trading/requirements-live.txt

RUN pip install --no-cache-dir \
    -r cbr_trading/requirements-live.txt

COPY cbr_trading cbr_trading
COPY scripts scripts
COPY tests tests

RUN python scripts/check_no_secrets.py
RUN python -m unittest discover -s tests -q

RUN useradd --create-home --uid 10001 appuser
USER appuser

CMD ["python", "-u", "-m", "cbr_trading.hosted_worker"]
