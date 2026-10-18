#!/usr/bin/env bash
# Serves the registry's champion model with `mlflow models serve` and follows the alias.
# When the champion changes (a rollback, or a better retrained model) it restarts on the new
# version, so a rollback takes effect within seconds without anyone touching Docker.
set -u
NAME="${MODEL_NAME:-nifty-option-direction}"
ALIAS="${MODEL_ALIAS:-champion}"
PORT="${MODEL_PORT:-5001}"
POLL_S="${POLL_SECONDS:-10}"
export MLFLOW_TRACKING_URI="${MLFLOW_TRACKING_URI:-sqlite:////app/mlflow/mlflow.db}"

version() {
  python - 2>/dev/null <<PY
import mlflow
try:
    print(mlflow.MlflowClient().get_model_version_by_alias("$NAME", "$ALIAS").version)
except Exception:
    pass
PY
}

pid=""
current=""
stop_server() { [ -n "$pid" ] && kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null; pid=""; }
trap 'stop_server; exit 0' TERM INT

while true; do
  v="$(version)"
  if [ -z "$v" ]; then
    echo "no '$ALIAS' model registered yet; waiting"
  elif [ "$v" != "$current" ] || ! kill -0 "$pid" 2>/dev/null; then
    stop_server
    echo "serving $NAME version $v ($ALIAS)"
    mlflow models serve -m "models:/$NAME/$v" -p "$PORT" --host 0.0.0.0 --env-manager local &
    pid=$!
    current="$v"
  fi
  sleep "$POLL_S"
done
