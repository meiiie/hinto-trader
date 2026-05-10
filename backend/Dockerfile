# Hinto Backend - Docker Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies & Build tools
# critical for TA-Lib: build-essential, wget, tar
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    wget \
    tar \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install TA-Lib C Library (Required wrapper build)
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xvzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
# TA-Lib needs include/lib dirs explicitly sometimes, but usually standard install works if C lib is in /usr
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs and data directories
RUN mkdir -p logs data

# Expose ports
EXPOSE 8000 8001

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV LD_LIBRARY_PATH="/usr/lib:/usr/local/lib"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "run_backend.py"]
