---
name: dev-sample-regen
description: as-built-atlas の公開サンプル (examples/ のことり書店) を生成スクリプトから作り直し、差分が意図した範囲に収まっていることを確かめ、必要なら README の画像を今の画面で撮り直す手順。形式の定義、プロファイル、抽出器、生成スクリプトを変えたとき、画面の見た目を変えて README の画像が古くなったとき、test_examples が落ちたときに使う。
---

# 見本を作り直す

守ることは `docs/rules/examples.md`。全体の流れは skill `dev-change` に従う。

## いつ要るか

| 変えたもの | 生成し直し | README の画像の撮り直し |
|---|---|---|
| 形式の定義 (`schema/`) | 要る | — |
| プロファイル (`profiles/batch-kestra/`)、抽出器 | 要る | 図に出るなら要る |
| 生成スクリプト (`examples/generator/kotori_books.py`) | 要る | 図に出るなら要る |
| 画面の見た目 | — | 要る |

ことり書店のほかの見本 (`examples/umami-atlas/` など、プロファイルごとに 1 つ) は、生成ではない。手で直さず、手元の分析リポジトリで分析し直した資産を、`examples/generator/import_atlas.py` で写す (`docs/rules/examples.md`)。写した後は、`uv run pytest -q tests/test_examples_profiles.py` で確かめる。

## 1. 生成し直す

```bash
uv run python examples/generator/kotori_books.py
```

## 2. 差分を確かめる

```bash
git status --short examples
```

| 見ること | 理由 |
|---|---|
| 変わったファイルが、意図した範囲か | 例: 作業定義だけに足すつもりの項目が、分析結果 34 件すべてに写ることがある (生成スクリプトが、同じ値を使い回しているため) |
| 対象のコード (`examples/kotori-books/`) が変わったか | 変わると、内容のハッシュ (`target.commit`) も変わり、全部の結果が変わる。意図していなければ、原因を調べる |
| 実在の名前、手元のパスが入っていないか | 公開するリポジトリ |

意図しないファイルが変わっていたら、生成スクリプトを直して、もう一度生成する。**生成されたファイルを、手で直さない。**

## 3. テスト

```bash
uv run pytest -q tests/test_examples.py
uv run pytest -q
```

`tests/test_examples.py` は、生成し直して差が無いこと、全件が機械の検査に通ること、列挙の出力と一致すること、初期化から集計までが通ることを見る。

## 4. README の画像を撮り直す (画面の見た目が変わったとき)

1. skill `dev-webapp-verify` の手順で、ことり書店の確認用の分析リポジトリを、**配布物の既定のプロファイル**で集計し直して起動する。変わった見本のファイルは、先に写しておく。
2. `README.md` が載せているページを、広い幅 (1440)、見えている範囲 (`view`) で撮る。

   | 画像 | ページ |
   |---|---|
   | `webapp-architecture.jpg` | `#/overview` |
   | `webapp-entries.jpg` | `#/entries` |
   | `webapp-entry.jpg` | 入口 1 件 (例: `#/entry/daily/sales/settle_orders`) |
   | `webapp-datastore.jpg` | `#/data` で、行と列を開いた状態 (開く操作が要るので、操作のスクリプトで撮る) |

3. 撮った画像を、目で見る (畳んだままの表、試しに直したプロファイルの状態で撮っていないか)。
4. JPEG にして、`docs/images/` に置く (macOS なら `sips -s format jpeg -s formatOptions 82 <png> --out <jpg>`)。
5. `README.md` の、画像の下の説明が、今の画面と合っているかを読む。
6. 使わなくなった画像は消す。

## 報告に書くこと

- 生成し直して、変わったファイルの範囲。
- 撮り直した画像と、目で見たかどうか。
