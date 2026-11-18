// 汎用部品: 物ごとのまとめ (宣言の rollup)。同じ物が、入口の数だけ行になっている表を、「1 つの物 = 1 行」で読む
//   1 行 = 物 1 つ。棒は、その物に関わる member (ふつうは入口) の数。開くと、次の段のまとめか、その物の行の一覧
//   数えるのはサーバ (API の groups)。全行を読まない

import { el, fmt } from "../lib/dom.js";
import { groups, PAGE } from "../lib/api.js";
import { labelOf, showCols } from "../model/catalog.js";
import { loading, emptyMsg } from "./card.js";
import { linkValue } from "./link.js";
import { listTable } from "./table.js";

const ORDERS = [["-members", "多い順"], ["members", "少ない順"], ["key", "名前の順"]];

export function rollupList(m, opts) {
  const o = { base: {}, ...opts };
  const r = m.declaration.rollup;
  const st = { q: "", order: "-members", scale: 1 };
  const count = el("span", { class: "count" });
  const search = el("input", { type: "search", "aria-label": `${labelOf(m, r.by[0])} で探す`, placeholder: `${labelOf(m, r.by[0])} で探す`, oninput: () => { st.q = search.value.trim(); draw(); } });
  const orderBar = el("div", { class: "chips", role: "group", "aria-label": "並び順" });
  const body = el("div", { class: "rollup" });
  const legend = el("p", { class: "legend" });

  function drawOrder() {
    orderBar.replaceChildren(...ORDERS.map(([id, text]) => el("button", { class: `chip${st.order === id ? " on" : ""}`, "aria-pressed": String(st.order === id), onclick: () => { st.order = id; draw(); } }, text)));
  }
  // 1 段分 (by[depth] でまとめた行) を host に描く。filter は、上の段で選んだ物の条件
  function level(host, depth, filter, top) {
    const by = r.by[depth];
    const last = depth === r.by.length - 1;
    const acc = [];
    const list = el("ul", { class: "rollup-rows" });
    const pager = el("div", { class: "pager" });
    host.replaceChildren(loading());
    let seq = 0;
    async function load() {
      const my = ++seq;
      try {
        const data = await groups(m, { ...filter, by, member: r.member, flag: r.flag, chip: last ? r.chip : null, order: st.order, q: top ? st.q : null, limit: PAGE, offset: acc.length });
        if (my !== seq) return;
        if (top) { st.scale = Math.max(1, data.member_total); count.textContent = `${data.total} 件`; drawLegend(data.member_total); }
        if (!acc.length && !data.groups.length) { host.replaceChildren(emptyMsg(top && !st.q ? "行が無い (該当が無いか、まだ分析されていない)" : "該当する行が無い")); return; }
        acc.push(...data.groups);
        list.append(...data.groups.map((g) => row(g, by, depth, filter, last)));
        const rest = data.total - acc.length;
        pager.replaceChildren(...(rest > 0 ? [el("span", null, `${acc.length} 件を表示 · 残り ${rest} 件`), el("button", { onclick: load }, `さらに ${Math.min(PAGE, rest)} 件を表示`)] : []));
        if (!list.isConnected) host.replaceChildren(list, pager);
      } catch (e) { if (my === seq) host.replaceChildren(el("p", { class: "err" }, e.message)); }
    }
    load();
  }
  function row(g, by, depth, filter, last) {
    const next = { ...filter, ...(g.key === "" ? { [`${by}__empty`]: "1" } : { [by]: g.key }) };
    const inner = el("div", { class: "rollup-inner", hidden: true });
    let opened = false;
    const tg = el("button", { class: "tg", "aria-expanded": "false", title: "開く・畳む", onclick: () => {
      inner.hidden = !inner.hidden;
      tg.setAttribute("aria-expanded", String(!inner.hidden));
      tg.textContent = inner.hidden ? "▸" : "▾";
      if (opened || inner.hidden) return;
      opened = true;
      if (!last) level(inner, depth + 1, next, false);
      else inner.replaceChildren(listTable(m, { base: next, link: o.link, cols: showCols(m, (m.columns || []).map((c) => c.name)).filter((c) => !r.by.includes(c)), pageSize: 20 }));
    } }, "▸");
    const pct = (n) => `${Math.min(100, Math.max(n > 0 ? 1 : 0, (n / st.scale) * 100)).toFixed(1)}%`;
    return el("li", null,
      el("div", { class: "rollup-row" },
        tg,
        el("span", { class: "name" }, g.key === "" ? el("span", { class: "muted" }, "(値なし)") : linkValue(g.key, m, by),
          (g.chips || []).map((c) => el("span", { class: "tag" }, c)), g.chips_more ? el("span", { class: "muted" }, `ほか ${g.chips_more}`) : null),
        el("span", { class: "bar", "aria-hidden": "true" }, el("i", { style: `width:${pct(g.members)}` }), r.flag && g.flagged ? el("i", { class: "flag", style: `width:${pct(g.flagged)}` }) : null),
        el("span", { class: "n" }, fmt(g.members), r.flag ? el("span", { class: g.flagged ? "flagged" : "muted" }, ` / ${fmt(g.flagged)}`) : null)),
      inner);
  }
  function drawLegend(total) {
    const member = labelOf(m, r.member);
    if (!total) { legend.replaceChildren(); return; }
    legend.replaceChildren(el("span", null, `棒と数 = その物に関わる ${member} の数 (棒の端から端までで ${fmt(total)})`,
      r.flag ? [" · ", el("span", { class: "flagged" }, `朱と、斜線の後ろの数 = そのうち ${labelOf(m, r.flag)}`)] : null,
      r.by.length > 1 ? ` · 開くと ${r.by.slice(1).map((c) => labelOf(m, c)).join(" → ")}、最後に行の一覧` : " · 開くと行の一覧"));
  }
  function draw() { drawOrder(); level(body, 0, o.base, true); }
  draw();
  return el("div", { class: "list" }, el("div", { class: "toolbar" }, search, orderBar, count), body, legend);
}
