FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SOUNDBOARD_SOUNDS_DIR=/data/sounds \
    SOUNDBOARD_DB_FILE=/data/sounds_db.json \
    SOUNDBOARD_USERS_DB=/data/users.db

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid 1000 --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py manage.py ./
COPY static ./static

RUN mkdir -p /data && chown -R app:app /app /data

USER app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:5000/ >/dev/null || exit 1

CMD ["gunicorn", "--worker-class", "gthread", "--workers", "2", "--threads", "4", "--timeout", "60", "-b", "0.0.0.0:5000", "app:app"]
