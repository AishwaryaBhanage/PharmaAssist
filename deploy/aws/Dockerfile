# The v2 API image (arm64): FastAPI + the React build, run by uvicorn on :8000 behind the load
# balancer on EC2, and used as-is for the one-off migration and seed tasks on Fargate.
#
# Build context: the repository root. The image holds code, config and the compiled frontend
# (plus the cross-encoder model when config.yaml search.rerank is set, so no instance downloads it):
# documents live in S3, chunks and vectors in PostgreSQL, the cache in Valkey. No API key is in
# the image; the environment comes from Secrets Manager at boot (deploy/aws/v2/template.yaml user-data)
# or from .env / docker-compose locally.

# ---- stage 1: the React frontend ----------------------------------------------------------------
# `frontend*` is a glob so the COPY also succeeds while frontend/ doesn't exist yet (the glob then
# matches nothing and only config.yaml is copied); the build step is skipped in that case and the API
# serves /api only.
FROM public.ecr.aws/docker/library/node:24-bookworm-slim AS frontend
WORKDIR /build
COPY config.yaml frontend* ./src/
RUN if [ -f src/package.json ]; then \
      cd src && npm ci --no-audit --no-fund && npm run build && test -d dist; \
    else \
      echo "frontend/ not present: building an API-only image" && mkdir -p src/dist; \
    fi
# stage the one script the API image needs; scripts/ exists but seed_users.py may not yet (stream C)
COPY scripts/ ./scripts/
RUN mkdir -p seed && (cp scripts/seed_users.py seed/ 2>/dev/null || echo "scripts/seed_users.py not present yet")

# ---- stage 2: the API -----------------------------------------------------------------------------
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken HF_HOME=/opt/hf HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    APP_WARM_MODELS=1 PYTHONPATH=/app/src

WORKDIR /app
COPY pyproject.toml config.yaml ./
# the base dependency list from pyproject.toml (the package itself is not installed: src/ is copied below)
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb')); print('\n'.join(d['project']['dependencies']))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
 && chmod -R a+rX /opt/tiktoken
# Only when config.yaml search.rerank is set: torch from the CPU wheel index (no CUDA libraries),
# sentence-transformers, and the named model baked in (~1.1 GB for bge-reranker-base). Off by default.
RUN if python -c "import yaml, sys; sys.exit(0 if yaml.safe_load(open('config.yaml'))['search'].get('rerank') else 1)"; then \
      pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
   && python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb')); print('\n'.join(d['project']['optional-dependencies']['rerank']))" > /tmp/rerank.txt \
   && pip install -r /tmp/rerank.txt \
   && HF_HUB_OFFLINE=0 python -c "import yaml; from sentence_transformers import CrossEncoder; \
        CrossEncoder(yaml.safe_load(open('config.yaml'))['search']['rerank']['model'], max_length=512)" \
   && chmod -R a+rX /opt/hf; \
    else echo 'search.rerank is off: no torch, no model in the image'; fi

COPY docs/catalog.yaml docs/catalog.yaml
COPY src/ src/
COPY app/ app/
COPY db/ db/
# only the seed script from scripts/ (the rest is offline tooling), staged in the first stage
COPY --from=frontend /build/seed/ scripts/
COPY --from=frontend /build/src/dist frontend/dist

# non-root: the app writes only under storage/ (PDF page cache) and /tmp
RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
 && mkdir -p storage && chown -R app:app /app/storage
USER app
ENV HOME=/home/app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"
# with search.rerank on, use --workers 1: the model is ~1 GB per process and its lock serialises scoring
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
