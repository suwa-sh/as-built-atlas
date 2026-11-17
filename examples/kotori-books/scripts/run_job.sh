#!/usr/bin/env bash
# 共通ランナー: 環境の設定を読み、ジョブモジュール (jobs/<name>.py) を実行し、ログに追記する。
# 使い方: bash scripts/run_job.sh <job> [args...]   (Kestra の Flow から呼ばれる)
set -euo pipefail
JOB="${1:?job name}"
shift
cd "$(dirname "$0")/.."
# 実行ユーザーの確認: KOTORI_RUN_USER が設定されていれば、そのユーザーでなければ動かさない
if [ -n "${KOTORI_RUN_USER:-}" ] && [ "$(id -un)" != "$KOTORI_RUN_USER" ]; then
  echo "run_job.sh: ${KOTORI_RUN_USER} で実行してください" >&2
  exit 77
fi
ENV_FILE="config/${KOTORI_ENV:-prod}.env"
# shellcheck disable=SC1090
source "$ENV_FILE"
export PYTHONPATH="$PWD"
mkdir -p var/log/jobs
LOG="var/log/jobs/${JOB}.log"
echo "$(date -Is) start ${JOB} $*" >> "$LOG"
set +e
python3 -m "jobs.${JOB}" "$@" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e
echo "$(date -Is) end ${JOB} rc=${rc}" >> "$LOG"
exit "$rc"
