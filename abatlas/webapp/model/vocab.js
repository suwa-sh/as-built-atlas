// 宣言の読み方: 画面に出す呼び名。概念の呼び名は用語集 (schema/vocab/terms.yaml → /meta の terms) から引く。画面のコードには呼び名を直接書かない
//   term("entry") → "entry point"。文の中では `この ${term("entry")} を開く` のように差し込む
//   モジュールの読み込み時 (関数の外) では呼ばない: 用語集は loadCatalog の後に入る

let terms = {};
export function setTerms(o) { terms = o && typeof o === "object" ? o : {}; }
// 用語集に無い id (古い集計表を読んだときなど) は id をそのまま返す (画面を落とさない。id の書き間違いは tests/test_terms.py が見つける)
export function term(id) { return terms[id] || id; }

export const VIEW_ORDER = ["sequence", "tree", "graph", "layers", "matrix", "stat", "table"];
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
  }[view];
}
// 宣言の subject / 図の参加者の種類 → 用語集の id
const SUBJECT_TERM = { entry: "entry", data: "datastore", external: "external", frame: "shared_frame", aspect: "aspects", analysis: "analysis_status" };
export const subjectLabel = (s) => (SUBJECT_TERM[s] ? term(SUBJECT_TERM[s]) : "");
export const KIND_TERM = { entry: "entry", frame: "frame", data: "datastore", external: "external" };
