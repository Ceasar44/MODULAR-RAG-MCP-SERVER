FROM python:3.11-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

COPY pyproject.toml README.md main.py ./
COPY src ./src
COPY scripts ./scripts

# Keep src/core/settings.py anchored at /app so resolve_path uses the mounted data.
RUN python -m pip install -e . \
    && mkdir -p /app/config /app/data /app/logs \
    && chown app:app /app/data /app/logs

USER app
EXPOSE 8002

CMD ["python", "-m", "src.mcp_server.fastmcp_adapter.server"]
