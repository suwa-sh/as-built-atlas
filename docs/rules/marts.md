# 集計表と宣言のルール

[← rules の地図へ](README.md)

対象: `dbt-template/` (コアの集計表)、`profiles/*/dbt-template/` (プロファイル固有の集計表)、`abatlas/declarations.py` (宣言の検査)。仕組みの説明は [../architecture/pipeline.md](../architecture/pipeline.md) です。

## 守ること

| 決まり | 理由 | 守っているもの |
|---|---|---|
| **コードは、集計表の名前を知らない。** 画面・API・MCP は、宣言 (`meta.abatlas`) だけを読む | 集計表を足しても、コードを直さない。プロファイルや分析リポジトリが、独自の集計表を足せる | `tests/test_navigation_api.py` |
| 画面が特定の表を探すときは、宣言の項目で探す (`subject`、`view`、`tags`、`keys`) | 同上 | 同上 |
| 「どう描くか」は `view`、「どこに載せるか」は `subject` と `tags` | 役目を混ぜない ([ADR 0003](../adr/0003-layer-diagram-view.md)) | 宣言の検査 |
| 宣言の文字 (`title`、`hint`、`labels`、`filters` の `label`、`description`) は、呼び名を `"{id}"` で書く | 呼び名の正本は用語集 ([ADR 0002](../adr/0002-labels-from-glossary.md)) | 宣言の検査、`tests/test_terms.py` |
| コアの `title` と `labels` は、`"{id}"` と、記号・単位だけで組む | 言い回しが、表ごとに揺れない | `tests/test_terms.py` |
| `show` の列は、左から概念を絞り込む順に並べる (区分 → 層 → 種類 → 個々のもの → 中身と数) | 一覧を、左から読める | — |
| dbt は、`dbt-template/` の中で直接動かさない。`abatlas build` が、作業用の場所に合成して動かす | 3 層 (core / profile / repo) を合わせて検査する | — |

## 表示の種類を足すとき

触る場所は 6 つです。手順は、skill `dev-add-view` にあります。

| 触る場所 | 足すもの |
|---|---|
| `abatlas/declarations.py` の `VIEWS` | 必須と任意の `keys` |
| `dbt-template/models/core/schema.yml` の冒頭の説明 | 表示の種類の一覧と、`keys` の意味 |
| `abatlas/webapp/views/<name>.js` と、`views/index.js` の `renderers` | 描き方 |
| `abatlas/webapp/model/vocab.js` の `VIEW_ORDER` と `viewHint` | 並び順と、読み方の既定の文 |
| `abatlas/webapp/css/views.css` | 見た目 |
| `docs/architecture/pipeline.md` と `webapp.md` | 表示の種類の表 |

## メニューの項目 (`subject`) を足すとき

| 触る場所 | 足すもの |
|---|---|
| `abatlas/declarations.py` の `SUBJECTS` | 新しい `subject` |
| `schema/vocab/terms.yaml` | 呼び名 |
| `abatlas/webapp/model/vocab.js` の `SUBJECT_TERM` | `subject` → 呼び名の id |
| `abatlas/webapp/pages/<name>.js`、`app.js` の `route` と `buildNav` | 画面と、経路 |
| `docs/architecture/webapp.md` | 画面の一覧 |

## 集計表を足す・変えるとき

- 列を変えたら、宣言の `keys` / `show` / `labels` / `filters` も合わせます (検査が、列の実在を見ます)。
- 宣言の `origin` は、定義の置き場所と同じにします (`models/core/` なら `core`)。集計の検査が、食い違いを止めます (`tests/test_webapp.py`)。
- コアの集計表を足したら、`docs/architecture/pipeline.md` の「コアの集計表」に 1 行足します。
- 数を数える列は、何を数えているかを `labels` と `hint` に書きます (例: 箇所の数、入口の数)。
