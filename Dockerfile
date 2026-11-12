# OmniRAG API server + web UI
#   docker build -t omnirag .
#   docker run --rm -p 8000:8000 -v omnirag-data:/data omnirag
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMNIRAG_HOME=/data \
    OMNIRAG_KB=default

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[server,pdf,images]"

COPY examples ./examples

RUN useradd --create-home --uid 1000 omnirag \
    && mkdir -p /data \
    && chown -R omnirag:omnirag /data
USER omnirag

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["sh", "-c", "omnirag serve --host 0.0.0.0 --port 8000 --kb \"$OMNIRAG_KB\""]
