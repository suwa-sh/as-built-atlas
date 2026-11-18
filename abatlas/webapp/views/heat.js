// 表示の種類: 行と列の組ごとの数 (view: heat)。階層で畳まない平らな表。全体を 1 枚で見て、偏りと例外を探す
//   濃いセルほど、その列の中で数が多い。keys.flag が真のセルは朱 (注意して見る所)

import { el, fmt } from "../lib/dom.js";
import { labelOf } from "../model/catalog.js";
import { emptyMsg } from "../ui/card.js";
import { linkValue } from "../ui/link.js";

export function heat(m, data) {
  const k = m.keys;
  if (!data.rows.length) return emptyMsg("行が無い");
  const cols = new Map(); // 列の値 → 並び順
  const rows = new Map(); // 行の値 → { 列の値 → 行 }
  for (const r of data.rows) {
    const c = String(r[k.col] ?? "");
    const ord = k.order && typeof r[k.order] === "number" ? r[k.order] : 0;
    if (!cols.has(c) || ord < cols.get(c)) cols.set(c, ord);
    const key = String(r[k.row] ?? "");
    if (!rows.has(key)) rows.set(key, new Map());
    rows.get(key).set(c, r);
  }
  const colKeys = [...cols.keys()].sort((a, b) => cols.get(a) - cols.get(b) || a.localeCompare(b));
  const val = (cells, c) => { const r = cells.get(c); return r && typeof r[k.value] === "number" ? r[k.value] : 0; };
  const flagged = (cells) => !!k.flag && [...cells.values()].some((r) => r[k.flag] === true);
  const max = Object.fromEntries(colKeys.map((c) => [c, Math.max(1, ...[...rows.values()].map((cells) => val(cells, c)))]));
  const st = { q: "", flagOnly: false, sort: null };
  const body = el("tbody");
  const count = el("span", { class: "count" });
  const head = el("tr");

  function draw() {
    let keys = [...rows.keys()].filter((key) => (!st.q || key.toLowerCase().includes(st.q)) && (!st.flagOnly || flagged(rows.get(key))));
    // 既定の並び: 印のある行を先に、その中は名前の順。列を選んだら、その列の数の多い順
    keys.sort((a, b) => (st.sort ? val(rows.get(b), st.sort) - val(rows.get(a), st.sort) : Number(flagged(rows.get(b))) - Number(flagged(rows.get(a)))) || a.localeCompare(b));
    head.replaceChildren(el("th", { class: "corner" }, labelOf(m, k.row)), ...colKeys.map((c) => el("th", { "aria-sort": st.sort === c ? "descending" : null },
      el("button", { class: "link", title: "押すと、この列の数の多い順に並べる (もう一度押すと、元の順)", onclick: () => { st.sort = st.sort === c ? null : c; draw(); } }, c, st.sort === c ? el("span", { class: "dir" }, "▼") : null))));
    body.replaceChildren(...keys.map((key) => {
      const cells = rows.get(key);
      return el("tr", { class: flagged(cells) ? "flagrow" : null },
        el("th", { scope: "row" }, linkValue(key, m, k.row)),
        colKeys.map((c) => {
          const r = cells.get(c);
          const n = val(cells, c);
          if (r && k.flag && r[k.flag] === true) return el("td", { class: "flag" }, n ? fmt(n) : labelOf(m, k.flag));
          // 行が無い組は「—」、値が無い (null) は「?」、数えて 0 は「0」。3 つを見分けられるようにする
          if (!r) return el("td", { class: "zero" }, "—");
          if (typeof r[k.value] !== "number") return el("td", { class: "zero", title: "値が無い" }, "?");
          if (!n) return el("td", { class: "zero" }, "0");
          const step = n / max[c] > 0.66 ? 3 : n / max[c] > 0.33 ? 2 : 1;
          return el("td", { class: `h${step}` }, fmt(n));
        }));
    }));
    count.textContent = keys.length === rows.size ? `${rows.size} 行` : `${keys.length} / ${rows.size} 行`;
  }
  const search = el("input", { type: "search", "aria-label": `${labelOf(m, k.row)} で探す`, placeholder: `${labelOf(m, k.row)} で探す`, oninput: () => { st.q = search.value.trim().toLowerCase(); draw(); } });
  const flagCount = k.flag ? [...rows.values()].filter(flagged).length : 0;
  const tools = el("div", { class: "toolbar" }, search,
    k.flag ? el("label", null, el("input", { type: "checkbox", onchange: (ev) => { st.flagOnly = ev.target.checked; draw(); } }), `${labelOf(m, k.flag)} だけ (${flagCount})`) : null,
    count);
  draw();
  return el("div", null, tools, el("div", { class: "scroll heat-wrap" }, el("table", { class: "heat" }, el("thead", null, head), body)));
}
