# `ui-ios` の決まり

[← プロファイルの仕様へ](../profiles.md)

| 決まり | 内容 | 理由 |
|---|---|---|
| 入口は、行き先の enum の case 1 つ | 階層は `/<enum の名前>/<case の名前>`。同じ View を描く case も、case ごとに入口 | URL が無い。case が、渡る値と読む API を決める |
| push で開く View は、別の入口 | enum を通らずに push で開く View と、2 つ以上の画面から重ねて開く View は `/(view)/<View の名前>`。1 つの画面からだけ重ねて開くものは、開く側に含める | 開く側に含めると、設定の画面 1 件が十数画面ぶんになった |
| アプリ全体の枠 (`shell`) | @main の App、AppDelegate、タブを持つルートの View、枠が描く共通の view。`within` は持たない | どの画面でも動く処理を、画面の数だけ繰り返さない |
| OS から起動される入口 (`system`) | `/(system)/<widget\|intent\|notification\|extension\|link\|background>/<名前>` | アプリの画面を通らずに、同じ保存の場所と API を使う |
| 端末の中の保存は、読み書きに書く | SwiftData / Core Data → rdb、UserDefaults と Keychain → kvs、ファイル → filesystem。host は `(device)`。App Group の名前を段にそろえる | 端末の DB や設定は本物のデータで、アプリと拡張が受け渡す |
| OS が呼ぶ関数が 2 つ以上ある入口 | どれも入口のフレームの直下に置き、主の関数 (`timeline`、`perform`、`didFinishLaunching`) の下に、共通の経路を 1 回だけ書く | OS が呼ぶ関数には、コードの順が無い |
| ほかの端末だけのコードは辿らない | `#if os(macOS)`、`#if os(visionOS)`、`#if targetEnvironment(macCatalyst)` | 対象は iPhone と iPad |

## モバイルの 2 つで、そろえた所と、そろえていない所

| 所 | `ui-android` | `ui-ios` | そろえたか |
|---|---|---|---|
| 端末の中の保存 | 読み書きに書く | 同じ | そろえた。host は `(device)`、SDK の host は `(<SDK の名前>)` |
| 読み書きを書くフレーム | `external` のフレーム (Room の DAO は、注釈の行を `source` にした `external` のフレーム) | `external` のフレーム (ライブラリの関数を呼ぶ行) | そろえた。サーバーの API を `external` のフレームに書く決まりと同じ向き |
| `dbms` | 中で動くエンジンを小文字で (`sqlite`) | 同じ (SwiftData、Core Data、GRDB は `sqlite`、Realm は `realm`)。ライブラリの名前は `note` | そろえた |
| 保存の形の移し替え (migration) | 入口の読み書きに書かない | 同じ | そろえた |
| OS から起動される入口の層 | `background` | `system` | そろえていない。iOS は、ウィジェットや共有の拡張のように、画面を持つものを含む |
| アプリ全体の枠の範囲 | Application は `background`、Activity は専用の層 `activity`、共通の composable が `shell` | App、AppDelegate、ルートの View が `shell` | そろえていない。OS の作りが違う |
| 外から URL で開かれたときの受け口 | 入口にせず、受ける Activity の `links` に書く | 入口にする (`/(system)/link/<スキーム>`) | そろえていない。Android は、受ける Activity そのものが入口なので、受け口の処理は、その入口の結果に入る |
