// 表示の種類: layer の図 (view: layers)。architecture のページと、その表の mart のページが同じ図を出す。
// 行 (from = layer の id、to = layer の id か "/" + datastore の kind、label = 数、status) を線にし、箱の並びと tier の枠は分析の型 (meta.profile.layers。枠は layers[].tier) から取る。
// 図そのもの (箱と線の配置) は views/layers.js。ここは 行 → 箱と線 の組み立てと、絞り込み、注記、行の表
//   ctx.list === false なら行の表を出さない (architecture のページ)

import { el, fmt } from "../lib/dom.js";
import { hData } from "../lib/hash.js";
import { tree, countOf } from "../lib/api.js";
import { model, kindOf, lineLegend } from "../model/catalog.js";
import { loading, emptyMsg } from "../ui/card.js";
import { gridTable } from "../ui/table.js";
import { term } from "../model/vocab.js";
import { layerDiagram } from "./layers.js";

// layer ごとの function の数。call tree の表が layer の列 (keys.tag) を持つときだけ数えられる
async function frameCounts(layers) {
  const m = model.treeMart;
  if (!m || !m.keys.tag || !m.cols.has(m.keys.tag)) return null;
  const ns = await Promise.all(layers.map((t) => countOf(m, { [m.keys.tag]: t.id }).catch(() => null)));
  return Object.fromEntries(layers.map((t, i) => [t.id, ns[i]]));
}

export function layerFlow(m, data, ctx) {
  const prof = model.meta.profile || {};
  const layers = (Array.isArray(prof.layers) ? prof.layers : []).filter((t) => t && t.id);
  if (!layers.length) return emptyMsg(`この ${term("mart")} には ${term("layer")} の並びが入っていない (図を描けない)`);
  const body = el("div", null, loading());
  Promise.all([frameCounts(layers), model.dataMart ? tree(model.dataMart, model.dataMart.keys.col, "/").catch(() => []) : []])
    .then(([counts, kinds]) => body.replaceChildren(...build(m, data, layers, counts, kinds, ctx || {})))
    .catch((e) => body.replaceChildren(el("p", { class: "err" }, `描けない: ${e.message}`)));
  return body;
}

function build(m, data, layers, counts, kinds, ctx) {
  const k = m.keys;
  const ids = new Set(layers.map((t) => t.id));
  const legend = lineLegend();
  // function が 0 件の layer (分析の型にはあるが、この対象では使われていない) は箱を薄く描く。位置は動かさない
  const empty = layers.filter((t) => counts && counts[t.id] === 0).map((t) => t.id);
  const node = (t) => ({
    id: t.id, name: t.id, group: t.tier || "", title: t.label || t.id,
    sub: counts && counts[t.id] != null ? `${term("frame")} ${fmt(counts[t.id])}` : "",
    cls: (t.role === "entry" ? `entry ${(legend.find((l) => l.label === t.id) || {}).cls || ""}` : t.role === "boundary" ? "boundary" : "") + (empty.includes(t.id) ? " empty" : ""),
  });
  // entry point の layer は 1 列に重ねる。tier が違うものは別の列にする (列は 1 つの枠にしか入らない)
  const entryCols = [];
  for (const t of layers.filter((x) => x.role === "entry")) { const last = entryCols[entryCols.length - 1]; if (last && (last[0].group || "") === (t.tier || "")) last.push(node(t)); else entryCols.push([node(t)]); }
  const columns = [...entryCols, ...layers.filter((t) => t.role !== "entry").map((t) => [node(t)])];
  const edges = [], inner = {}, storeIds = new Set();
  let skipped = 0; // 今の分析の型に無い layer の行 (古い結果)。図には描けない
  for (const r of data.rows) {
    if (r[k.from] == null || r[k.to] == null) continue;
    const from = String(r[k.from]), to = String(r[k.to]), n = Number(k.label ? r[k.label] : 1) || 0;
    const unknown = !!k.status && r[k.status] === "unknown"; // unknown を含む線は点線
    if (!ids.has(from)) { skipped++; continue; }
    if (to.startsWith("/")) { storeIds.add(to); edges.push({ from, to, n, unknown }); }
    else if (from === to) inner[from] = (inner[from] || 0) + n;
    else if (ids.has(to)) edges.push({ from, to, n, unknown });
    else skipped++;
  }
  const out = [];
  {
    const leaves = Object.fromEntries(kinds.map((c) => [c.name, c.leaves]));
    const kindIds = Object.keys(model.meta.resource_kinds || {});
    const stores = [...storeIds].sort((a, b) => kindIds.indexOf(a.slice(1)) - kindIds.indexOf(b.slice(1))).map((sid) => {
      const kind = sid.slice(1), isExt = kind === "external_api";
      return { id: sid, name: isExt ? term("external") : kindOf(kind).label || kind, group: isExt ? term("external_group") : term("datastore"), cls: isExt ? "external" : "", sub: !isExt && leaves[kind] != null ? `${leaves[kind]} 件` : "",
        href: isExt ? (model.subj.external ? "#/external" : null) : (model.subj.data ? hData(kind) : null) };
    });
    const fig = layerDiagram({ columns, stores, edges, label: term("layer_deps") });
    // 絞り込み: 箱の名前、unknown を含む線だけ。合わないものは薄くする (箱の位置は動かさない)
    const state = { q: "", unknownOnly: false };
    const count = el("span", { class: "count" });
    const apply = () => { const r = fig.applyFilter(state); count.textContent = `線 ${r.shown} / ${r.total}`; };
    const search = el("input", { type: "search", placeholder: "箱の名前で絞る", "aria-label": "箱の名前で絞る", oninput: () => { state.q = search.value.trim().toLowerCase(); apply(); } });
    const unk = edges.some((e) => e.unknown) ? el("button", { type: "button", class: "chip", "aria-pressed": "false", onclick: () => {
      state.unknownOnly = !state.unknownOnly;
      unk.classList.toggle("on", state.unknownOnly);
      unk.setAttribute("aria-pressed", String(state.unknownOnly));
      apply();
    } }, `${term("unknown")} を含む線だけ`) : null;
    // 線が 0 本でも箱は描く (layer の並びと、使われていない layer は見える)。絞り込みは線があるときだけ
    if (edges.length) out.push(el("div", { class: "toolbar layers-tools" }, search, unk ? el("div", { class: "chips" }, unk) : null, count));
    else out.push(el("p", { class: "note" }, "線にするつながりが無い。箱だけを出している"));
    apply();
    out.push(el("div", { class: "scroll layers-wrap", tabindex: "0" }, fig));
  }
  const innerText = Object.entries(inner).map(([t, n]) => `${t} ${fmt(n)}`).join("、");
  out.push(el("p", { class: "note layers-note" }, `左が呼ぶ側。${edges.some((e) => e.unknown) ? `点線は ${term("unknown")} を含む線。` : ""}上を回る線は、途中の ${term("layer")} を飛ばす ${term("call")}。`,
    innerText ? `同じ ${term("layer")} の中の ${term("call")} は線にしていない (${innerText})。` : "",
    empty.length ? `薄い箱は、${term("profile")} にはあるが ${term("frame")} が 0 件の ${term("layer")} (${empty.join("、")})。` : "",
    skipped ? `今の ${term("profile")} に無い ${term("layer")} の行 ${skipped} 件は、図に出していない。` : "",
    `${term("entry")} ごとの実際の通り道は、${term("entry")} や ${term("datastore")} のページの「${term("call_path")}」で見る`));
  if (ctx.list !== false) out.push(el("h2", null, "行"), gridTable(m, data.rows, data.columns, {}));
  return out;
}
