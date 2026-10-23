#!/usr/bin/env bash
# Builds the serving image both ways and prints the size difference (course Docker assignment, Q1).
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -q -f docker/Dockerfile.serve.naive -t optpred-serve-naive:latest . > /dev/null
docker build -q -f docker/Dockerfile.serve -t optpred-serve:latest . > /dev/null
naive=$(docker image inspect optpred-serve-naive:latest --format '{{.Size}}')
multi=$(docker image inspect optpred-serve:latest --format '{{.Size}}')
python3 - "$naive" "$multi" <<'PY'
import sys
n, m = int(sys.argv[1]), int(sys.argv[2])
print(f"single-stage (python:3.11 full base): {n/1e6:8.0f} MB")
print(f"multi-stage  (python:3.11-slim base): {m/1e6:8.0f} MB")
print(f"reduction: {100*(n-m)/n:.0f}%")
PY
