# Career Copilot — container image (Streamlit UI + batch pipeline in one image)
# Build:  docker build -t career-copilot .
# Run:    docker run --rm -p 8501:8501 --env-file career_copilot/.env career-copilot

FROM python:3.11-slim AS base

# Playwright needs system libs for Chromium; git for pip VCS deps if ever needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git wget gnupg \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

# App code
COPY career_copilot/ ./career_copilot/
COPY pyproject.toml .

# Local DB / generated artifacts live in a writable volume
RUN mkdir -p career_copilot/generated_resumes career_copilot/screenshots
VOLUME ["/app/career_copilot"]

ENV PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Default: the Streamlit UI. Override for pipeline mode:
#   docker run career-copilot python -m career_copilot.scheduler --once
EXPOSE 8501
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s \
    CMD wget -qO- http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "career_copilot/app.py", "--server.port", "8501"]
