FROM python:3.11-slim

# Install uv for faster package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# NOTE: this image expects the build context to be the REPO ROOT (set in
# docker-compose.yml via `context: .`), so the sibling shared package
# services/inh-contracts is visible and the `../inh-contracts` uv path
# dependency resolves.

# Copy the shared contracts package first (separate layer; changes rarely).
COPY services/inh-contracts /app/services/inh-contracts

# Copy this service's dependency files, readme, and source (readme + src are
# required by hatchling at install time).
COPY services/inh-public-api-svc/pyproject.toml services/inh-public-api-svc/Readme.md /app/services/inh-public-api-svc/
COPY services/inh-public-api-svc/src /app/services/inh-public-api-svc/src

WORKDIR /app/services/inh-public-api-svc

# Install dependencies. The `../inh-contracts` path dependency resolves
# relative to this WORKDIR.
RUN uv pip install --system -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SERVICE_MODE=api
ENV PORT=8080

EXPOSE 8080

# Run the application
CMD ["python", "-m", "src.main"]
