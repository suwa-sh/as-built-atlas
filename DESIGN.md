---
name: as-built-atlas webapp
description: 分析結果の画面。入口からデータまでの経路を、細い線の路線図として描く
colors:
  bg: "#FFFFFF"
  ink: "#0A0A0A"
  mute: "#6B6B6B"
  faint: "#A3A3A3"
  edge: "#858585"
  hair: "#E2E2E2"
  tint: "#F6F6F6"
  sel: "#EDEDED"
  write: "#C7381C"
  err: "#B00020"
  ink-hover: "#333333"
  line-1: "#0B8A5A"
  line-2: "#2C6FD1"
  line-3: "#8A4FBF"
  line-4: "#B26A00"
  line-5: "#0E8C9A"
  line-6: "#C2378A"
typography:
  title:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "32px"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  kpi:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "24px"
    fontWeight: 400
    lineHeight: 1.15
  stat:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "22px"
    fontWeight: 400
  heading:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.3
  brand:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 600
  body:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  note:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  small:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 400
  label:
    fontFamily: "Hiragino Sans, Noto Sans JP, Yu Gothic UI, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 400
  code:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
rounded:
  none: "0"
  tag: "3px"
  control: "6px"
  op: "10px"
  badge: "12px"
  pill: "16px"
  station: "50%"
  transfer: "3px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "40px"
components:
  button:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "3px 14px"
    height: "30px"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.bg}"
    rounded: "{rounded.pill}"
    padding: "3px 14px"
  op-read:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.op}"
    padding: "0 8px"
  op-write:
    backgroundColor: "{colors.write}"
    textColor: "{colors.bg}"
    rounded: "{rounded.op}"
    padding: "0 8px"
  badge:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.badge}"
    padding: "0 11px 0 9px"
    height: "24px"
  row-selected:
    backgroundColor: "{colors.sel}"
    textColor: "{colors.ink}"
---

# Design System: as-built-atlas webapp

正本は `abatlas/webapp/css/` の 5 ファイル (変数は `base.css` の `:root`)。この文書は、そこに実装されている決まりの説明。値を変えるときは CSS とこの文書を一緒に直す。

## 言葉

画面の呼び名は、用語集 `schema/vocab/terms.yaml` で決まる。概念 1 つに呼び名 1 つで、技術用語は英語のまま (分析結果や API の値と同じ綴り)。

| 書く場所 | 書き方 |
|---|---|
| 画面のコード (`abatlas/webapp`) | 呼び名を直接書かず、`term("<id>")` で引く。文の中では `` `この ${term("entry")} を開く` `` のように差し込む |
| mart の宣言 (`meta.abatlas` の title / hint / labels / filters の label、model の description) | `"{<id>}"` と書く。build が呼び名に置き換えて配る。core の title と labels は `"{<id>}"` と記号・単位だけで組む |
| プロファイルの表示項目 (label、layers の label / tier、hierarchy.notes の text) | 対象ごとの名前 (page、frontend など) はそのまま書く。概念は `"{<id>}"` |
| データの種類の語彙 (`schema/vocab/resource-kinds.yaml` の label) | 用語集にある呼び名は `"{<id>}"` で引く (例: external API、read、write) |
| 説明の文、操作の言葉 (開く、畳む、コピー) | 日本語のまま |

使わなくなった呼び名 (用語集の `retired`) が画面に出る文字に残ると、`tests/test_terms.py` が落とす。この文書の下の節では、見た目の説明のために日本語の呼び名 (入口、層、データ など) も使う。画面に出る語との対応は用語集の注記にある。

## Overview

路線図の言葉で、「入口 → 処理の段 → データ」を描く。見た目は、白と黒と細い線だけで組む。階層は文字の大きさと余白で作り、太さと塗りでは作らない。

| 路線図の言葉 | 画面での意味 | 形 |
|---|---|---|
| 路線 (線) | 1 つの入口からの経路 | 太さ 2px の線。色は入口の種類 |
| 駅 | 処理の段 | 細い縁の丸 |
| 乗換駅 | ほかの入口も通る部品 | 黒の縁の角丸の四角 |
| 終点 | 読み書きの相手、または探している部品 | 塗りつぶした駅 |
| まだ引かれていない線 | 未分析 | 破線の線と破線の駅 |

使う場面は、エディタの隣に置いて影響を調べること。昼の作業机を想定し、明るい地にする。

## Colors

地は白、文字は黒、脇の文字と罫は彩度のない灰。彩度のある色の役割は 2 つだけ。

| 役割 | 色 | 使う場所 |
|---|---|---|
| 路線の色 | `line-1`〜`line-6` | 入口の種類ごとに 1 色。行頭の帯 (3px)、駅の縁、経路の線 (2px)、種類の札の点 |
| 書く操作・注意 | `write` | 書く操作の札の塗り、注意書きの強調 |

- 入口の種類と色の対応は、プロファイルの呼び名 (`level_labels` の末尾 → `entry_labels` の順) に、出た順で割り当てる (`model/catalog.js` の `lineOf`)。凡例は、色の帯を使う表の下にだけ出す (ナビには置かない)
- リンクは黒の文字に細い下線。青をリンクに使わない (路線の色と取り違えるため)
- 選んだ行の地色は中立の `sel`。路線の色は行頭の帯が持つ
- 2 つ目の地色 `tint` は、行に触れたときと、開閉できる表の見出しだけ
- `faint` は飾りの線だけに使う (リンクの下線、小さな札の縁、スクロールバー)。文字、意味を持つ線、操作できる部品の縁には使わない (白地で 2.5:1)
- `edge` は、入力・絞り込みの札・コピーのボタンの縁と、不明を含む図の辺、ツリーの線 (白地で 3.7:1)
- 脇の文字は `mute` (白地で 5.3:1)。書く操作の札は白い文字で 4.9:1
- 文字を選んだときは白黒を反転する
- 状態を色だけで伝えない。読む / 書くは札の塗りの有無と文字、選択は `aria-selected` と帯の太さ、不明は破線の縁と「不明」の文字

## Typography

- 書体は 1 つ (システムのゴシック)
- 見出しは太さ 400 のまま、大きさで分ける: ページの名前 32px、数字 24px、節の見出し 18px、本文 14px
- 太さ 600 は、小さな文字で区別が要るところだけ: 現在地 (ナビ、包む入口の並び)、経路の駅の名前、種類の札。500 は一覧の名前と操作の札
- 小さい文字の段階は 13 / 12 / 11px (11px は表の見出しと小さな札)
- 数字は等幅数字 (`font-variant-numeric: tabular-nums`)
- 等幅の書体は、パス・ファイルの場所・集計表の物理名だけに使う
- 読む文章 (要約、注記) は 1 行 75 文字まで

## Layout

- 左に幅 240px の白いナビ (項目は 1 行に収め、改行させない)。見出しは分析対象の名前で、下に小さくコミットの先頭 7 桁 (どのページでも、どのシステムを見ているかが分かる。畳んだ帯には名前を縦書きで残し、タブの名前にも出す)。道具の名前は本文の下のフッターに小さく出す (「as-built-atlas で作成」と、対象のリポジトリ・コミット・profile)。見出しの右の「‹」で畳むと、開くボタンだけの幅 44px の帯になる (畳んだ状態はブラウザに覚える。狭い画面では、これまでどおり「メニュー」のボタンで開閉)。本文との境は 1px の薄い罫。項目は区分だけ (件数つき) で、先頭が「構成」(最初に開くページ)。現在地は塗った点と黒の文字、ほかは灰の文字
- 本文の見出しは「種類の札 + 名前 + 数字」を 1 行に置き、下に 1px の黒の罫 (ページで 1 本だけの強い罫)
- 逆引きの画面 (データ、入口の詳細、外部接続、共有処理) は 2 列: 左に選べる表、右 (360〜460px) に経路。右の欄は画面に留まり、中で縦に送る。下端を薄くして続きを示す
- 表の列は、左から概念を絞り込む順に並べる (tier → layer → kind → 個々のもの → その中身と数)。集計表では宣言の `show` の順がそのまま列の順になる
- datastore の最初のページは、種類ごとの access matrix (種類はタブで切り替える)。列の名前から個々の datastore (referenced by と call path) へ降りる
- 長い説明 (ツリーの summary など) は畳んでおき、押して開く。名前と並びを先に読めるようにする
- unknown を含む矢印は点線 (色の濃さだけで区別しない)
- 集計表へのリンクは「mart で見る」だけ (表の名前は出さず、マウスを載せたときの説明に入れる)
- 余白の決まり: 節の間は 40px (本文の直下に置く見出し・表・畳んだ節は、前の節から必ず 40px 空ける)。見出しの下は 12px、ページの見出しの下は 24px、注意書きの下は 28px。本文の左右は 48px、下は 96px
- 行の高さ: 表の行は上下 10px、一覧の行は上下 11px。表の下の「さらに表示」は 16px 空ける
- 1023px 以下では 1 列にし、ナビは「メニュー」のボタンで開く。表は個別に横スクロール

## Elevation & Depth

影を使わない。区切りは 1px の罫だけ: 黒 (ページの見出しの下、表の見出しの下) と `hair` (節の見出しの下、行の間)。重なりは、全画面の図と右クリックのメニューだけ (メニューは 1px の黒の縁)。

## Shapes

- 駅: 丸 (経路 14px・縁 2px、一覧と包む入口の並び 9px・縁 1.5px、ナビ 7px・縁 1px)
- 乗換駅: 角丸 3px の四角、縁は黒
- ボタンと絞り込みの札: 角丸 16px、縁 1px の黒 (絞り込みは `edge`)。ボタンは触れると白黒が反転する。絞り込みの札は触れると縁が黒になり、選んだものが黒の塗り
- 入力: 角丸 6px、縁 1px の `edge`。触れたとき・入力中は黒
- 操作の札: 角丸 10px。種類の札: 角丸 12px、縁 1px の黒、先頭に路線の色の点
- 割合の線は 2px、角丸なし
- 箱 (背景を塗ったカード) を作らない。図の入れ物だけ、1px の `hair` の縁を持つ

## Components

| 部品 | 場所 | 決まり |
|---|---|---|
| 経路 | `views/route.js`、`css/views.css` | 先頭に「読み書きの箇所と根拠の場所」(4 行 + 残りは開く)。駅は名前・種類の札・定義場所 (コピー)・概要 (畳む)。枝分かれは字下げ |
| 選べる表 | `ui/table.js` の `pickTable` | 行頭に路線の色の帯。クリック、Enter / スペース、上下の矢印で選ぶ。Tab で止まるのは選んだ行だけ |
| 値の出し方 | `lib/dom.js` の `fmt`、`ui/table.js` の `gridTable` | 値が無い = 「—」。はい / いいえの値は、文字で「はい」「いいえ」と出す (記号にしない。白抜きの丸は「まだ」に、塗った丸は現在地に読めるため)。表の中の「いいえ」は灰の文字 |
| 操作の札 | `.op` / `.op.w` | read する操作 = 白抜き、write する操作 = 朱の塗り。文字は語彙の呼び名 (read、update など) |
| 包む入口の並び | `.through` | 外側から横 1 本の細い線。最後が「この入口」(塗りつぶし) |
| 構成の図 (function が 0 件の layer の箱は、薄い罫の枠と灰の名前で描き、注記に名前を出す。位置は動かさない) | `views/layers.js` (図)、`views/layer-flow.js` (行からの組み立て。構成のページと集計表のページが同じ図を出す)、`svg.layers` | 層 = 白地に 1px の黒の枠の箱 (入口の層だけ路線の色の 2px の枠)。区分 (フロント / バックなど) = 1px の `hair` の枠で、名前は枠の左下。データの種類 = `tint` の塗りの箱、外部接続 = `tint` + 灰の枠。線は `mute` の細い線で、箇所の数で太さを 3 段 (1 / 1.5 / 2px)。確かめられていない箇所を含む線は点線。となりの層へはまっすぐ、層を飛ばす線は上を回る弧、データへは下へ降りる。箱に触れている間は、つながる線と箱だけ残す。図の上の絞り込み (箱の名前、確かめられていない箇所を含む線だけ) も、合わないものを薄くするだけで箱の位置は動かさない。幅が足りないときは図だけ横に送る |
| 注意書き | `.caveat` | 地の文。強調したい数だけ朱。箱にしない |
| 読み込み中 | `ui/card.js` の `loading` | 行の形の灰色の細い帯 3 本 |
| 図 (シーケンス・有向グラフ) | `views/figure-box.js` | 線と枠は灰の細い線。入口の箱だけ路線の色の枠 |
| 物ごとのまとめ | `ui/rollup.js`、`.rollup-row` | 1 行 = 物 1 つ。左から、開閉、名前 (値の札)、棒、数。棒は 2px の黒の線で、端から端までが全体 (関わる入口の総数)。印の付くもの (書く入口) は、朱の 4px の線を重ね、数は「全体 / 朱」で出す。開いた中身は字下げ。並び順は札 (多い順 / 少ない順 / 名前の順) |
| 見え方の切り替え | `.seg` | 2 つの札を 1 本の枠でつなぐ。選んだ方が黒の塗り。節の見出しの右に置く |
| 数の表 | `views/heat.js`、`table.heat` | 行と列の組ごとの数。その列の中で数が多いセルほど、地色を濃くする (無し → `tint` → `sel` + 太字の 3 段。色は足さない)。行が無い組は薄い「—」、値が無いセルは「?」、数えて 0 は薄い「0」。注意して見るセルは朱の太字で、その行を先に並べる。行の見出しと列の見出しは固定 |
| 3 列のつながり | `views/bridge.js`、`.bridge` | 左に物の一覧 (名前の下に、左右の数と、中央の駅から左右へ伸びる 2px の線)。選んだ物は `sel` の地色と左端の黒の帯。右に、入口の列 → 2px の黒の枠の箱 → 入口の列。矢印は黒の 2px。狭い幅では縦に並べる |
| 数つきのツリー | `views/tree.js`、`ul.tree.valued` | 名前の横に、2px の棒と数。棒の端から端までは、いちばん上の段の最大の数。子は畳んで出す |

動きは 1 つだけ: 経路を引き直すときの 0.22 秒の切り替え。`prefers-reduced-motion` では止める。

## Do's and Don'ts

- する: 新しい画面でも、経路・駅・終点の形を同じ意味で使う
- する: 分かっていないこと (未分析、不明、上限で切った数) を、分かっていることと見分けが付く形で出す
- する: 強めたいときは、まず大きさと余白で試す
- しない: 路線の色と朱のほかに、彩度のある色を足す
- しない: 2px を超える線、太さ 700 以上の文字を使う
- しない: 同じ大きさのカードを並べる、影を付ける、背景を塗った注意の箱を作る
- しない: 記号 (矢印、三角) をアイコン代わりに足す
- しない: 画面が集計表の名前を知る書き方をする (宣言と `/meta` だけを読む)

### 構成の 3D 構成図

各区分を、中心軸をそろえた別々の高さの円筒で表す。層は円筒の側面を円周方向に分けた透明な曲面で、処理の点は所属する曲面の半径に固定する。正面からは各面に点が広がり、真上からは点が円弧を描く。データストアは最内周でアプリより低い円筒とし、種類ごとの側面に資源の点を置く。外部 API の接続先は同軸の最外周に並べる。初期視点は斜めとし、上からアプリケーションの各区分、データストア、外部サービスの順に読む。図の外に入口・面・区分を開く操作を並べ、枠内の左上に視点・回転・ズーム・移動の操作をまとめる。区分名を開くと、一つの層が一段の円筒を占める。円周を入口の階層パスで分け、同じパスの処理を各段の同じ方角にまとめる。面の番号は凡例のパスに対応し、色は入口の種類を示す。線上の矢印が呼び出し元から呼び先へ向かい、段をまたぐ線で層間の関係を読める。呼び出しと読み書きを入口の種類に応じた色の細線で結び、白丸で起点を示す。点を選ぶと起点までの経路が濃くなり、図の下に直接のつながりが並ぶ。面を選ぶと、その面に属する全点について同じ強調を重ね、通過する面の輪郭も濃くする。

入口を選んだ後の処理別の断面図では、層を面、処理を駅、読み書きの相手を終点で示す。
