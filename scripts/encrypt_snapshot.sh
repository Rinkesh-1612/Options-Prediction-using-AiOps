#!/usr/bin/env bash
# Encrypts the data snapshot and the models with GnuPG, AES-256, passphrase mode:
#   data/raw (+ manifest), data/days.json, and mlflow/ (tracking DB, artifacts, registered models).
#   scripts/encrypt_snapshot.sh              encrypt  -> $BACKUP_DIR/snapshot-<date>.tar.gpg
#   scripts/encrypt_snapshot.sh --verify F   decrypt F to /dev/null and compare with the checksum
# The passphrase lives in $KEY_FILE (default ~/.optpred_snapshot.key, mode 600), NEVER in the repo.
# The first run creates it. Copy it to a safe place: without it the backup cannot be opened.
set -euo pipefail
cd "$(dirname "$0")/.."
KEY_FILE="${KEY_FILE:-$HOME/.optpred_snapshot.key}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/optpred-backups}"

if [[ "${1:-}" == "--verify" ]]; then
  f="${2:?give the .tar.gpg file}"
  want="$(cut -d' ' -f1 "$f.sha256")"
  got="$(gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$KEY_FILE" -d "$f" | sha256sum | cut -d' ' -f1)"
  [[ "$want" == "$got" ]] && echo "verified: $f decrypts and matches its checksum" || { echo "MISMATCH" >&2; exit 1; }
  exit 0
fi

mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
if [[ ! -f "$KEY_FILE" ]]; then
  (umask 077; head -c 32 /dev/urandom | base64 > "$KEY_FILE")
  echo "created passphrase file $KEY_FILE -- copy it somewhere safe"
fi
out="$BACKUP_DIR/snapshot-$(date +%Y%m%d).tar.gpg"
# the checksum is of the decrypted tar stream, so --verify can prove the backup opens and is whole
tar -C . -cf - data/raw data/days.json mlflow | tee >(sha256sum > "$out.sha256") \
  | gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$KEY_FILE" \
        --symmetric --cipher-algo AES256 --compress-algo none -o "$out"
sleep 1
echo "wrote $out ($(du -h "$out" | cut -f1))"
