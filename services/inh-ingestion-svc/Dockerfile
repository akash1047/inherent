FROM python:3.11-slim

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install the Tesseract OCR system binary (needed for PNG image OCR).
# Kept minimal: only tesseract-ocr, and apt lists are removed afterwards.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# NOTE: this image expects the build context to be the REPO ROOT (set in
# docker-compose.yml via `context: .`), so the sibling shared package
# services/inh-contracts is visible and the `../inh-contracts` uv path
# dependency resolves.

# Copy the shared contracts package first (separate layer; changes rarely).
COPY services/inh-contracts /app/services/inh-contracts

# Copy this service's dependency files + source (Readme.md is required by
# pyproject.toml; hatchling needs src/ present at install time). uv.lock is
# copied because this image installs the LOCKED dependency set -- see the
# install step below.
COPY services/inh-ingestion-svc/pyproject.toml services/inh-ingestion-svc/uv.lock services/inh-ingestion-svc/Readme.md /app/services/inh-ingestion-svc/
COPY services/inh-ingestion-svc/src /app/services/inh-ingestion-svc/src

# Bake the SQL migrations into the image so SERVICE_MODE=migrate can apply them
# without a repo checkout. This is what lets docker-compose.release.yml init the
# database from published images alone (no host bind-mount of ./scripts).
COPY services/inh-ingestion-svc/scripts/migrations /app/services/inh-ingestion-svc/scripts/migrations

WORKDIR /app/services/inh-ingestion-svc

# Ensure Python resolves the src package from the service dir (the local
# source), not from a stale installed wheel in site-packages. PYTHONPATH
# entries come before site-packages in sys.path.
ENV PYTHONPATH=/app/services/inh-ingestion-svc

# Install the EXACT dependency set `uv.lock` pins -- the same one CI's test
# venv gets from `uv sync --frozen` (#225). Includes the optional 'ocr' extra
# (pytesseract + Pillow) so PNG OCR works in the Compose stack.
#
# This used to be a bare `uv pip install --system ".[ocr]"`, which ignores
# uv.lock and re-resolves every `>=` constraint in pyproject.toml against PyPI
# at build time -- making the image's dependencies a function of its BUILD
# DATE rather than of anything in the repo. The public-api service was the one
# that actually broke that way (mcp 2.0.0; see its Dockerfile), but this
# service carried the identical defect and is fixed here in the same sweep.
#
# Two steps, because they answer two different questions:
#   1. `uv export --frozen` renders uv.lock to pinned requirements (--frozen
#      forbids uv from updating the lock, so this is the lock verbatim); the
#      `../inh-contracts` path dependency is emitted as a relative path and
#      resolves against this WORKDIR, exactly as it did before.
#   2. `--no-deps` installs THIS package only. Without it, uv would re-resolve
#      the pyproject `dependencies` table and undo step 1.
RUN uv export --frozen --no-dev --no-hashes --no-emit-project --extra ocr -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && uv pip install --system --no-deps ".[ocr]" \
    && rm /tmp/requirements.txt

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (if needed for health checks)
EXPOSE 8080

# Run the service
CMD ["python", "-m", "src.main"]
