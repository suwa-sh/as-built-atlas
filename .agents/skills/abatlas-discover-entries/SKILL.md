---
name: abatlas-discover-entries
description: 分析対象リポジトリの「入口」(ジョブ・エンドポイント・画面) を見つけて、入口の一覧を作る。抽出器とパラメータを決めて entry-list.yaml の extractors に書き、抽出器で取れない入口は、コードを読んで根拠付きで足す。入口一覧を作りたい・抽出器の設定を決めたい・列挙結果を見直したい・入口の漏れを確かめたいときに使う。
---

# 入口を見つける

入口を列挙する主体は、このスキルを実行するエージェントである。抽出器 (決定的な道具) は、その土台として使う。

- 抽出器で取れる入口は、**どの抽出器を、どのパラメータで使うか**を `entry-list.yaml` に書いて、列挙ツールに出させる
- 抽出器で取れない入口 (別のファイルから来る定義、関数が作る定義、道具が読めない言語) は、**コードを読んで、根拠と理由を付けて足す**
- 抽出器が失敗しても、止まらない。その抽出器を外し、読んで足す
- 承認は人が行う

## 入力

- 分析リポジトリのルート (カレントディレクトリ)。`analysis/work-definition.yaml` が必須
- 分析の資産は `analysis/` の下: `analysis/work-definition.yaml`、`analysis/entry-list.yaml`、`analysis/results/`、`analysis/reviews/`
- OSS の参照物 `<oss>`: カレントディレクトリに `.abatlas/` があればそれ (分析リポジトリ)。無ければこの SKILL.md の実体の 3 つ上 (OSS の checkout)
- ツールの呼び方 `<abatlas>`: 分析リポジトリでは `docker compose run --rm abatlas` (コンテナの中で動く。パスはリポジトリのルートからの相対で書く)。OSS の checkout では `uv run abatlas`
- プロファイル: `analysis/work-definition.yaml` の `profile.dir`。無ければ `<oss>/profiles/<profile.id>/`

## 前提

- 分析リポジトリでは Docker が動き、`.env` の `ABATLAS_TARGET` が対象の clone を指している (`<abatlas>` はそれを `/ws/target` として読む)。OSS の checkout では `uv sync` 済み
- 対象は `analysis/work-definition.yaml` の `target.clone_path` に clone 済みで、`target.commit` が checkout されている (`git -C <clone_path> rev-parse HEAD` で確かめる。違えば止めて人に伝える。対象に git のコマンドを実行しないよう指示されているときは、確かめずに、作業定義の値を信じる)

## 手順

1. プロファイルを読む: `profile.yaml` (層、`extractors[]` の候補と `hint`、`hierarchy.derivation`) と `context.md` (入口の判別の節)
2. 対象を調べる: `target.clone_path/target.scope` の中で、プロファイルの `extractors[].hint` に従って、入口を定義している場所・形式・必須項目を確かめる。`rg` / `find` / 実ファイルの先頭を読む程度にとどめ、全ファイルを読まない
   - コードの構文で探すときは、`<abatlas> code-search analysis/work-definition.yaml --language <言語> --files <glob> --pattern '<コードの形>'` を使う (一致した場所を出すだけで、一覧は変えない)
3. `analysis/entry-list.yaml` を作る (無ければ)。既にあるときは、作り直さずに見直す: `profile.version` を、いまの `profile.yaml` の版に合わせる。版が上がっていたら、プロファイルの決まりを読み直し、抽出器の設定と、読んで足した入口 (`listed`) を、いまの決まりで見直す。`format_version: 1`、`target` は `analysis/work-definition.yaml` と同じ、`profile.id` と `profile.version` は `profile.yaml` から、`entries: []`
4. `extractors[]` を書く。プロファイルの既定パラメータを出発点に、このリポジトリに合わせて埋める。各抽出器に `rationale` (なぜこの設定か) を 1〜2 文で書く
   - 構文を読む抽出器 (`abatlas-extract ast`) を使うときは、取れない定義に一致する規則を `params.unresolved` にも書く (例: 定義の配列の中の、名前だけの要素・展開・関数の呼び出し)
5. 試す: `<abatlas> enumerate analysis/entry-list.yaml --dry-run` (プロファイルは、作業定義の `profile.dir` から自動で読まれる。読んだ場所が出力の最初に出る。「自動で読めない」と出たら、`profile.dir` を直す)
   - 失敗したら標準エラーの指摘 (契約違反・schema 違反・規則の誤り・読めない言語) に従って設定を直す。抽出器のコードは直さない
   - 直しても通らない抽出器は、`extractors[]` から外す。その抽出器で取るはずだった入口は、手順 6 で読んで足す。外した理由は、報告に書く
   - `--dry-run` は、一覧を書かずに、候補を 1 行 1 件 (id、階層パス、層、抽出器、状態) で出す。件数と階層パスの分布を見て、明らかな漏れ (定義ファイルがあるのに出ない) や重複 (同じ入口が別 id) があれば設定を見直す
6. 抽出器で取れない入口を足す。次の 3 つを調べ、見つけた入口を `abatlas-extract listed` の `params.entries` に書く
   - 列挙の出力の「読めなかった参照」(ファイルと行)。その名前の定義を辿って読む
   - プロファイルの `context.md` に書いてある、取れない入口の探し方
   - 手順 5 で外した抽出器が取るはずだった入口
   - 入口ごとに、`id`、`path` (階層パス。プロファイルの `hierarchy.derivation` と、抽出器が出した入口の付け方に合わせる)、`source` (入口を定義しているファイルと行。定義が複数行なら、始まりの行)、`reason` (なぜ入口と判断したか、なぜ抽出器で取れないか) を書く。人が読む名前があれば `name`、抽出器が出す入口と同じ付随の情報があれば `attributes` も書く (どちらも任意)
   - ファイルのパス (`source.file`、抽出器の `files`、`code-search` の `--files`) は、すべて、作業定義の `target.scope` からの相対で書く (`clone_path` からではない。例: scope が `ui` なら、`ui/src/a.ts` ではなく `src/a.ts`)
   - 入口にするか迷うもの (データの読み書きに至るかを、数段先まで読まないと決められないもの) は、足す。承認のときに、人が外せる。迷ったことを `reason` に書く
   - 読んでも入口の数や名前が決まらないもの (実行時の値で決まる定義など) は、足さない。報告に、場所と理由を書く
   - 既にある `listed` の入口を直すとき: `reason`、`name`、`attributes`、`source` の行だけを変えても、人の承認は引き継がれる。`path`、層、`source.file` を変えると、列挙が `candidate` に戻す (人が承認し直す)。承認済みの入口は、誤りを直すとき以外は、指す先を変えない
   - `listed` は、`extractors[]` の最後に書く。抽出器が出した入口を、`listed` に重ねて書かない (同じ id で、指す先か行が違うと、列挙が止まる)
   - `listed` が出す入口の層は、抽出器の `layer` で決まる (入口ごとには書けない)。入口の層が 2 つ以上あるプロファイルでは、層ごとに別の名前の `listed` を作り (例: `agent-listed-page`、`agent-listed-layout`)、その層の入口だけを書く
7. 本番の列挙: `--dry-run` を外して実行する。`entries[]` に `status: candidate` で候補が書かれる
8. 人に渡す報告を書く (標準出力でよい)
   - 件数と、階層の第 1 段ごとの内訳
   - 抽出器が出した件数と、読んで足した件数 (足した入口は、1 件ずつ id と理由)
   - 既定パラメータから変えた点と、その理由。外した抽出器と、その理由
   - 入口かもしれないが、足さなかったもの (場所と理由)
   - 既に分析結果があるリポジトリで、ほかの入口の中で描かれる・呼ばれる入口 (プロファイルが、別の入口に分けると決めている部品など) を足した・外したとき: 分析し直す入口 (それを描く・呼ぶ側の入口)。この古さは、プロファイルの版の比較では見つからない

`listed` の書き方:

```yaml
extractors:
  - name: agent-listed
    run: abatlas-extract listed
    layer: <入口の層の id>
    rationale: <なぜ抽出器で取れないか>
    params:
      entries:
        - id: orders
          path: /orders
          name: orders/list
          source: { file: src/orders/orderTabs.ts, line: 1 }   # scope からの相対
          reason: 画面の定義の配列に ORDER_ROUTE として入っている。定義は、このファイルにある
```

## 完了条件

- `<abatlas> validate entries analysis/entry-list.yaml` が OK。出力に「プロファイルを自動で読めない」と出たら、OK でも完了にしない (プロファイルとの突き合わせが省かれている)。`analysis/work-definition.yaml` の `profile.dir` と、その場所の `profile.yaml` を確かめて直す
- `entries[]` が 1 件以上ある。今回の列挙で新しく出た入口は、`status: candidate` のまま (承認は人の作業。このスキルでは `approved` にしない)。前に人が付けた `approved` / `rejected` は、列挙が引き継ぐので、そのままにする
- 列挙の出力に「candidate に戻す」と出た入口 (人が判断した後に、指す先が変わった入口) を、報告に書いてある
- 各抽出器に `rationale` がある
- 列挙の出力の「読めなかった参照」を、1 件ずつ調べてある (入口を足したか、足さない理由を報告に書いたか)
- 読んで足した入口のすべてに、`source` と `reason` がある

## 禁止

- `entries[]` を手で書く・直す。読んで見つけた入口は、`listed` 抽出器の `params.entries` に書く (`entries[]` に直接書くと、列挙のやり直しで消える)
- 根拠の無い入口を足す (名前から推測した入口、定義を読んでいない入口)
- `status` を `approved` / `rejected` に変える
- 抽出器 (配布物の `abatlas/extractors/` やプロファイルの `extractors/`) のコードを変える

## 参照

- 抽出器の契約と `params` の書き方: `<oss>/docs/architecture/profiles.md` の「抽出器の契約」、`<oss>/schema/entry-candidate.schema.json`、プロファイルの `profile.yaml` の `extractors[]` (既定の params と hint)。コア同梱の抽出器の `params` の全項目は、`<abatlas> extractors <名前>` で出す (名前は `structured-query` / `nested-keys` / `glob` / `ast` / `listed`)
- 入口一覧の形式: `<oss>/schema/entry-list.schema.json`
