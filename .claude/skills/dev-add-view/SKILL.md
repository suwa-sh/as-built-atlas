---
name: dev-add-view
description: as-built-atlas の画面に、新しい表示の種類 (集計表の宣言の view) か、新しいメニューの項目 (宣言の subject) を足す手順。宣言の検査、画面の描き方の登録、呼び名、見た目、文書を、漏れなく同じ変更で直す。新しい図や表の見せ方を足したい、集計表を新しい形で描きたい、メニューに項目を増やしたいと頼まれたときに使う。
---

# 表示の種類か、メニューの項目を足す

守ることは `docs/rules/marts.md` と `docs/rules/webapp.md`。全体の流れは skill `dev-change` に従い、その「3. 直す」で、ここの手順を使う。

## 先に確かめること

| 問い | はい | いいえ |
|---|---|---|
| 既にある表示の種類で描けないか | 宣言の `view` と `keys` だけで済ませる | 下へ |
| 「どう描くか」が新しいのか | 表示の種類 (`view`) を足す | 「どこに載せるか」なら、`subject` か `tags` |
| 同じ図を、2 つ以上のページで出すか | 部品を 1 つにして、共有する | — |

## 表示の種類 (`view`) を足す

順に直す。途中で止めると、宣言の検査かテストが落ちる。

| 順 | 場所 | やること |
|---|---|---|
| 1 | `abatlas/declarations.py` の `VIEWS` | 必須と任意の `keys` を足す。何の列かを、コメントに書く |
| 2 | `dbt-template/models/core/schema.yml` の冒頭 | 表示の種類の一覧 (数も) と、`keys` の意味を足す |
| 3 | 集計表の `meta.abatlas` | `view` と `keys` を、新しい種類で宣言する |
| 4 | `abatlas/webapp/views/<name>.js` | 描き方を書く。`(m, data, ctx)` を受けて、要素を返す |
| 5 | `abatlas/webapp/views/index.js` の `renderers` | 1 行足す |
| 6 | `abatlas/webapp/model/vocab.js` | `VIEW_ORDER` に足し、`viewHint` に、読み方の既定の文を足す (呼び名は `term()` で引く) |
| 7 | `abatlas/webapp/css/views.css` | 節を足す。色・線・余白は `DESIGN.md` の決まりに合わせる |
| 8 | テスト | 宣言の検査のテスト、その表を探すテスト (`tests/test_navigation_api.py`) を直す |
| 9 | 文書 | `docs/reference/marts.md` の表示の種類の表、`docs/architecture/webapp.md` の描き方、`docs/rules/webapp.md` の `views/` の表、`DESIGN.md` の部品の表 |

描き方 (順 4) を書くときは、`docs/rules/webapp.md` の「作りの決まり」と「見せ方の決まり」を読んでから書く。書いた後に、次の場合を 1 つずつ考える。

| 場合 | 見ること |
|---|---|
| 行が 0 件 | 何が出るか |
| 不明、上限で切った数を含む | どう見分けが付くか |
| 絞り込みを付けた | 合わないものが、どうなるか |
| プロファイルが違う | 見本 2 つで、行の中身がどう変わるか |

## メニューの項目 (`subject`) を足す

| 順 | 場所 | やること |
|---|---|---|
| 1 | `abatlas/declarations.py` の `SUBJECTS` | 足す |
| 2 | `schema/vocab/terms.yaml` | 呼び名を足す |
| 3 | `abatlas/webapp/model/vocab.js` の `SUBJECT_TERM` | `subject` → 呼び名の id |
| 4 | `abatlas/webapp/model/catalog.js` | その `subject` の表を探して、`model` に持たせる |
| 5 | `abatlas/webapp/pages/<name>.js` | 画面を書く |
| 6 | `abatlas/webapp/app.js` | `route` に 1 行、`buildNav` に 1 行 (表が宣言されているときだけ出す) |
| 7 | 文書 | `docs/architecture/webapp.md` の画面の一覧、`README.md` のメニューの表、`DESIGN.md` |

## 確かめる

1. `uv run pytest -q`
2. skill `dev-webapp-verify` で、見本 2 つ、幅 2 つ。集計に関わるので、`--build` を付ける。
3. 新しい表示が、集計表のページ (`#/mart/<名前>`) でも出ることを確かめる (汎用の表示も、同じ描き方を使う)。
4. 古い集計表 (新しい宣言が無い) を開いても、画面が落ちないことを考える。落ちるなら、無いときの出し方を足す。
