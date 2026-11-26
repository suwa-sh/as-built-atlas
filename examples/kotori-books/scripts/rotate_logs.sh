#!/usr/bin/env bash
# ログのローテーション: 最後の更新から 2 日以上たったジョブログを gzip し、31 日以上たった圧縮済みログを削除する。
set -euo pipefail
cd "$(dirname "$0")/.."
find var/log/jobs -name '*.log' -mtime +1 -exec gzip -f {} \;
find var/log/jobs -name '*.log.gz' -mtime +30 -delete
