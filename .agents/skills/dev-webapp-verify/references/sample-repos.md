# 見本の分析リポジトリを用意する

確認用の分析リポジトリは、このリポジトリの checkout の**外**に作る (`init` が git リポジトリとして初期化し、設定を書き足すため)。場所は、開発する人が決める。以下では `<work>` と書く。

イメージは、開発用のタグ (`ghcr.io/suwa-sh/as-built-atlas:dev`) を使う。先に、checkout のルートで作っておく。

```bash
docker build -t ghcr.io/suwa-sh/as-built-atlas:dev .
```

## ことり書店 (バッチの見本)

```bash
mkdir -p <work>/kotori
cp -R examples/kotori-books examples/kotori-books-atlas <work>/kotori/
cd <work>/kotori/kotori-books-atlas
```

`.env` に、次の行を足す。ポートは、もう 1 つの見本と重ならない番号にする。

```text
ABATLAS_IMAGE=ghcr.io/suwa-sh/as-built-atlas:dev
ABATLAS_PORT=8771
```

```bash
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:dev init . --profile batch-kestra
docker compose run --rm abatlas build .
docker compose up -d api
```

## umami (画面を持つシステムの見本)

対象のコードは同梱していないので、隣に clone する。手順の正本は `examples/umami-atlas/README.md`。

```bash
mkdir -p <work>/umami-try
cp -R examples/umami-atlas <work>/umami-try/
cd <work>/umami-try
git clone https://github.com/umami-software/umami.git
```

`examples/umami-atlas/README.md` に書かれたコミットを checkout してから、ことり書店と同じように、`.env` (`ABATLAS_IMAGE` と、別の `ABATLAS_PORT`)、`init --profile ui-nextjs`、`build`、`up -d api` を行う。

## 別の端末から開くとき

既定では、画面と API は、同じ機械からだけ開ける。同じネットワークの別の端末から開くときだけ、`.env` に次を足す。**外から開けるようになるので、確認が終わったら戻す。**

```text
ABATLAS_BIND=0.0.0.0
ABATLAS_ALLOWED_HOSTS=<この機械の名前か IP アドレス>
```

## 検査と集計をやり直す (形式、ツール、集計表を変えたとき)

確認用の分析リポジトリの中で行う。検査と列挙は、プロファイルを、作業定義の `profile.dir` から自動で読む (集計と同じファイル。読んだ場所が、出力の最初に出る)。

```bash
docker compose run --rm abatlas validate work analysis/work-definition.yaml
docker compose run --rm abatlas validate profile <profile.dir>/profile.yaml   # <profile.dir> = 作業定義の profile.dir の値 (既定は .abatlas/profiles/<id>。自分用に写していれば、その場所)
docker compose run --rm abatlas validate entries analysis/entry-list.yaml
docker compose run --rm abatlas validate result analysis/results/*.yaml --work analysis/work-definition.yaml
docker compose run --rm abatlas build .
```

出力に「プロファイルを自動で読めない」「配布物と違う」と出たら、確かめたことにしない。原因 (作業定義の `profile.dir`、配布物のコピーの更新) を直す。

- 先に、イメージを作り直す (`scripts/redeploy.sh <分析リポジトリ>`)。検査も集計も、イメージの中のツールが動く。
- umami の見本は、対象の clone が隣にあるときだけ、`--work` での根拠の行の検査ができる。

## プロファイルを変えたとき

このリポジトリの `profiles/<id>/` を変えたときの、見本での確かめ方。変えた内容で、要る手順が違う。

| 変えた内容 | 要る手順 |
|---|---|
| 表示だけ (呼び名、区分の名前、説明の文)、使っていない層の増減 | 1 |
| 包む関係 (`within`) | 1 → 3 → 5 |
| 入口の拾い方 (抽出器、既定のパラメータ) | 1 → 2 → 3 → 5 |
| 分析の判断が変わる直し (`version` を上げた) | 1 → (2 → 3) → 4 → 5 |

| 手順 | やること |
|---|---|
| 1 | **新しいイメージを作ってから**、配布物のコピーを置き換える: `scripts/redeploy.sh --upgrade <分析リポジトリ>` (イメージの作り直し → `upgrade` → 集計 → 起動し直し、の順に行う)。古いイメージのまま `upgrade` すると、コピーは古いプロファイルのままになる。手順 2 以降が要る変更では、この時点の集計は止まるか、古い一覧のままになるので、手順 5 でやり直す |
| 2 | `analysis/entry-list.yaml` の `extractors` を、新しい拾い方に書き換える (列挙が実行するのは、一覧に書かれた抽出器とパラメータ) |
| 3 | 列挙し直す: `docker compose run --rm abatlas enumerate analysis/entry-list.yaml`。一覧の差分を見て、承認の状態を確かめる |
| 4 | 影響する入口を分析し直す (分析 skill)。ことり書店は、分析し直さず、生成スクリプトを直して生成し直したものを写す (skill `dev-sample-regen`) |
| 5 | 集計し直して起動する: `scripts/redeploy.sh --build <分析リポジトリ>` (手順 2〜4 を行ったとき。手順 1 だけなら、手順 1 の中で済んでいる) |

- 包む関係を変えて、列挙し直さずに集計すると、集計が止まる (入口の一覧の `within` が、今のプロファイルの宣言と合わないため)。
- 入口の拾い方を変えて、列挙し直さずに集計すると、**集計は成功するが、古い入口の一覧のまま**になる。画面に変更が出たと取り違えない。
- 手順の正本 (利用者向け) は、`docs/guide/customize-profile.md`。

## 見本を作り直すとき

- 見本の中身 (生成スクリプト、プロファイル) を変えたら、変わったファイルを、確認用の分析リポジトリへ写してから、集計し直す。
- プロファイルを試しに直したときは、確認が終わったら、配布物の既定のプロファイルに戻す (README の画像を、直したままの状態で撮らないため)。
- 確認用の分析リポジトリと、撮った画像は、このリポジトリに入れない。
