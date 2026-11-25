FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt
COPY event_preisliste ./event_preisliste
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --system --uid 10001 --create-home eventapp \
    && mkdir -p /data \
    && chown eventapp:eventapp /data
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--access-logfile", "-", "event_preisliste:create_app()"]
