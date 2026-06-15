FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN pip install --no-cache-dir --upgrade pip setuptools

# Copy everything
COPY pyproject.toml .
COPY histrategy/ histrategy/
COPY histrategy-engine/ histrategy-engine/
COPY histrategy-knowledge/ histrategy-knowledge/
COPY scenarios/ scenarios/

# Install dependencies
RUN pip install "fastapi>=0.100.0" "uvicorn>=0.30.0" "PyJWT>=2.8.0" "httpx>=0.27.0" "rich>=13.0.0" "pydantic>=2.0.0" "pyyaml>=6.0" "psycopg2-binary>=2.9"

# Install histrategy-engine as proper package (not editable)
# Force clean rebuild — ensure YAML rules are included
RUN pip install --no-cache-dir ./histrategy-engine/

# Install main package as editable (needs histrategy-engine available)
RUN pip install -e .

# Expose port
EXPOSE 8080

# Shell-form CMD so $PORT is expanded
CMD sh -c "uvicorn histrategy.server.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"
