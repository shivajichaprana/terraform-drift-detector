# ──────────────────────────────────────────────────────────────────────
# Terraform Drift Detector — Container Image
#
# Multi-stage build for a lightweight drift detection container.
# Includes Terraform CLI and the Python-based detector with all
# dependencies pre-installed.
#
# Usage:
#   docker build -t drift-detector .
#   docker run -v $(pwd)/config.yaml:/app/config.yaml \
#     -e AWS_ACCESS_KEY_ID=... \
#     -e AWS_SECRET_ACCESS_KEY=... \
#     drift-detector detect --config config.yaml
# ──────────────────────────────────────────────────────────────────────

# ── Stage 1: Terraform binary ────────────────────────────────────────
FROM hashicorp/terraform:1.7.0 AS terraform

# ── Stage 2: Python application ──────────────────────────────────────
FROM python:3.11-slim AS base

# Metadata
LABEL maintainer="Project Maintainers"
LABEL org.opencontainers.image.title="terraform-drift-detector"
LABEL org.opencontainers.image.description="Automated Terraform state drift detection"
LABEL org.opencontainers.image.source="https://github.com/shivajichaprana/terraform-drift-detector"
LABEL org.opencontainers.image.version="1.0.0"

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TF_IN_AUTOMATION=true

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        ca-certificates \
        curl \
        jq && \
    rm -rf /var/lib/apt/lists/*

# Copy Terraform binary from stage 1
COPY --from=terraform /bin/terraform /usr/local/bin/terraform

# Verify Terraform installation
RUN terraform version

# Create non-root user for security
RUN groupadd --gid 1000 detector && \
    useradd --uid 1000 --gid detector --shell /bin/bash \
    --create-home detector

# Set working directory
WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY setup.py .
COPY README.md .
COPY detector/ detector/

# Install the package
RUN pip install --no-cache-dir -e .

# Copy scripts and make executable
COPY scripts/ scripts/
RUN chmod +x scripts/*.sh 2>/dev/null || true

# Create directories for results and configs
RUN mkdir -p /app/drift-results /app/configs && \
    chown -R detector:detector /app

# Switch to non-root user
USER detector

# Health check — verify detector is installed
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD drift-detector --version || exit 1

# Default entrypoint runs the detector
ENTRYPOINT ["drift-detector"]

# Default command shows help
CMD ["--help"]
