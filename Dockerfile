# Stage 1 builds the client. frontend/.gitignore ignores dist, so the host has
# to build it, and that is the only reason Node is here.
FROM node:24-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 3.13 matches the venv (3.13.5) and CI. statsmodels is pinned <0.15 in
# requirements.txt; IDEAS.md carries why and what would lift the pin.
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/ api/
COPY pitwall/ pitwall/
COPY scripts/ scripts/
# tests/ ships so the suite can run against the real dist and the real data
# inside the image. CI cannot: it excludes data/ and never builds dist.
COPY tests/ tests/
COPY data/processed/ data/processed/
COPY --from=web /app/frontend/dist frontend/dist
ENV PYTHONUNBUFFERED=1
# Reading one race parquet grows this container by 322 MB for a 55 MB frame:
# glibc keeps a per-core arena and pyarrow's pool sits outside malloc, where a
# trim cannot reach it. All three are needed and none works alone - measured
# 20 Sept 2026, docker run -m 512m against the Gate 3c workload.
ENV MALLOC_ARENA_MAX=2
ENV MALLOC_TRIM_THRESHOLD_=131072
ENV ARROW_DEFAULT_MEMORY_POOL=system
EXPOSE 8000
# One worker. The lru_cache loaders in api/cache.py are per-process and one
# holds a ~74 MB decoded frame, so a second worker doubles memory for no extra
# hit rate.
CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
