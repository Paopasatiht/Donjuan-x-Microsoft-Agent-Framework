FROM python:3.13-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install uv for fast dep resolution
RUN pip install uv

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/

# Install dependencies
RUN uv pip install --system --prerelease=allow .

# Copy env + static
COPY .env .env

EXPOSE 8080

CMD ["uvicorn", "dj_agent.main:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "src"]
