// 表示の種類: 行列 (view: matrix)。行も列も開閉できるクロス表 (読み書きの表のページで使う)

import { el, fmt } from "../lib/dom.js";
import { segs, joinPath } from "../lib/path.js";
import { hEntries, hEntry, hData } from "../lib/hash.js";
import { tree, pivot } from "../lib/api.js";
import { kindOf, dataLevelLabel } from "../model/catalog.js";
import { loading } from "../ui/card.js";
import { listTable } from "../ui/table.js";
import { toast } from "../ui/toast.js";
import { term } from "../model/vocab.js";

const $ctx = document.getElementById("ctx");

export function pivotTable(m, opts) {
  const k = m.keys;
  const kind = opts.kind;
  const kindSpec = kindOf(kind);
  const rowRoot = opts.rowRoot || "/";
  const colRoot = opts.colRoot || "/" + kind;
  const st = { rowOpen: new Set([rowRoot]), colOpen: new Set([colRoot]), touched: true, unknownOnly: false, q: "", swap: false };
  const base = { [k.kind]: kind };
  const rowBase = () => (rowRoot !== "/" ? { [`${k.row}__under`]: rowRoot } : {});
  // 木 (行・列の見出し) と pivot (セルの値) に同じ条件を渡す。表示中の条件に無い行をセルに合算しない
  const cellFilter = () => ({ ...base, ...(st.unknownOnly && k.flag ? { [k.flag]: "true" } : {}), ...(st.q ? { [`${k.col}__contains`]: st.q } : {}) });
  const colFilter = () => ({ ...cellFilter(), ...(st.touched ? rowBase() : {}) });
  const rowFilter = () => ({ ...cellFilter() });
  const wrap = el("div", { class: "pivot-wrap" }, loading());
  const status = el("span", { class: "count" });
  const detail = el("div");
  const search = el("input", { type: "search", placeholder: `${dataLevelLabel(kind, (kindSpec.levels || []).length)} で列を探す`, oninput: () => { st.q = search.value.trim(); draw(); } });
  const tb = el("div", { class: "toolbar" },
    el("span", null, "行: ", el("button", { class: "link", onclick: () => openAll("row") }, "すべて開く"), " | ", el("button", { class: "link", onclick: () => { st.rowOpen = new Set([rowRoot]); draw(); } }, "畳む")),
    el("span", null, "列: ", el("button", { class: "link", onclick: () => openAll("col") }, "すべて開く"), " | ", el("button", { class: "link", onclick: () => { st.colOpen = new Set([colRoot]); draw(); } }, "畳む")),
    search,
    el("label", null, el("input", { type: "checkbox", checked: st.touched, onchange: (ev) => { st.touched = ev.target.checked; draw(); } }), "表示中の行が使う列だけ"),
    k.flag ? el("label", null, el("input", { type: "checkbox", onchange: (ev) => { st.unknownOnly = ev.target.checked; draw(); } }), `${term("unknown")} を含むものだけ`) : null,
    status);
  const legend = el("div", { class: "legend" }, "畳んだ行・列の値はサーバで集計した配下の和 · ", el("span", { class: "box flag" }), `点線 = ${term("unknown")} を含む · 列の名前を押すと、その ${term("datastore")} の ${term("referenced_by")} と ${term("call_path")} · セルを押すと内訳 · ▸ ▾ で開閉、見出しの右クリックで配下をまとめて開閉`);

  // 木を可視の節に展開する (開いている節の子を並べる)
  async function visible(axis) {
    const open = axis === "row" ? st.rowOpen : st.colOpen;
    const root = axis === "row" ? rowRoot : colRoot;
    const col = axis === "row" ? k.row : k.col;
    const filt = axis === "row" ? rowFilter() : colFilter();
    const out = []; // {key, name, depth, open, isLeaf, parent}
    async function walk(key, depth, parentIdx) {
      const kids = await tree(m, col, key, filt);
      for (const c of kids) {
        const idx = out.length;
        const node = { key: c.key, name: c.name, depth, isLeaf: c.is_leaf, open: open.has(c.key) && !c.is_leaf, parent: parentIdx, children: [], leaves: c.leaves };
        out.push(node);
        if (parentIdx != null) out[parentIdx].children.push(idx);
        if (node.open) await walk(c.key, depth + 1, idx);
      }
    }
    await walk(root, 1, null);
    if (!out.length && root !== "/") out.push({ key: root, name: segs(root).slice(-1)[0] || root, depth: 1, isLeaf: true, open: false, parent: null, children: [], leaves: 1 }); // 根が葉 (1 つのデータ・1 つの入口) ならそれ自身を見せる
    return out;
  }
  async function openAll(axis) {
    const open = axis === "row" ? st.rowOpen : st.colOpen;
    const root = axis === "row" ? rowRoot : colRoot;
    const n = await openUnder(axis, root, 400);
    if (n >= 400) toast("開く行・列が多いので 400 個まで開いた。検索で列を絞るか、配下を個別に開く");
    void open;
    draw();
  }
  async function openUnder(axis, key, cap) {
    const open = axis === "row" ? st.rowOpen : st.colOpen;
    const col = axis === "row" ? k.row : k.col;
    const filt = axis === "row" ? rowFilter() : colFilter();
    let n = 0;
    const stack = [key];
    while (stack.length && n < cap) {
      const cur = stack.pop();
      open.add(cur);
      n++;
      const kids = await tree(m, col, cur, filt);
      for (const c of kids) if (!c.is_leaf) stack.push(c.key);
    }
    return n;
  }
  function closeUnder(axis, key) {
    const open = axis === "row" ? st.rowOpen : st.colOpen;
    for (const x of [...open]) if (x === key || x.startsWith(key + "/")) open.delete(x);
    if (key === (axis === "row" ? rowRoot : colRoot)) open.add(key); // 根は閉じない (子は見せる)
  }
  function toggle(axis, key) {
    const open = axis === "row" ? st.rowOpen : st.colOpen;
    if (open.has(key)) closeUnder(axis, key); else open.add(key);
    draw();
  }
  function contextMenu(ev, axis, key) {
    ev.preventDefault();
    $ctx.replaceChildren(el("div", { class: "ttl" }, key),
      el("button", { onclick: async () => { hideCtx(); const n = await openUnder(axis, key, 400); if (n >= 400) toast("配下が多いので 400 個まで開いた"); draw(); } }, "配下をすべて開く"),
      el("button", { onclick: () => { hideCtx(); closeUnder(axis, key); draw(); } }, "配下をすべて閉じる"),
      el("button", { onclick: () => { hideCtx(); location.hash = axis === "row" ? hEntries(key) : hData(kind, joinPath(segs(key).slice(1))); } }, axis === "row" ? `この ${term("entry")} の階層を開く` : `この ${term("datastore")} を開く`));
    $ctx.hidden = false;
    const x = Math.min(ev.clientX, window.innerWidth - 240), y = Math.min(ev.clientY, window.innerHeight - 160);
    $ctx.style.cssText = `left:${x}px;top:${y}px`;
  }
  const hideCtx = hideCtxGlobal;

  let seq = 0;
  async function draw() {
    const my = ++seq;
    wrap.replaceChildren(loading());
    try {
      const [rowsV, colsV] = await Promise.all([visible("row"), visible("col")]);
      if (my !== seq) return;
      // 列の見出し: 開いた節は配下の葉をまたぐ。葉列 = 開いていない可視の節
      const colLeaves = colsV.filter((c) => !c.open);
      const cells = await pivot(m, { row: k.row, col: k.col, value: k.value, flag: k.flag, row_keys: rowsV.map((r) => r.key), col_keys: colLeaves.map((c) => c.key), filters: cellFilter() });
      if (my !== seq) return;
      const cellMap = new Map(cells.cells.map((c) => [c.row + "\u0000" + c.col, c]));
      const maxDepth = Math.max(1, ...colsV.map((c) => c.depth));
      // 列見出しの行 (段ごと)。開いた節は colspan = 配下の葉列の数、rowspan は葉で深さが浅いとき
      const leafCount = (idx) => { const n = colsV[idx]; if (!n.open) return 1; return n.children.reduce((a, ci) => a + leafCount(ci), 0); };
      const headRows = Array.from({ length: maxDepth }, () => []);
      colsV.forEach((c, idx) => {
        const th = el("th", { class: c.open ? "group" : null, "data-node": c.key, title: c.key, colspan: c.open ? leafCount(idx) : null, rowspan: c.open ? null : (maxDepth - c.depth + 1),
          oncontextmenu: c.isLeaf ? null : (ev) => contextMenu(ev, "col", c.key) },
          el("button", { class: "tg" + (c.isLeaf ? " leaf" : ""), onclick: () => toggle("col", c.key), title: c.isLeaf ? null : (c.open ? "畳む" : "配下を開く") }, c.open ? "▾" : "▸"),
          el("a", { class: "lbl", href: hData(kind, joinPath(segs(c.key).slice(1))), title: `${c.key} の ${term("referenced_by")} と ${term("call_path")} を開く` }, c.name));
        headRows[c.depth - 1].push(th);
      });
      const thead = el("thead", null, headRows.map((cells, i) => el("tr", null, i === 0 ? el("th", { class: "corner", rowspan: maxDepth }, `${rowsV.length} × ${colLeaves.length}`) : null, cells)));
      const tbody = el("tbody", null, rowsV.map((r) => el("tr", { class: r.isLeaf ? null : "group" },
        el("th", { "data-node": r.key, title: r.key, style: `padding-left:${8 + (r.depth - 1) * 16}px`, oncontextmenu: r.isLeaf ? null : (ev) => contextMenu(ev, "row", r.key) },
          el("button", { class: "tg" + (r.isLeaf ? " leaf" : ""), onclick: () => toggle("row", r.key), title: r.isLeaf ? null : (r.open ? "畳む" : "配下を開く") }, r.open ? "▾" : "▸"),
          el("a", { href: r.isLeaf ? hEntry(r.key) : hEntries(r.key), title: r.key }, r.name)),
        colLeaves.map((c) => {
          const cell = cellMap.get(r.key + "\u0000" + c.key);
          if (!cell || cell.value == null) return el("td", null, "—");
          return el("td", { class: `has${cell.flag ? " flag" : ""}`, title: `${r.key} × ${c.key}: ${cell.rows} 行。押すと内訳`, onclick: () => showDetail(r, c, cell) }, fmt(cell.value));
        }))));
      wrap.replaceChildren(el("table", { class: "pivot" }, thead, tbody));
      status.textContent = `行 ${rowsV.length} · 列 ${colLeaves.length} (開いた階層 ${colsV.filter((c) => c.open).length})`;
    } catch (e) { if (my === seq) wrap.replaceChildren(el("p", { class: "err" }, e.message)); }
  }
  function showDetail(r, c, cell) {
    const params = { ...cellFilter(), [`${k.row}__under`]: r.key, [`${k.col}__under`]: c.key }; // セルの集計と同じ条件
    detail.replaceChildren(el("div", { class: "detail" },
      el("h3", null, `${r.key} × ${c.key}`, el("span", { class: "muted" }, `${cell.rows} 行`), el("button", { class: "close", onclick: () => detail.replaceChildren() }, "閉じる")),
      listTable(m, { base: params, pageSize: 50 })));
  }
  draw();
  return el("div", null, tb, wrap, legend, detail);
}
export function hideCtxGlobal() { $ctx.hidden = true; }
