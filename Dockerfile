FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install \
        "anthropic>=0.40.0" \
        "alembic>=1.13.0" \
        "supermemory>=3.0.0" \
        "graphiti-core[falkordb]>=0.28.0" \
        "openai>=1.40.0"

COPY . .

RUN chmod +x bin/start.sh

ENV PORT=8000
ENV DONNA_PROCESS_ROLE=api
EXPOSE 8000

CMD ["bin/start.sh"]
