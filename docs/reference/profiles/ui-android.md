# `ui-android` の決まり

[← プロファイルの仕様へ](../profiles.md)

| 決まり | 内容 | 理由 |
|---|---|---|
| 入口は、画面の行き先と、OS から起動される class | Navigation の destination のほかに、manifest の activity / application / service / receiver / provider と、WorkManager の Worker を入口にする | 画面を通らない同期や受信が、端末の中の保存を書く。書く側を入口にしないと、保存を介したつながりが消える |
| XML は `ast` の `html` で読む | manifest と navigation graph の XML 用の抽出器は足さない | `ast` の `html` で要素と属性が読める (先頭の `<?xml ?>` だけ読めない) |
| 型の route は 1 段、文字の route は区切りが段 | `ForYouNavKey` → `/ForYou` (末尾の NavKey / Route / Destination を落とす)、`"topic/{topicId}"` → `/topic/{topicId}` (`topic.topicId_d`) | 型の route には URL が無い |
| アプリ全体の枠 | Navigation の host を置く Activity は枠。枠が描く、保存先を読み書きする composable は、別の入口 (`/(shell)/<名前>`)。画面は枠を辿らない | `ui-vue-router` の `shell` と同じ。同じ通り道を、画面の数だけ繰り返さない |
| 端末の中の保存は、読み書きに書く | Room → rdb (`host: (device)`、`dbms: sqlite`)、DataStore / SharedPreferences → kvs、ファイル → filesystem。メモリだけの状態と、ライブラリ任せのキャッシュは書かない | 先に端末に貯める作りでは、端末の中のデータベースが本物の保存先。Web のプロファイルの「ブラウザの中の保存は書かない」とは逆 |
| interface の実装は、DI の宣言で決める。build variant は 1 つ | Hilt の `@Binds` / `@Provides` の行を根拠にする。分析する variant は、分析リポジトリの決まりに書く | 層の間を interface と DI でつなぐのがふつう。flavor で実装が変わる |
| ディープリンクと通知は、入口にしない | 受ける Activity と、通知を出す側のフレームの `links` (`navigate`) に書く | 起動の経路で、処理は Activity の中にある |
