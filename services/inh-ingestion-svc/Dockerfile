FROM python:3.11-slim

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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

# Install dependencies and the package
RUN uv pip install --system .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (if needed for health checks)
EXPOSE 8080

# Run the service
CMD ["python", "-m", "src.main"]
