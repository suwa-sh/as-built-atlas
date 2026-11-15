#!/usr/bin/env bash
# DB の日次スナップショット: pg_dump → var/backup/ → S3 (kotori-backups/db/<日付>/)。7 日より古いローカルのダンプは消す。
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1090
source "config/${KOTORI_ENV:-prod}.env"
STAMP="$(date +%Y%m%d)"
OUT="var/backup/kotori_${STAMP}.dump"
mkdir -p var/backup
pg_dump --format=custom --dbname="${KOTORI_DATABASE_URL}" --file="${OUT}"
aws s3 cp "${OUT}" "s3://${BACKUPS_BUCKET}/db/${STAMP}/"
find var/backup -name 'kotori_*.dump' -mtime +7 -delete
