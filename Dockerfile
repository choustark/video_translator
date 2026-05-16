FROM python:3.13-slim

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    ffmpeg -version

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/uv

WORKDIR /app

# Install Python dependencies (layer cache: only re-install when deps change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra docker

# Copy application code
COPY src/ src/
COPY main.py config.yaml scripts/docker-entrypoint.sh ./

ENTRYPOINT ["./docker-entrypoint.sh"]
