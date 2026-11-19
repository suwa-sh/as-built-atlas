# プロファイルのルール

[← rules の地図へ](README.md)

対象: `profiles/<id>/` (`profile.yaml`、`context.md`、`dbt-template/`、`extractors/`)。仕組みの説明は [../architecture/profiles.md](../architecture/profiles.md) です。

## 守ること

| 決まり | 理由 | 守っているもの |
|---|---|---|
| 形式の定義、ETL、コアの集計表、画面は、プロファイルに依らない。対象の種類ごとの違いは、プロファイルに閉じる | プロファイルを足しても、コアを直さない | `tests/test_examples_profiles.py` (どのプロファイルの見本も、同じコアで集計が通る) |
| ツールが読むことは `profile.yaml`、エージェントが読むことは `context.md` に書く | 読み手を分ける | `abatlas validate profile` |
| 分析者によって書き方が割れた所は、`context.md` に、決まりと理由を書く | 突き合わせが、書き方の違いで食い違わない | — |
| 決定論で決まること (抽出器で取れる入口、包む関係) は、`profile.yaml` の宣言からツールが決める。エージェントに決めさせない | 同じ入力から、同じ結果を出す | `tests/test_file_glob.py` |
| 抽出器で取れない入口がある種類では、`context.md` に、取れない入口の探し方を書く。エージェントが足す入口は、`listed` 抽出器の設定に、根拠と理由を付けて書かせる | 道具だけでは漏れる入口を、気づかれないままにしない ([ADR 0011](../adr/0011-agent-enumerates-entries.md)) | `tests/test_ast_query.py` |
| 表示項目 (`label`、`layers` の `label` / `tier`、`hierarchy.notes` の `text`) は、呼び名を `"{id}"` で書く | [ADR 0002](../adr/0002-labels-from-glossary.md) | プロファイルの検査 |
| `layers[].invokes_next` は自由文。コードの例を書いてよい (呼び名の置き換えの対象外) | 波かっこを含むコードを書ける | — |
| 分析の判断が変わる直しでは、`version` を上げる | 再分析するかどうかは、版の比較で決まる | — |

## 版を上げるか

| 直し | `version` |
|---|---|
| 層の増減で、既存の結果の層が変わる。入口の拾い方が変わる。包む関係が変わる。`context.md` の判断の決まりが変わる | 上げる |
| 表示だけの直し (呼び名、区分の名前、説明の文)。既存の結果と矛盾しない、使っていない層の削除 | そのまま |

## 配布物のコピーと、自分用のプロファイル

- 分析リポジトリの `.abatlas/profiles/<id>/` は、配布物のコピーです。`upgrade` で置き換わります。**ここを直す手順を、文書や skill に書きません。**
- 利用者が直すときは、`analysis/profiles/<id>/` に写して、作業定義の `profile.dir` を書き換えます ([ADR 0006](../adr/0006-profile-dir-single-source.md))。
- このリポジトリの `profiles/` を直したら、そのプロファイルの見本で確かめます ([examples.md](examples.md))。`batch-kestra` は生成し直し (skill `dev-sample-regen`)、ほかは `tests/test_examples_profiles.py` で確かめます (`ui-nextjs` は `tests/test_examples_umami.py` も)。
- プロファイルを足すときは、見本も足します。プロファイルの版を上げたら、その見本を分析し直します (テストは、今の版で分析した結果だけを通す)。

## プロファイルを足すとき

手順は [../architecture/profiles.md](../architecture/profiles.md) の「プロファイルを増やす手順」です。足したら、次も直します。

| 直す場所 | 足すもの |
|---|---|
| `docs/architecture/profiles.md` | プロファイルの表に 1 行。バッチと違う所があれば、その節 |
| `README.md` | プロファイルの表に 1 行 |
| `tests/` | そのプロファイルの検査と、見本があれば見本のテスト |
