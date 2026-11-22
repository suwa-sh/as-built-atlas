# `ui-nuxt` の決まり

[← プロファイルの仕様へ](../profiles.md)

ファイルの置き場がルーティングになる点は `ui-nextjs` と同じです。自動で読み込まれる component / composable / store と、バックエンドを `external_api` で閉じる点は `ui-vue-router` と同じです。違う所だけを書きます。

| 所 | 決まり | 理由 |
|---|---|---|
| 階層 | URL ではなく、置き場。拡張子を除いたファイル名を最後の段にし、`index` も残す | 入れ子の親 (`a.vue`) と子 (`a/index.vue`、`a/index/index.vue`) は、URL が同じ。`index` を落とすと、id がぶつかる |
| 入れ子の page | 親も子も入口。親は `<NuxtPage>` の中身を辿らず、子は親を辿らない。`within` は付かない (どの親の中で動くかは、階層パスと summary で見る) | 包む側の `a.vue` と、包まれる側のフォルダ `a/` が隣り合う形を、いまの包む関係の決め方 (`source_dir`) では表せない |
| layout | ファイル 1 つ = 入口。`within` は付かない | どの page がどの layout を使うかは、`definePageMeta` で決まり、置き場からは決まらない |
| アプリ全体の枠 (`shell`) | app.vue、error.vue、global の route middleware、server middleware は、ファイル 1 つ = 入口 (glob)。起動のときにデータを読む・外へ送るプラグインは、エージェントが足す (listed) | どの画面・要求でも動く処理を、入口の数だけ繰り返さない。置き場から決定論で取れるものは、抽出器で取る |
| 名前付きの route middleware | 入口にしない。`definePageMeta` で指す page の経路に書く | その page のときだけ動く |
| サーバー側 | `server/api`、`server/routes` は入口にしない (画面から URL で辿る途中の段 `api_route`)。`server/` が無いシステムは、`external_api` で閉じる | 1 つのプロファイルで、両方の作りを扱う |
| 自動で読み込まれるもの | 名前から定義を探す場所 (`components.dirs`、`imports.dirs`、生成された型の定義) を、先に確かめる。定義が 1 つに決まれば `fact`。`extends` の layer での上書きは、notes に書くだけ | import を辿るだけでは、呼び先に着かない |
