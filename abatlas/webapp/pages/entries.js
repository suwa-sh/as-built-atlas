// 画面: 入口の階層 (#/entries/<path>)

import { el } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { hEntries, hEntry, hAccess } from "../lib/hash.js";
import { rows, tree, countOf } from "../lib/api.js";
import { model, levelLabel, levelLabelsText, hierarchyNotes, showCols, kindOf, scopeFilter, attaches } from "../model/catalog.js";
import { pathCrumbs } from "../ui/crumbs.js";
import { cardFor, loading, emptyMsg } from "../ui/card.js";
import { listTable } from "../ui/table.js";
import { panelBody, byView } from "../views/index.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");

export async function nodeInfo(path) {
  // 節の種類: 配下の子 (tree) と、自身が入口か (行が 1 つあるか)
  const col = model.entryMart.keys.path;
  const [kids, selfRows] = await Promise.all([tree(model.entryMart, col, path), path === "/" ? Promise.resolve({ total: 0, rows: [] }) : rows(model.entryMart, { [col]: path }, 1)]);
  const depth = path === "/" ? 0 : segs(path).length;
  return { path, name: path === "/" ? "全体" : segs(path).slice(-1)[0], depth, children: kids, isEntry: selfRows.total > 0, row: selfRows.rows[0] || null, isLeaf: selfRows.total > 0 && kids.length === 0 };
}

export async function pageEntries(path) {
  if (!model.entryMart) {
    $main.replaceChildren(el("div", { class: "head" }, el("div", null, el("h1", null, term("entry")))), el("p", { class: "note" }, `${term("entry")} の階層の元になる表 (subject: entry の table で keys.path を持つもの) が宣言されていないので、階層を辿れない。宣言されている ${term("entry")} の表は下に出す`),
      ...(model.subj.entry || []).map((m) => cardFor(m, panelBody(m, {}, {}), {})));
    return;
  }
  $main.replaceChildren(loading());
  const node = await nodeInfo(path);
  if (node.isLeaf) { location.replace(hEntry(path)); return; }
  const col = model.entryMart.keys.path;
  const filters = model.entryMart.declaration.filters || [];
  const [total, ...fcounts] = await Promise.all([countOf(model.entryMart, { [`${col}__under`]: path }), ...filters.map((f) => countOf(model.entryMart, { [`${col}__under`]: path, ...f.where }).catch(() => null))]);
  const groupsN = node.children.filter((c) => !c.is_leaf).length;
  const head = el("div", { class: "head" },
    el("div", null,
      el("h1", null, node.depth ? node.name : term("entry")),
      el("p", { class: "sub" }, node.depth ? `${levelLabel(node.depth, false)}。` : `分類 (${levelLabelsText()}) を開いて ${term("entry")} へ降りる。`, `${term("entry")} を開くと、何をするか・何に依存するか・そこまでの ${term("call_path")} が見える`)),
    el("div", { class: "kpis" }, groupsN ? el("div", null, el("b", null, groupsN), levelLabel(node.depth + 1, false)) : null, el("div", null, el("b", null, total), term("entry")),
      fcounts.map((n, i) => n ? el("div", null, el("b", null, n), filters[i].label) : null)), // 0 件の絞り込みは見出しに出さない
    el("div", { class: "actions" }, node.isEntry ? el("a", { href: hEntry(path) }, `この ${term("entry")} 自身を開く`) : null));
  const parts = [];
  if (node.depth) parts.push(pathCrumbs(path, hEntries, term("entry"), "#/entries"));
  parts.push(head);
  for (const t of hierarchyNotes()) parts.push(el("p", { class: "note" }, t));
  // 直下の分類 (子を持つ節) の行
  const groups = node.children.filter((c) => !c.is_leaf);
  if (groups.length) {
    const groupCounts = await Promise.all(filters.map((f) => tree(model.entryMart, col, path, f.where).catch(() => [])));
    parts.push(el("h2", null, `${levelLabel(node.depth + 1, false)} (${groups.length})`));
    parts.push(el("div", { class: "rows" }, groups.map((c) => {
      const metas = filters.map((f, i) => { const hit = groupCounts[i].find((x) => x.key === c.key); return hit && hit.leaves ? `${f.label} ${hit.leaves}` : null; }).filter(Boolean); // 0 件の絞り込みは出さない
      const first = groupCounts[0] && groupCounts[0].find((x) => x.key === c.key);
      const ratio = filters.length && c.leaves ? (first ? first.leaves : 0) / c.leaves : null; // 0% でも空の線を出す
      return el("a", { class: "row", href: hEntries(c.key) },
        el("span", { class: "name" }, c.name),
        el("span", { class: "meta" }, el("span", null, `${term("entry")} ${c.leaves}`), metas.map((t) => el("span", null, t))),
        ratio != null ? el("span", { class: "bar", title: `${filters[0].label} ${Math.round(ratio * 100)}%` }, el("i", { style: `width:${Math.round(ratio * 100)}%` })) : el("span"));
    })));
  }
  // 配下の入口の一覧 (直下だけでなく配下すべて。検索と絞り込みはサーバ側)
  parts.push(el("h2", null, node.depth === 0 ? `${term("entry")} の一覧` : `この ${levelLabel(node.depth, false)} の ${term("entry")}`));
  // 列の順は宣言の show (左から概念を絞り込む順)。show に入口の列が無ければ先頭に足す
  const shown = showCols(model.entryMart, (model.entryMart.columns || []).map((c) => c.name)).filter((c) => c !== model.entryMart.keys.label);
  const listCols = shown.includes(col) ? shown : [col, ...shown];
  parts.push(listTable(model.entryMart, { base: { [`${col}__under`]: path }, cols: listCols, rel: { col, root: path }, empty: `この配下に ${term("entry")} が無い` }));
  // この階層の読み書き (種類ごと。既定で閉じている)
  if (model.dataMart) {
    const kinds = await tree(model.dataMart, model.dataMart.keys.col, "/", path === "/" ? {} : { [`${model.dataMart.keys.row}__under`]: path }).catch(() => []);
    const det = el("details", { class: "fold" },
      el("summary", null, node.depth ? `この ${levelLabel(node.depth, false)} の ${term("data_access")}` : `全体の ${term("data_access")}`, el("span", { class: "hint" }, `${term("kind")} ごとに、行と列を開閉できる表を開く`)),
      kinds.length ? el("div", { class: "treelist" }, kinds.map((c) => {
        const k = kindOf(c.name);
        return el("a", { class: "trow", href: hAccess(c.name, path) }, el("span", { class: "lbl" }, el("b", null, k.label || c.name), el("span", { class: "cap" }, `${term("access_matrix")} を開く`)), el("span", { class: "n" }, `${c.leaves} 件の ${term("datastore")}`), el("span"));
      })) : emptyMsg(`この配下の ${term("entry")} はまだ ${term("datastore")} の ${term("data_access")} が分析されていない`));
    parts.push(det);
  }
  // この節に貼る他の表 (subject entry の level: path、attach で段を名指ししたもの)
  for (const m of (model.subj.entry || []).filter((x) => x !== model.entryMart && x.declaration.level === "path" && attaches(x, node)).sort(byView)) {
    const f = scopeFilter(m, node);
    if (f === null) continue;
    parts.push(cardFor(m, panelBody(m, f, {}), f));
  }
  $main.replaceChildren(...parts);
}
