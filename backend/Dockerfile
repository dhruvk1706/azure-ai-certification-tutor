# Build context is the repository root (see infrastructure/docker-compose.yml).
FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.11.19
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
