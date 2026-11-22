# `ui-sveltekit` の決まり

[← プロファイルの仕様へ](../profiles.md)

ファイルの置き場がルーティングになる型です。Next.js の型と違う所だけを書きます。

| 所 | 決まり | 理由 |
|---|---|---|
| どの要求でも動くフック | `hooks.server` を 1 件の入口 (`shell`) にする。包む関係は `layout` と `shell` の 2 つの層で `source_dir`。`src/` に置くので、すべての入口を包む | ログインの確認やセッションの読み書きを、画面と API の受け口の数だけ繰り返さない |
| load と actions | `+page.ts` / `+layout.ts` の load は component。`+page.server.ts` / `+layout.server.ts` の load と actions、remote functions は api_route。どれも画面か枠の入口の段の子にする | ブラウザでも動く load は API を呼ぶだけ。サーバーの load と actions は、ブラウザから HTTP 越しに入る口 |
| `_` で始まるフォルダ | route になる (除外しない)。routes 直下だけは id の置換を足す | SvelteKit に、route にならないフォルダの書き方は無い |
| 値の形の検査付きの段 `[id=integer]` | id から検査の名前を外す (`id_d`)。階層パスには残す | 同居して同じ id になれば、列挙が止まって知らせる |
| 段の一部に値が入る段 (`photos-[id]`) | 値の部分に印を付ける (`photos-id_d`) | `ui-nuxt` と同じ |
| 枠を抜ける page (`+page@.svelte`) | `within` は置き場の祖先の枠をすべて持つ (余分)。抜けていることは入口の要約に書く | 包む関係の決め方 (`source_dir`) が、`@` を知らない |
| MongoDB | `rdb` (`dbms: mongodb`、`table` = コレクション)。GridFS は `object_storage` | データの種類に、文書の DB が無い |
| `+server.ts` | 入口にしない (`ui-nextjs` と同じ) | 画面を通らない受け口は、`api` のプロファイルで、分析リポジトリを分けて見る |
| 起動のときに始めて、動き続ける処理 | 始める段で止め、`not_analyzed` にする | 入口にする層が無い |

## ファイルの置き場がルーティングになる 3 つで、そろえた所と、そろえていない所

| 所 | `ui-nextjs` | `ui-sveltekit` | `ui-nuxt` | そろえたか |
|---|---|---|---|---|
| id の印 | `[id]` → `id_d`、`[[x]]` → `x_o`、`[...x]` → `x_c`。名前の中の `_` は重ねる。枠は `layout_l` | 同じ | 同じ | そろえた |
| サーバー側の受け口 | 入口にしない (`api_route` の段) | 同じ | 同じ | そろえた |
| どの要求・画面でも動く処理の層 | (layout が受け持つ) | `shell` | `shell` | そろえた (`ui-vue-router` と同じ名前) |
| 画面を包む入口 (`within`) | 置き場のフォルダで決まる | 同じ | 持たない | そろえていない。Nuxt は、画面が枠を宣言で選び、入れ子の親が隣のファイルなので、フォルダの上下では決まらない |
| 階層 | URL | URL | 置き場 (`index` も段に残す) | そろえていない。Nuxt は、入れ子の親と子が同じ URL になる |
| 状態の置き場と、API を呼ぶ関数の層 | 持たない | 持たない | 持つ (`store`、`api_client`) | そろえていない。Nuxt は、サーバー側を持たず、別のバックエンドを呼ぶ作りにも使う (`ui-vue-router` と同じ層) |
