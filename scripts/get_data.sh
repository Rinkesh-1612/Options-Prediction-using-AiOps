#!/usr/bin/env bash
# Download the project data from the GitHub release, verify it, and unpack it into this checkout.
#   scripts/get_data.sh app   built data and trained models (0.9 GB): enough for ./stack up
#   scripts/get_data.sh raw   raw recordings (4.4 GB): needed for make rebuild
set -euo pipefail
cd "$(dirname "$0")/.."
URL="${DATA_URL:-https://github.com/rinkesh-1612/Options-Prediction-using-AiOps/releases/download/data-v1}"
case "${1:-}" in
  app) files=(optpred-app-bundle.tar.gz) ;;
  raw) files=(optpred-raw-data.tar.part-00 optpred-raw-data.tar.part-01 optpred-raw-data.tar.part-02) ;;
  *) echo "usage: $0 app|raw" >&2; exit 2 ;;
esac

mkdir -p .download
cd .download
curl -fsSL -o SHA256SUMS "$URL/SHA256SUMS"
for f in "${files[@]}"; do
  echo "downloading $f"
  curl -fL -C - --retry 5 -o "$f" "$URL/$f"
  grep " $f\$" SHA256SUMS | sha256sum -c -
done
cd ..

echo "unpacking"
if [[ "$1" == app ]]; then
  tar xzf ".download/${files[0]}"
else
  (cd .download && cat "${files[@]}") | tar xf -
fi
rm -rf .download
echo "done"
