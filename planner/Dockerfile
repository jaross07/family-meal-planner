# Stage 1: Build Vue 3 frontend if frontend/package.json exists
FROM node:20-alpine AS frontend
WORKDIR /src
COPY . .
RUN mkdir -p /out && \
    if [ -f frontend/package.json ]; then \
      cd frontend && npm ci && npm run build && cp -r dist/* /out/; \
    fi

# Stage 2: Python runtime (non-root)
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations/ ./migrations/
COPY app/ ./app/
COPY --from=frontend /out ./static

RUN useradd --system --uid 10001 planner && chown -R planner:planner /app
USER planner

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
