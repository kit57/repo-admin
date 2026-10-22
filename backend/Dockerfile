FROM python:3.13-slim AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

# Build with WITH_OTEL=true to include the optional OpenTelemetry exporter.
ARG WITH_OTEL=false

COPY backend/requirements.txt backend/requirements-otel.txt ./
RUN if [ "$WITH_OTEL" = "true" ]; then cat requirements-otel.txt >> requirements.txt; fi \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/repo_admin.db

WORKDIR /app

COPY --from=dependencies /wheels /wheels
COPY --from=dependencies /build/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /data \
    && chown app:app /data

COPY --chown=app:app backend/ ./

USER app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
