#!/usr/bin/env bash
# toolbox plugin の mid-harness skill を .agents/skills/mid-harness/ に取り込む (配布物に同梱するため)。
# 使い方: scripts/vendor-mid-harness.sh [<mid-harness の skill ディレクトリ>]
# 省略時は ~/.claude/plugins/cache/suwa-sh-claude-plugins/toolbox/<最新版>/skills/mid-harness を使う。
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:-}"
if [ -z "$SRC" ]; then
	BASE="$HOME/.claude/plugins/cache/suwa-sh-claude-plugins/toolbox"
	VER="$(for candidate in "$BASE"/*/skills/mid-harness/SKILL.md; do
		[[ -f $candidate ]] || continue
		version_dir=${candidate%/skills/mid-harness/SKILL.md}
		basename "$version_dir"
	done | sort -V | tail -1)"
	SRC="$BASE/$VER/skills/mid-harness"
fi
test -f "$SRC/SKILL.md" || {
	echo "mid-harness が見つからない: $SRC" >&2
	exit 2
}
VER_JSON="$(dirname "$(dirname "$SRC")")/.claude-plugin/plugin.json"
VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$VER_JSON" 2>/dev/null || echo unknown)"

# The plugin cache carries the release version. A clean source checkout also has a Git commit.
source_ref=""
if git -C "$SRC" ls-files --error-unmatch -- SKILL.md >/dev/null 2>&1 &&
	git -C "$SRC" diff --quiet HEAD -- . &&
	[[ -z $(git -C "$SRC" ls-files --others --exclude-standard -- . ':!**/__pycache__/**' ':!**/.pytest_cache/**') ]]; then
	source_ref=" (Git $(git -C "$SRC" rev-parse HEAD))"
fi

DST=.agents/skills/mid-harness
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
rsync -a --exclude '__pycache__' --exclude '.pytest_cache' "$SRC/" "$stage/"
mkdir -p "$DST"
rsync -a --delete "$stage/" "$DST/"
cat >"$DST/VENDOR.md" <<EOF
# vendored: mid-harness

- 出自: suwa-sh/suwa-sh-claude-plugins の toolbox plugin (skills/mid-harness)
- 版: toolbox $VERSION$source_ref
- 取り込み日: $(date +%F)
- 取り込み方: 上流を記録した版で checkout し、\`scripts/vendor-mid-harness.sh <上流の作業ツリー>/plugins/toolbox/skills/mid-harness\` を実行する
- 目的: 配布物 (OSS 層) だけで、分析リポジトリの adapter 生成・drift 検査・trust 確認ができるようにする
EOF
echo "vendored mid-harness $VERSION -> $DST"
