# umami-atlas (画面を持つシステムを分析した見本)

公開されている Web 解析ソフト [umami](https://github.com/umami-software/umami) (v3.4.1、Next.js の App Router) の画面を、as-built-atlas の `ui-nextjs` プロファイルで分析した状態の、分析リポジトリの資産です。

`kotori-books-atlas` (バッチの見本) との違い:

| | kotori-books-atlas | umami-atlas |
|---|---|---|
| 対象 | 架空のバッチ (このリポジトリに同梱) | 実在の公開ソフト (同梱しない。自分で clone する) |
| 分析結果 | 対象と同じ仕様から生成した**正解** | AI が分析した**実例**。正解ではない。使ったモデルは、結果ごとに `analyzer.model` に書いてある (枠と一部の画面の 26 件は Claude Fable、残りの 57 件は Claude Opus) |
| 件数 | 入口 34 件すべて | 入口 83 件すべて (枠 6 つ + 画面 60 件 + 部品 17 件) |

## 入っているもの

- `analysis/work-definition.yaml` 対象と範囲 (umami の commit `559e3c6` = v3.4.1)
- `analysis/entry-list.yaml` 入口 83 件 (画面 60 + 画面を包む共通の枠 6 + 部品 17。すべて承認済み)。`abatlas enumerate` の出力で、画面ごとの「通る枠」(`within`) が付いている。部品は、利用者が組むボードの画面が、保存された設定で選んで描くもの (登録表の項目 1 つ = 入口 1 件)。ボードを描く画面 4 つは、登録表を引く段で止めて、部品へのつながり (`embed`) を持つ。共有リンクの画面は、描く画面の入口へのつながりを持つ。部品のうち 1 つ (`part_p.shared_a.WebsiteControls`) は、サイトの画面 21 個が自分で描く、期間と絞り込みの操作の部品。描く側は、この部品を描く段で止めて、つながり (`embed`) で指す
- `analysis/results/*.yaml` 分析結果 83 件 (合わせて約 11 MB)
  - 枠 6 つ: 全体 / ログイン後 / サイト / 設定 / 管理 / 共有ページ (id が `layout_l` で始まる)
  - 画面 60 件: すべての画面
- `analysis/reviews/*.yaml` 分析結果ごとのレビュー (別の文脈の AI が、根拠の行を開いて確かめた記録)
- `.env` `ABATLAS_TARGET=../umami`

umami のコードは入っていません。分析結果が持つのは、ファイルのパスと行番号、処理の要約、読み書きするデータの名前です。

## 見どころ

- **画面と、画面を包む枠を別々に分析している。** 画面のページに「この入口を包む入口」、枠のページに「この入口の中で動く入口」が出て、行き来できる。枠の処理 (ログイン確認など) は枠の結果に 1 回だけあり、画面の結果には無い
- **ブラウザ側のフックから API の受け口への橋渡し。** URL の文字列 (例 `/websites/${websiteId}/stats`) を、その形に当たる `route` ファイルの関数に対応付けている
- **同じ処理に 2 つの DB 向けの実装がある。** PostgreSQL 用と ClickHouse 用の SQL を、両方とも読み書きに書いている (サイトの概要、ファネル)
- **確かめられなかった点も残している。** 全体で 97 件 (理由付き)。分析の状態のページで、理由ごとに見られる
- **入口をまたいで見る表 (メニューの aspects)。** 読み書きする列と書く値、ほかの入口へのつながり、権限の確認 (枠が行う確認は、その中で動く画面の行としても出る)、条件つきの呼び出し、動きを変える設定、業務のルール、同じデータを書く入口と読む入口のつながり、どの入口からも辿られないファイル

## 使い方

**このディレクトリを as-built-atlas の checkout の外へコピーし、隣に umami を clone する** (`abatlas init` が git リポジトリとして初期化し、中ハーネスと製品別の設定を書き足すため)。

```bash
mkdir -p ~/abatlas-try && cp -r examples/umami-atlas ~/abatlas-try/
cd ~/abatlas-try
git clone https://github.com/umami-software/umami.git
git -C umami checkout 559e3c607c23d2c72d9bd4f6481bda428255323c   # v3.4.1 (分析結果の根拠の行は、この版のもの)
```

続けて、分析リポジトリとして初期化し、集計して画面を開きます (イメージの用意は as-built-atlas の README の「10 分で試す」と同じ)。

```bash
cd ~/abatlas-try/umami-atlas

# 分析リポジトリとして初期化 (OSS 所有のファイルと中ハーネスを置く。既にある .env と analysis/ はそのまま)
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile ui-nextjs

docker compose run --rm abatlas validate work analysis/work-definition.yaml
docker compose run --rm abatlas enumerate analysis/entry-list.yaml   # 入口 83 件 (承認済みのまま)
docker compose run --rm abatlas validate result analysis/results/login.yaml --work analysis/work-definition.yaml   # 根拠の行が、clone した umami に実在すること
docker compose run --rm abatlas build .        # ETL → dbt build → analysis/data/abatlas.duckdb
docker compose up -d api                        # webapp http://localhost:8765  /  MCP http://localhost:8765/mcp
```

ブラウザで <http://localhost:8765> を開き、「入口」から `settings › teams › [teamId]` (チームの設定) や `(layout) › (main)` (ログイン後の枠) を開きます。メニューの aspects では、入口をまたいだ表 (権限のまとめ、業務のルール、設定への依存など) を見られます。

## 分析結果についての注意

- 分析結果は AI が書いたもので、人が 1 件ずつ読んで確かめてはいません。機械チェック (形式、根拠のファイルと行の実在) と、AI によるレビューは通っています。レビューの指摘のうち、直した印 (`resolved`) が付いていないものが 10 件の入口に合わせて 12 件あります (直さなかった理由は、結果ごとの `notes` に書いてあります)。分析の skill の版は、部品を分けた後に分析し直した 39 件が 0.4.1、残りの 44 件が 0.4.0 です (0.4.1 は、固定の値で閉じた呼び出しを辿らない。3 つ目の数字だけの違いなので、0.4.0 の結果も、そのまま使えます)
- 大きい入口があります (ボードを組む画面は、処理の段が 185)。保存された設定で描く部品が決まる画面で、候補の部品をすべて辿っているためです
- 入口によって、書き方に揺れがあります (同じ部品を、どこまで辿るか。届かないように見える分かれ道を、段に書くか要約に書くか)。どの入口にも出る共通の段 (ログインの確認、持ち主の確認、API の接続先の設定) は、後からそろえました。そろえた入口では、結果の `notes` や要約の古い説明が、直した中身と食い違っている所があります (中身が正しい)
- umami は Umami Software, Inc. の著作物で、MIT License です。この見本は umami の公式の文書ではなく、umami の開発元とは関係ありません
- umami の版が変わると、根拠の行番号はずれます。別の版を分析するときは、作業定義の `commit` を変えて分析し直します
