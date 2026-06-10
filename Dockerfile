FROM python:3.13-slim

WORKDIR /app

# Install system deps + uv
RUN pip install --no-cache-dir uv

# Copy dependency lock and pyproject.toml first (layer caching)
COPY pyproject.toml uv.lock ./
COPY histrategy-engine/pyproject.toml histrategy-engine/

# Install dependencies (cached unless pyproject.toml changes)
RUN uv pip install --system "setuptools>=75" && \
    uv pip install --system "fastapi>=0.100.0" "uvicorn>=0.30.0" "PyJWT>=2.8.0"

# Copy application source code
COPY histrategy/ histrategy/
COPY histrategy-engine/ histrategy-engine/
COPY histrategy-knowledge/ histrategy-knowledge/

# Editable-install both packages (resolves source imports correctly)
RUN uv pip install --system -e . -e histrategy-engine

# Ensure histrategy-engine source is on Python path
ENV PYTHONPATH="/app/histrategy-engine/src:${PYTHONPATH}"

# Expose port
EXPOSE 8080

# Shell-form CMD so $PORT is expanded
CMD sh -c "uvicorn histrategy.server.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"
