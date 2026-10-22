#!/bin/sh
# Writes config.json from environment variables at container start, so the backend address is
# configuration, not code (the frontend and backend are linked only by this REST address).
cat > /usr/share/nginx/html/config.json <<JSON
{"api_url": "${API_URL:-http://127.0.0.1:8000}", "mlflow_url": "${MLFLOW_URL:-http://127.0.0.1:5050}", "grafana_url": "${GRAFANA_URL:-http://127.0.0.1:3001}"}
JSON
