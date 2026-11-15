# プロファイルのルール

[← rules の地図へ](README.md)

対象: `profiles/<id>/` (`profile.yaml`、`context.md`、`dbt-template/`、`extractors/`)。仕組みの説明は [../architecture/profiles.md](../architecture/profiles.md) です。

## 守ること

| 決まり | 理由 | 守っているもの |
|---|---|---|
| 形式の定義、ETL、コアの集計表、画面は、プロファイルに依らない。対象の種類ごとの違いは、プロファイルに閉じる | プロファイルを足しても、コアを直さない | `tests/test_examples_umami.py` (2 本目のプロファイル) |
| ツールが読むことは `profile.yaml`、エージェントが読むことは `context.md` に書く | 読み手を分ける | `abatlas validate profile` |
| 分析者によって書き方が割れた所は、`context.md` に、決まりと理由を書く | 突き合わせが、書き方の違いで食い違わない | — |
| 決定論で決まること (入口の列挙、包む関係) は、`profile.yaml` の宣言からツールが決める。エージェントに決めさせない | 同じ入力から、同じ結果を出す | `tests/test_file_glob.py` |
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
- このリポジトリの `profiles/` を直したら、見本で確かめます。バッチのプロファイルは生成し直し (skill `dev-sample-regen`)、画面のプロファイルは `tests/test_examples_umami.py` で確かめます。

## プロファイルを足すとき

手順は [../architecture/profiles.md](../architecture/profiles.md) の「プロファイルを増やす手順」です。足したら、次も直します。

| 直す場所 | 足すもの |
|---|---|
| `docs/architecture/profiles.md` | プロファイルの表に 1 行。バッチと違う所があれば、その節 |
| `README.md` | プロファイルの表に 1 行 |
| `tests/` | そのプロファイルの検査と、見本があれば見本のテスト |
