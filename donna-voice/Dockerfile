# donna-voice — LiveKit agent worker container.
# Built for Railway. Worker registers with LiveKit Cloud over websocket
# and serves /health on $HEALTH_PORT (default 8080) for Railway's probe.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build essentials for onnxruntime (used by silero VAD + turn detector).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install python deps first for layer caching.
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# App code.
COPY . /app/donna_voice

# Pre-download model weights (silero, turn-detector) so first call is fast.
# Network must be available at build time; Railway's builder allows this.
RUN python -m donna_voice.agent download-files || \
    echo "model prewarm skipped (will lazy-load at runtime)"

ENV HEALTH_PORT=8080
EXPOSE 8080

# Worker is the long-running process. `start` mode binds the agent to
# LiveKit Cloud; rooms get dispatched on demand.
CMD ["python", "-m", "donna_voice.agent", "start"]
