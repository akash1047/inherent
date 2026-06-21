FROM python:3.11-slim

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install the Tesseract OCR system binary (needed for PNG image OCR).
# Kept minimal: only tesseract-ocr, and apt lists are removed afterwards.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Ensure Python resolves the src package from /app (the local source),
# not from a stale installed wheel in site-packages.
# PYTHONPATH entries come before site-packages in sys.path.
ENV PYTHONPATH=/app

# Copy dependency files (including Readme.md required by pyproject.toml)
COPY pyproject.toml Readme.md ./

# Copy source code before install (required for package install)
COPY src/ ./src/

# Install dependencies and the package, including the optional 'ocr' extra
# (pytesseract + Pillow) so PNG OCR works in the Compose stack.
RUN uv pip install --system ".[ocr]"

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (if needed for health checks)
EXPOSE 8080

# Run the service
CMD ["python", "-m", "src.main"]
