# batch-github-actions プロファイル: エージェント向けの説明

対象は「GitHub Actions で組んだ自動処理」(テスト、ビルド、公開、定期の処理)。入口の発見と、入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

Kestra のフローから起動されるバッチは `batch-kestra`、スケジューラの定義がリポジトリに無いコマンドは `cli` を使う。

## アーキテクチャと層の連鎖

```text
workflow (.github/workflows の workflow ファイル。入口)
  → job      (jobs の下の job)
    → step     (run のスクリプト、リポジトリの中の action)
      → program  (リポジトリのスクリプト、Makefile のターゲット、パッケージのスクリプト)
        → external (外部の action、外部のコマンド。ここで終端)
```

- `workflow` が `role: entry`。workflow ファイル 1 つ = 入口 1 件
- `external` が `role: boundary`。外部の action (`uses: owner/name@版`) と、外部のコマンド (`docker`、`gh`、`npm publish`、クラウドの CLI) に達したら閉じる
- step が、リポジトリのスクリプトを起動せず、直接、外部のコマンドを呼ぶときは、`step` から `external` へつなぐ (`program` を作らない)

## 入口の判別

- workflow ファイルは、`.github/workflows` の直下の YAML。抽出器 `workflows` が、ファイル 1 つを入口 1 件にする
- 別の workflow から呼ばれるだけの workflow (`on: workflow_call`) も、入口として列挙する。呼び出しの関係は、呼ぶ側の結果の `links` に書く
- リポジトリの中の action (`.github/actions/<名前>/action.yml`、根の `action.yml`) は、入口にしない。呼ぶ workflow の中のフレームとして現れる
- どの workflow からも呼ばれないリポジトリの中の action と、外部に配る action (根の `action.yml`) があれば、報告に書く (入口にするかは、人が決める。するなら `listed` で足し、層は `workflow`、階層は `/(action)/<名前>`)

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| workflow | workflow ファイル | 起動のきっかけ (`on`)、入力 (`workflow_dispatch` / `workflow_call` の `inputs`)、権限 (`permissions`)、同時実行の決まり (`concurrency`)、job の並びと依存 (`needs`) |
| job | `jobs.<id>` | 動く条件 (`if`)、環境 (`environment`)、行列 (`strategy.matrix`)、job の `permissions`、step の並び |
| step | `steps[]` の `run`、リポジトリの中の action の定義 | 起動するスクリプトとコマンド、読み書き、外への送信 |
| program | スクリプト本体、Makefile、`package.json` の scripts | 接続先、操作、読み書きするファイル |
| external | 外部の action を使う行 (`uses`)、外部のコマンドを呼ぶ行 | `source` は、その行 |

### フレームにするもの・しないもの

- **job は、すべてフレームにする** (`kind: job`、`name` は job の id)。`caller` は、入口のフレーム。`needs` で順が決まるので、`needs` の先を、`call` の `note` に書く
- **step は、次のどれかに当たるものだけをフレームにする**: 読み書きをする、外へ送る (公開、デプロイ、通知、API の呼び出し)、リポジトリのスクリプトを起動する、業務のルール (判定) を持つ。`name` は、step の `name` (無ければ、`run` の最初のコマンドか、action の名前)
- **フレームにしない step**: 環境を用意するだけのもの (`actions/checkout`、`actions/setup-*`、依存の取得、キャッシュ)、ログインするだけのもの (`docker/login-action`、クラウドの認証の action。使う秘密の名前は、job のフレームの `parameters` に書く)、表示するだけのもの (`echo`)。job のフレームの `summary` に、まとめて書く
- この基準は、`program` の層の中でも同じ。スクリプトや Makefile の中の、依存の取得 (`go install`、`npm ci`、道具のダウンロード) と表示は、フレームにも読み書きにも書かない
- **外部を読んで確かめるだけのコマンド** (公開されたイメージがあるかを見る、など。無ければ失敗させる): `external` のフレームにし、呼び出し元に `external_api` の読み書きを書く。確かめる内容は、呼び出し元の `rules` (`validation`) に書く
- **フレームの `kind`**: `job`、`script` (`run` のスクリプト、リポジトリのスクリプト)、`action` (action)、`make_target` (Makefile のターゲット)、`package_script` (パッケージのスクリプト)、`cli` (外部のコマンド。`cli`、`api`、`batch-kestra` と同じ語)、`library` (ライブラリ)。外部のコマンドを `command` と書いた前の結果は、誤りではない (レビューは、指摘しない)
- **外部の action** (`uses: owner/name@版`): 外へ送る・成果物を出し入れする・デプロイするものを、`external` のフレームにする (`kind: action`、`name` は `owner/name`、`source` は `uses` の行)。`caller` は job のフレーム (step の層を挟まない)。読み書きは、その `external` のフレームに書く (action の中は読めないので、`with` に渡している値と、action の公開された役割から書き、`interpretation` にする)
- **リポジトリの中の action** (`uses: ./.github/actions/<名前>`): `step` の層のフレームにし (`kind: action`、`source` は action の定義ファイル)、その中の step を、上と同じ基準で辿る
- **別の workflow を呼ぶ job** (`uses: ./.github/workflows/<名前>.yml`、または別のリポジトリの workflow): job のフレームを書き、行き先を `links` (`kind: trigger`) に書く。同じリポジトリの workflow なら `entry_id` も書く (`entry_id` のある `trigger` を持つ job は、終端にできる)。別のリポジトリの workflow は、`entry_id` が書けないので、呼び出しを `external` のフレームにして閉じ (`source` は `uses` の行)、`links` は job のフレームに書く。呼んだ先は辿らない (別の入口)
- **`run` のスクリプト**: step のフレーム (`kind: script`)。その中で起動するリポジトリのスクリプト (`./scripts/build.sh`、`make dist`、`npm run build`) は、`program` のフレームにして辿る。Makefile のターゲットと、パッケージのスクリプトは、定義の行を `source` にし、そこから起動するものを、さらに辿る
- **行列 (`matrix`)** で同じ job が何度も動くときも、フレームは 1 回だけ書く。行列の軸と値は、job の `parameters` に書く
- 終端の決まり (機械チェック): 誰も呼ばないフレームは、`external` の層である、読み書きを持つ、業務のルールを持つ、行き先の入口が分かっているつながり (`trigger` と `entry_id`) を持つ、不明の主張を持つ、のどれか。読み書きも外への送信もしない job や `program` (テストを動かすだけ、ビルドするだけ、など) は、最後に頼るコマンド (テストやビルドを起動するコマンド) を `external` のフレームとして 1 つ書いて閉じる
- **外部の道具が、設定ファイルから、リポジトリの処理を呼び返すとき** (公開の道具が、設定の `hooks` で、リポジトリのスクリプトや Makefile のターゲットを起動する): 設定ファイルに書いてある呼び出しは、読めば決まるので辿る。`caller` は、その道具の `external` のフレームではなく、道具を起動するフレーム。`call` の根拠は、設定ファイルの行。`interpretation` にする

### 呼び出しの条件 (`call.when`)

| 書き方 | `when` |
|---|---|
| `if` が無い job、step | `always` |
| `if: <条件>` (ブランチ、イベント、入力、前の step の出力) | `conditional`。`condition` には、条件を 1 文で書く (式は、根拠の行にある。式をそのまま写さない) |
| `if: failure()`、`if: cancelled()` | `on_failure` |
| `if: always()` | `always` (成功しても失敗しても動く後片付け) |
| `continue-on-error: true`、`run` の中で失敗を飲み込む書き方 (`\|\| true`) | `always` のまま。`note` に、失敗しても先へ進むことを書く |
| Makefile で、成果物の新しさを比べて動くかが決まるターゲット | 成果物がリポジトリに無い (毎回、取得した直後の状態から動く) なら `always`。リポジトリにあるなら `conditional` |
| 起動のきっかけ (`on`) で、ある job だけが動く (job の `if: github.event_name == ...`) | `conditional` |

### ほかの入口へのつながり (`links`)

| 書き方 | 書く場所 |
|---|---|
| 別の workflow を呼ぶ (`uses: ./.github/workflows/x.yml`) | その job のフレームに `trigger` |
| 別の workflow を起動する (`gh workflow run`、`repository_dispatch`、`workflow_dispatch` の API) | 起動する step のフレームに `trigger` |
| 別の workflow が終わった後に動く (`on: workflow_run`) | つながりは、先に動く側の結果には現れない。**後に動く側の入口のフレームの `summary` に書く** (`links` は、この入口から出るつながりだけを持つ) |

### 権限の確認・設定・ルール

- **`guards`**: 人の承認や、保護された環境を通る所 (`environment: production` で、承認が要る設定) を、その job のフレームに `kind: other` で書く (`value` は、環境の名前)。承認が要るかは、リポジトリの設定で決まり、コードからは読めないので、`interpretation` にして `note` に書く。フォークからの実行を止める条件 (`if: github.repository == ...`) は、`rules` (`decision`) に書く
- **`settings`**: リポジトリや組織の設定で、動きを変える変数 (`vars.X`)。値を与えるだけの秘密 (`secrets.X`) は、`settings` に書かず、使う step のフレームの `parameters` に、名前だけを書く (どの外部とやり取りするかの手掛かりになる)。action が、既定のトークンを使う (秘密を渡していない) ときは、読み書きの `note` に書く
  - リポジトリの中のファイルに固定された値 (道具の設定ファイルの値) は、`settings` ではなく、読み書きやルールの根拠に使う。workflow が式で作って渡す値 (`env` に入れた版の文字など) は、`parameters` と、作り方の `rules` (`calculation`) に書く
- **`rules`**: 版の決め方 (タグから版を作る)、公開するかの判定、対象を絞る条件など、業務の意味を持つ判定
  - 起動のきっかけ (`on`) は、入口のフレームの `parameters` に書く (`name: on`。きっかけが複数あれば、きっかけごとに 1 件)。`rules` にも書くのは、きっかけが業務の判定を兼ねるとき (タグの形で、公開するかが決まる、など) だけ
  - 外部の action に渡す値 (`with`) は、`parameters` に `fact` で書く。その値から読み取った動き (`rules`) は、action の中を読めないので `interpretation`
- workflow と job の `permissions` は、入口や job のフレームの `parameters` に書く (`name: permissions`、値は、書いてあるとおり)。書いていないとき (リポジトリの既定に任せている) は、何も書かない

## 事実・解釈・不明の付け方

- **fact**: 定義にそのまま書いてある (`run` の文字列、`uses` の値、`if` の式)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの `summary`)。外部の action が行う読み書き (中は読めない)
- **unknown**: 次の典型例では、この理由を使う
  - 行き先や対象が、式 (`${{ inputs.x }}`、`${{ matrix.x }}`、前の step の出力) で決まり、値が読めない → `dynamic_dispatch` (読める値は、1 件ずつ書く)
  - 接続先が、秘密や変数で決まり、値がリポジトリに無い → `not_traceable_in_repo` (分かる段だけ書く)
  - 呼ぶ workflow や action が、別のリポジトリにある → フレームは `external` で閉じる (不明にしない)。別のリポジトリの workflow は、`links` に書く
  - 実行時に組み立てたスクリプトを実行する → `generated_at_runtime`

## データの当てはめ

- **実行の間だけある作業用のファイル** (取得したソース、ビルドの出力、一時ファイル) は、読み書きに書かない。job が終わると消えるため
- **リポジトリに書き戻すファイル** (生成したファイルを commit して push する) → `filesystem` の `write` (パスは、リポジトリの根から) と、`git push` の `external_api`
- **成果物の出し入れ** (`actions/upload-artifact`、`actions/download-artifact`) → `object_storage` (`account: github-actions`、`bucket: artifacts`、`object` は成果物の名前)。操作は `put` / `get`
- **キャッシュ** (`actions/cache`) は、読み書きに書かない (速くするためだけのもの)
- **コンテナイメージの公開** (`docker push`、`docker/build-push-action`) → `external_api` (`host` はレジストリ、`path` はイメージの名前。タグは書かない。レジストリが書かれていないイメージは `docker.io`)
- **パッケージの公開** (`npm publish`、`twine upload`、`goreleaser`) → `external_api` (`host` は公開先、`path` はパッケージの名前)
- **GitHub の API** (`gh`、`actions/github-script`、リリースの作成、issue や PR への書き込み) → `external_api` (`host: api.github.com`、`path` は、資源の形。例: `/repos/{owner}/{repo}/releases`。タグの作成・削除は `/repos/{owner}/{repo}/git/refs`、issue と PR へのラベル・コメントは `/repos/{owner}/{repo}/issues`、PR を閉じる・マージするのは `/repos/{owner}/{repo}/pulls`)
- **ページの公開** (`actions/deploy-pages`、`gh-pages` への push) → `external_api` (`host` は公開先)
- **クラウドへのデプロイ、通知** (Slack、メール) → `external_api`
- **テストのためだけに job の中で起動するデータベース** (`services`) は、読み書きに書かない
