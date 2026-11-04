FROM python:3.12-slim-bookworm

# Install system dependencies, compilers, fonts, and Playwright Chromium requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    fonts-dejavu-core \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    pip install --no-cache-dir pytest pytest-asyncio

# Install Playwright browser binaries
RUN python -m playwright install --with-deps chromium

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /app/data/screenshots /app/data/generated_pdfs /app/data/temporary && \
    chown -R appuser:appuser /app

# Copy application source code
COPY --chown=appuser:appuser . .

USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -m app.main status || exit 1

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["scheduler"]

