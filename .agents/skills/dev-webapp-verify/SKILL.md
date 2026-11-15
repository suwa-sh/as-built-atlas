---
name: dev-webapp-verify
description: as-built-atlas の画面 (abatlas/webapp/) や、画面に出るデータ (集計表、宣言、meta、プロファイル) を変えた後に、配布物のイメージを作り直し、見本の分析リポジトリ 2 つを起動し直して、実際のブラウザで広い幅と狭い幅を撮り、コンソールのエラーと横のはみ出しを確かめる手順。画面を直したとき、集計や形式の変更が画面にどう出るかを確かめたいとき、README の画像を撮り直すときに使う。
---

# 画面を実物で確かめる

画面の動きは、自動のテストでは見ていない。変更したら、ここの手順で確かめる。守ることは `docs/rules/webapp.md` の「確かめ方」。

## 用意 (最初の 1 回)

見本の分析リポジトリを、このリポジトリの checkout の**外**に 2 つ作る。作り方は [references/sample-repos.md](references/sample-repos.md)。

| 見本 | プロファイル | これでしか出ない表示の例 |
|---|---|---|
| ことり書店 | `batch-kestra` | 確かめられていない線 (点線)、function が 0 件の層 |
| umami | `ui-nextjs` | 入口を包む入口、入口の種類が 2 つ、未分析の入口 |

撮影には、Python の playwright と、そのブラウザが要る (`uv run --with playwright playwright install chromium`)。ブラウザを別の場所に置いているときは、環境変数 `ABATLAS_CHROME` に実行ファイルの場所を入れる。

## 手順

### 1. イメージを作り直し、見本を起動し直す

```bash
sh .agents/skills/dev-webapp-verify/scripts/redeploy.sh <ことり書店の分析リポジトリ> <umami の分析リポジトリ>
```

変えたものによって、付ける指定が違う。

| 変えたもの | 指定 | 行うこと |
|---|---|---|
| 画面のファイルだけ | なし | イメージの作り直し、起動し直し |
| 形式、ETL、集計表、宣言、meta | `--build` | 上に加えて、集計のやり直し |
| このリポジトリの `profiles/`、配布用の skill、`compose.yaml`、参照物 | `--upgrade` | 上に加えて、集計の前に、分析リポジトリの中の配布物のコピーを置き換える |

```bash
sh .agents/skills/dev-webapp-verify/scripts/redeploy.sh --upgrade <ことり書店の分析リポジトリ> <umami の分析リポジトリ>
```

- **プロファイルを変えたのに `--build` だけにすると、古いプロファイルで集計される。** 集計は、分析リポジトリの中のプロファイルのコピー (作業定義の `profile.dir`) を読む。コピーを置き換えるのは `upgrade` だけ。
- 集計か更新が失敗したら、スクリプトは起動し直さずに止まる。失敗を直してから、やり直す。
- **プロファイルの、入口の拾い方・包む関係・版を変えたときは、`--upgrade` だけでは足りない。** 入口の一覧と分析結果が、古い決まりのまま残る。先に [references/sample-repos.md](references/sample-repos.md) の「プロファイルを変えたとき」の手順を行う。

### 2. 撮る

```bash
uv run --with playwright python -I .agents/skills/dev-webapp-verify/scripts/shoot.py <画面の URL> <出力先> <幅> <full|view> "<名前>=<ハッシュ>" …
```

- 幅は、広い幅 `1440` と、狭い幅 `390` の 2 つ。
- `full` はページ全体、`view` は見えている範囲だけ。
- 出力先は、リポジトリに入れない場所にする (作業用の一時の場所)。
- 例: `"arch=#/overview" "entries=#/entries" "data=#/data"`

出力の JSON を読む。

| 項目 | 見ること |
|---|---|
| `errors` | 空であること。`favicon.ico` の 404 は、画面の変更と関係ない |
| `scrollW` と `clientW` | 同じであること (違えば、横にはみ出している) |

### 3. 操作を確かめる

足した操作 (絞り込み、開閉、畳む、選ぶ) は、実際に動かして、動かした後の状態を数える。撮るだけでは、動くことは分からない。

- 操作ごとに、小さなスクリプトを書く。書き方の型は [references/interaction.md](references/interaction.md)。
- 確かめる状態を、先に決める (例: 絞り込み前・合う語・合わない語の 3 つ)。
- 読み直した後、幅を変えた後も、確かめる。

### 4. 目で見る

撮った画像を、開いて見る。見るのは、変えた所と、その周り。

- 変えた表示が出る見本で見る。片方の見本にしか出ない表示がある。
- 出る見本が無い表示は、確かめていないと報告する。

## 報告に書くこと

| 項目 | 例 |
|---|---|
| 目で見た画面 | ことり書店の構成のページ (広い幅) |
| 数値だけ確かめたもの | 狭い幅は、はみ出しが無いことだけ |
| 動かした操作と、結果 | 「rdb」で絞ると、線 2 / 13 |
| 見ていないもの | umami の同じページ、狭い幅の画像 |

## はまり所

[references/troubleshooting.md](references/troubleshooting.md)
