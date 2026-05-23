FROM python:3.11-slim

WORKDIR /app

# Install uv for faster package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files, readme, and source code (required by hatchling)
COPY pyproject.toml Readme.md ./
COPY src/ ./src/

# Install dependencies
RUN uv pip install --system -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SERVICE_MODE=api
ENV PORT=8080

EXPOSE 8080

# Run the application
CMD ["python", "-m", "src.main"]
