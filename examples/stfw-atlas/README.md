# stfw の CLI をたどる

シナリオテストを実行する Go 製 CLI の公開コマンド20件を列挙し、次の3件を `gpt-6.2-sol` で分析しました。対象は [stfw v1.7.1](https://github.com/scenario-test-framework/stfw/tree/v1.7.1)（コミット `866a1edf`）、ライセンスは [Apache License 2.0](https://github.com/scenario-test-framework/stfw/blob/v1.7.1/LICENSE) です。

| 入口 | 3D 図でたどれる処理 |
|---|---|
| `stfw run` | シナリオを読み、事前検証を経て実行する |
| `stfw validate` | シナリオの構成やプラグインの依存を検査する |
| `stfw report` | 保存済みの実行結果を読み、レポートを作る |

構成の「3D」で入口を選び、面や点を選ぶと、そこに至る呼び出しが強調されます。分析結果は AI によるソースの読み取りです。

## 手元で開く

as-built-atlas の checkout のルートで以下を実行します。

```bash
mkdir -p ~/abatlas-try
cp -R examples/stfw-atlas ~/abatlas-try/
cd ~/abatlas-try
git clone --branch v1.7.1 --depth 1 https://github.com/scenario-test-framework/stfw.git stfw
cd stfw-atlas
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile cli
docker compose run --rm abatlas build .
docker compose up -d api
```

ブラウザで [3D 図](http://127.0.0.1:8765/#/overview?view=3d) を開きます。
