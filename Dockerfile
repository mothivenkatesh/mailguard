FROM python:3.12-slim

WORKDIR /app

# Install build essentials for aiodns (pycares)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY mailguard ./mailguard

RUN pip install --no-cache-dir ".[api,web]"

EXPOSE 8000

# Default: REST API. Override CMD to run Streamlit or CLI instead.
CMD ["uvicorn", "mailguard.api:app", "--host", "0.0.0.0", "--port", "8000"]
