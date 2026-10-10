# ---- build the React dashboard ----
FROM node:20-alpine AS web
WORKDIR /web
COPY dashboard/package.json ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# ---- python agent + API ----
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY copytrader.py server.py scanner.py tune.py config.json ./
COPY --from=web /web/dist ./dashboard/dist
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
CMD ["python", "server.py"]
