---
name: abatlas-classify-data
description: 分析結果に出てきた列 (データと、その中の列) を、データの辞書 (analysis/data-dictionary.yaml) に集め、列ごとの区分 (個人情報、認証の情報など) の案を書く。区分を確かめて承認するのは人。「個人情報の列を洗い出して」「データの辞書を作って」「区分の案を出して」と頼まれたとき、分析結果が増えた後に辞書を更新するときに使う。
---

# データの区分の案を書く

区分 (個人情報など) は、分析結果には書かない。同じ列の区分が、入口ごとにぶれないように、データの辞書に 1 回だけ書く。**エージェントが書くのは案 (`status: candidate`) まで。承認 (`approved`) は人がする。** 集計は、承認された行だけを使う。

## 入力

- 分析リポジトリのルート (カレントディレクトリ)。`analysis/results/` に、分析結果がある
- OSS の参照物 `<oss>`: カレントディレクトリに `.abatlas/` があればそれ (分析リポジトリ)。無ければこの SKILL.md の実体の 3 つ上 (OSS の checkout)
- ツールの呼び方 `<abatlas>`: 分析リポジトリでは `docker compose run --rm abatlas`。OSS の checkout では `uv run abatlas`
- 出力: `analysis/data-dictionary.yaml` (形式は `<oss>/schema/data-dictionary.schema.json`)

## 手順

1. 列を集める: `<abatlas> dictionary .`。分析結果の `io[].fields` に出てきた列のうち、辞書に無いものが、`status: candidate` で足される (区分は空)。既にある行は変わらない。出力の `unclassified` が、区分の無い行の数
2. 区分の語彙を読む: `<oss>/schema/vocab/data-categories.yaml` (区分の id と、当てはめ方)
3. 区分の無い行 (`category` が無い行) に、案を書く

   | 書く項目 | 内容 |
   |---|---|
   | `category` | 語彙の id。どれにも当てはまらないと判断したら `none` |
   | `note` | 判断の根拠 (何を見てそう判断したか)。迷ったときは、迷った点 |

   - 判断の材料は、列の名前、データの名前、分析結果の中での使われ方 (`analysis/results/` の、その列を書いている読み書きの `detail` と、処理の `summary`)。範囲の中にデータの定義 (スキーマのファイル、モデルの定義) があれば、それも読む
   - 名前だけでは決められない列 (例: `data`、`value`、`payload`、`metadata`) は、推測で `none` にしない。`category` を書かず、`note` に「中身が名前から決まらない」と書く
   - 利用者にひも付く識別子 (利用者の id、セッションの id、端末の id) は、`personal`
4. **`status` は `candidate` のままにする。** 既に `approved` の行は、区分も `note` も変えない (変えるべきだと考えたら、報告に書く)
5. 確かめる: `<abatlas> dictionary . --dry-run` (辞書が形式に合わなければ、ここで止まる。区分が語彙に無い、同じ列が 2 回ある、など)
6. 報告: 足した列の数、区分ごとの案の数、区分を書かなかった列と理由。**人が次にすること** (案を確かめて、`status` を `approved` に変える。その後に集計し直す) を書く

## 禁止

- `status` を `approved` に変える
- 承認済みの行を書き換える
- 分析結果 (`analysis/results/`) と、対象リポジトリを変える
- 辞書に、分析結果に無い列を足す (列は、手順 1 のコマンドだけが足す)
