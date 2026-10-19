# V6 reproducible local image: build the React workbench, then serve it from
# the same loopback-scoped FastAPI process as the existing Python pipeline.
FROM node:22-alpine AS web-build
WORKDIR /build
COPY apps/web/package.json apps/web/package-lock.json ./apps/web/
RUN npm ci --prefix apps/web
COPY apps/web ./apps/web
COPY docs/openapi-v6.json ./docs/openapi-v6.json
RUN npm run build --prefix apps/web

FROM python:3.12-slim AS runtime
ARG REPOLENS_LANGCHAIN=0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    REPOLENS_DATA_DIR=/data \
    REPOLENS_CONTAINER=1 \
    REPOLENS_REPOSITORY_ROOTS=/workspace/repository

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 repolens

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY apps/api/requirements-web.lock apps/api/requirements-langchain.lock ./apps/api/
COPY docs ./docs
COPY eval ./eval
COPY scripts ./scripts
COPY --from=web-build /build/src/repolens/workbench/static ./src/repolens/workbench/static

RUN if [ "$REPOLENS_LANGCHAIN" = "1" ]; then \
      python -m pip install --no-cache-dir -r apps/api/requirements-langchain.lock; \
    else \
      python -m pip install --no-cache-dir -r apps/api/requirements-web.lock; \
    fi \
    && python -m pip install --no-cache-dir --no-deps . \
    && mkdir -p /data \
    && chown -R repolens:repolens /app /data

USER repolens
EXPOSE 8770
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8770/api/health', timeout=2)"

CMD ["python", "-m", "repolens.workbench.launcher", "--host", "0.0.0.0", "--port", "8770", "--no-browser", "--data-dir", "/data"]
