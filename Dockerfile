FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY histrategy/ histrategy/
COPY histrategy-engine/ histrategy-engine/

# Install build deps + both packages
RUN uv pip install --system "setuptools>=75" && \
    uv pip install --system -e . -e histrategy-engine && \
    uv pip install --system "fastapi>=0.100.0" "uvicorn>=0.30.0" "PyJWT>=2.8.0"

# Ensure histrategy-engine source is on Python path
# Editable installs may not resolve correctly in all environments
ENV PYTHONPATH="/app/histrategy-engine/src:${PYTHONPATH}"

# Expose port
EXPOSE 8080

# Shell-form CMD so $PORT is expanded
CMD sh -c "uvicorn histrategy.server.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"
