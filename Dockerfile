# ---- stage 1: build the frontend ------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: the service --------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY scripts ./scripts
COPY --from=frontend /fe/dist ./frontend/dist
ENV VPREDICT_DATA=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn vpredict.serving.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
