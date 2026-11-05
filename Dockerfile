FROM ghcr.io/astral-sh/uv:0.12.24 AS uv
FROM python:3.11-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.11-slim-bookworm AS runtime
ARG VCS_REF=workshop
LABEL org.opencontainers.image.title="Bombometro" \
      org.opencontainers.image.source="https://github.com/that-ugly-cat/bombometro" \
      org.opencontainers.image.revision="${VCS_REF}"
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_MODE=lab APP_REVISION="${VCS_REF}"
COPY --from=builder /app/.venv /app/.venv
COPY web.py core.py forecast.py charts.py regimes.py settings.py traffic.py site_details.py sites.json ./
COPY templates/ ./templates/
COPY static/ ./static/
USER 10001:10001
EXPOSE 8502
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8502/healthz', timeout=2).read()"
CMD ["uvicorn", "web:app", "--host", "0.0.0.0", "--port", "8502", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "32", "--backlog", "64", "--timeout-keep-alive", "5"]
