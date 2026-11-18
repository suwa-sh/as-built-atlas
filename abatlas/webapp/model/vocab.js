// 宣言の読み方: 画面に出す呼び名。概念の呼び名は用語集 (schema/vocab/terms.yaml → /meta の terms) から引く。画面のコードには呼び名を直接書かない
//   term("entry") → "entry point"。文の中では `この ${term("entry")} を開く` のように差し込む
//   モジュールの読み込み時 (関数の外) では呼ばない: 用語集は loadCatalog の後に入る

let terms = {};
export function setTerms(o) { terms = o && typeof o === "object" ? o : {}; }
// 用語集に無い id (古い集計表を読んだときなど) は id をそのまま返す (画面を落とさない。id の書き間違いは tests/test_terms.py が見つける)
export function term(id) { return terms[id] || id; }

export const VIEW_ORDER = ["sequence", "heat", "bridge", "tree", "graph", "layers", "matrix", "stat", "table"];
// 表示の種類ごとの「この図の読み方」(宣言に hint が無いときの既定文)
export function viewHint(view) {
  return {
    table: "1 行が 1 件。見出しを押すと並べ替え",
    matrix: `行が ${term("entry")}、列が ${term("datastore")}。▸ を押すと配下を開く。畳んだ行・列の値は配下の和。点線のセルは ${term("unknown")} を含む`,
    graph: "左から右へ流れる。色の意味は図の下の凡例。箱が多いときは絞り込み・拡大縮小・全画面。箱や矢印に触れるとつながりだけ濃く残る",
    layers: `左が呼ぶ側。箱が ${term("layer")}、下の段が ${term("datastore")} と ${term("external")}。線の数字は ${term("call_sites")}。箱に触れると、つながる線だけ残る`,
    sequence: "上から下へ時系列。色の意味は図の下の凡例。参加者が多いときは絞り込み・拡大縮小・全画面。箱や矢印に触れるとつながりだけ濃く残る",
    tree: `${term("entry")} から ${term("call")} を辿ったツリー`,
    stat: "値と、全体に対する割合",
    heat: "行と列の組ごとの数。濃いセルほど、その列の中で数が多い。朱のセルは、注意して見る所。— は行が無い組、? は値が無い。列の見出しを押すと並べ替え",
    bridge: `左の一覧から 1 つ選ぶ。選んだ物の左右に、つながる ${term("entry")} が並ぶ`,
  }[view];
}
// 分析の観点の組 (宣言の topic)。観点のページは、この順に組を並べる。ask = その組が答える問い
export function topics() {
  return [
    { id: "access", name: term("topic_access"), ask: `だれが、どこに入れるか。${term("no_authentication")} の ${term("entry")} はどれか。この ${term("guard")} は、どの ${term("entry")} にあるか` },
    { id: "data_detail", name: term("topic_data_detail"), ask: `この ${term("field")} を ${term("read")} する ${term("entry")}、${term("write")} する ${term("entry")} はどれか。決まった値を書くのはどこか` },
    { id: "links", name: term("topic_links"), ask: `この ${term("datastore")} を ${term("write")} する側を直すと、だれが ${term("read")} しているか。この ${term("entry")} へは、どこから来るか` },
    { id: "behavior", name: term("topic_behavior"), ask: `この ${term("setting")} を変えると、どの ${term("entry")} の動きが変わるか。同じ ${term("rule")} は、どこにあるか` },
    { id: "coverage", name: term("topic_coverage"), ask: `どの ${term("entry")} からも辿られないコードは、どこに固まっているか。${term("test")} の無い ${term("frame")} はどこか` },
  ];
}
// 宣言の subject / 図の参加者の種類 → 用語集の id
const SUBJECT_TERM = { entry: "entry", data: "datastore", external: "external", frame: "shared_frame", aspect: "aspects", analysis: "analysis_status" };
export const subjectLabel = (s) => (SUBJECT_TERM[s] ? term(SUBJECT_TERM[s]) : "");
export const KIND_TERM = { entry: "entry", frame: "frame", data: "datastore", external: "external" };
