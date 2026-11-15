#!/usr/bin/env bash
# ログのローテーション: 1 日経過したジョブログを gzip し、30 日を超えた圧縮済みログを削除する。
set -euo pipefail
cd "$(dirname "$0")/.."
find var/log/jobs -name '*.log' -mtime +1 -exec gzip -f {} \;
find var/log/jobs -name '*.log.gz' -mtime +30 -delete
