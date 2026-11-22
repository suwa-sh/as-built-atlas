#!/bin/sh
# 配布物のイメージを作り直し、見本の分析リポジトリの画面を起動し直す。
# 使い方: redeploy.sh [--build | --upgrade] <分析リポジトリ>...
#   --build    起動し直す前に、集計 (abatlas build) もやり直す (形式・ETL・集計表・宣言・meta を変えたとき)
#   --upgrade  集計の前に、分析リポジトリの中の配布物のコピーも置き換える (abatlas upgrade)。その後、集計もやり直す
#              (このリポジトリの profiles/、配布用の skill、compose.yaml、参照物を変えたとき。集計は、分析リポジトリの中のプロファイルのコピーを読むため)
# 集計か更新が失敗したら、起動し直さずに止まる (古い集計表のまま「確かめた」ことにしない)。
# イメージのタグは、環境変数 ABATLAS_IMAGE (既定 ghcr.io/suwa-sh/as-built-atlas:dev)。分析リポジトリの .env の ABATLAS_IMAGE と同じにしておく。
set -e
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
IMAGE=${ABATLAS_IMAGE:-ghcr.io/suwa-sh/as-built-atlas:dev}
BUILD=0
UPGRADE=0
case "$1" in
--build)
	BUILD=1
	shift
	;;
--upgrade)
	UPGRADE=1
	BUILD=1
	shift
	;;
esac
if [ "$#" -eq 0 ]; then
	echo "使い方: redeploy.sh [--build | --upgrade] <分析リポジトリ>..." >&2
	exit 2
fi
docker build -q -t "$IMAGE" "$ROOT" >/dev/null
echo "image: $IMAGE"
START=$PWD
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT
# 出力を畳みつつ、終了コードを失わないように、いったんファイルに受ける
run_step() {
	label=$1
	shift
	if "$@" >"$LOG" 2>&1; then
		tail -1 "$LOG"
	else
		echo "$label が失敗した。起動し直していない: $repo" >&2
		tail -20 "$LOG" >&2
		exit 1
	fi
}
for repo in "$@"; do
	cd "$START" # 相対パスで渡されても、毎回、起動した場所から探す
	if [ ! -f "$repo/compose.yaml" ]; then
		echo "分析リポジトリではない (compose.yaml が無い): $repo" >&2
		exit 1
	fi
	cd "$repo"
	if [ "$UPGRADE" -eq 1 ]; then
		run_step "upgrade" docker compose run --rm abatlas upgrade .
	fi
	if [ "$BUILD" -eq 1 ]; then
		run_step "build" docker compose run --rm abatlas build .
	fi
	docker compose up -d --force-recreate api >/dev/null 2>&1
	echo "restarted: $repo"
done
sleep 3
