// 表示の種類: 登録表 (宣言の view → 描き方)。新しい図の種類は views/<name>.js を作り、renderers に 1 行足す

import { el } from "../lib/dom.js";
import { rows, rowsAll, BIG } from "../lib/api.js";
import { hMart } from "../lib/hash.js";
import { VIEW_ORDER, term } from "../model/vocab.js";
import { loading } from "../ui/card.js";
import { listTable } from "../ui/table.js";
import { table } from "./table.js";
import { stat } from "./stat.js";
import { graph } from "./graph.js";
import { tree } from "./tree.js";
import { sequence } from "./sequence.js";
import { layerFlow } from "./layer-flow.js";
import { heat } from "./heat.js";
import { bridge } from "./bridge.js";

export const renderers = { table, stat, graph, tree, sequence, layers: layerFlow, heat, bridge };
export function render(m, data, ctx) {
  const fn = renderers[m.declaration.view] || renderers.table;
  try { return fn(m, data, ctx); } catch (e) { return el("p", { class: "err" }, `描けない: ${e.message}`); }
}
// mart 1 つを絞って描く (表は 50 件ずつの一覧、図は全行)
export function panelBody(m, filter, ctx) {
  if (m.declaration.view === "table" || m.declaration.view === "matrix") return listTable(m, { base: filter, link: ctx && ctx.link, rel: ctx && ctx.rel }); // 行列の汎用表示は行の一覧 (開閉する表は読み書きの表のページ)
  const body = el("div", null, loading());
  // 入口をまたぐ図 (絞り込みが無いときの heat / bridge / 数つきのツリー) は、1 回で読める行数までで描く。切ったら、切ったことを出して、全体を見られる場所へ誘導する
  const wide = !Object.keys(filter || {}).length && (m.declaration.view === "heat" || m.declaration.view === "bridge" || (m.declaration.view === "tree" && m.keys.value));
  const read = wide ? rows(m, filter, BIG) : rowsAll(m, filter);
  // replaceChildren は、null を「null」という文字にする。知らせが無いときは、並びに入れない
  read.then((data) => body.replaceChildren(
    ...(data.total > data.rows.length ? [el("p", { class: "caveat" }, el("b", null, `${data.total} 行のうち、先頭の ${data.rows.length} 行で描いている`), "。全体は ", el("a", { href: hMart(m.name) }, `${term("mart")} で見る`))] : []),
    render(m, data, ctx))).catch((e) => body.replaceChildren(el("p", { class: "err" }, e.message)));
  return body;
}
export const byView = (a, b) => VIEW_ORDER.indexOf(a.declaration.view) - VIEW_ORDER.indexOf(b.declaration.view) || a.name.localeCompare(b.name);
