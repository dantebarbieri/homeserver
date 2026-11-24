FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY common.py events.py ssh_keys.py networks.py collector.py server.py ./
COPY static ./static
USER 65534:65534
CMD ["python", "server.py", "--host", "0.0.0.0"]
