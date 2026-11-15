// 表示の種類: ツリー (view: tree)

import { el, fmt } from "../lib/dom.js";
import { labelOf } from "../model/catalog.js";
import { emptyMsg } from "../ui/card.js";
import { linkValue } from "../ui/link.js";

export function tree(m, data) {
  const k = m.keys;
  if (!data.rows.length) return emptyMsg("行が無い");
  const groups = new Map();
  for (const r of data.rows) {
    const g = k.group ? String(r[k.group] ?? "") : "";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(r);
  }
  const out = el("div");
  if (k.detail && data.rows.some((r) => r[k.detail])) {
    // 説明は畳んでおく (名前と並びを先に読む)。まとめて開く操作は先頭に 1 つ
    const name = labelOf(m, k.detail);
    const all = el("button", { class: "link", onclick: () => { const open = all.dataset.open !== "1"; all.dataset.open = open ? "1" : "0"; all.textContent = `${name} をすべて${open ? "畳む" : "開く"}`; for (const d of out.querySelectorAll("details.det")) d.open = open; } }, `${name} をすべて開く`);
    out.append(el("div", { class: "tree-tools" }, all));
  }
  for (const [g, list] of groups) {
    const byId = new Map(list.map((r) => [String(r[k.id]), r]));
    const children = new Map();
    const roots = [];
    for (const r of list) {
      const p = r[k.parent];
      if (p == null || p === "" || !byId.has(String(p))) roots.push(r);
      else { if (!children.has(String(p))) children.set(String(p), []); children.get(String(p)).push(r); }
    }
    const used = new Set([k.id, k.parent, k.label, k.group, k.detail].filter(Boolean));
    const varying = data.columns.filter((c) => !used.has(c) && new Set(list.map((r) => r[c])).size > 1);
    const seen = new Set();
    function node(r) {
      const id = String(r[k.id]);
      if (seen.has(id)) return el("li", { class: "err" }, `循環: ${fmt(r[k.label])} (${id}) は既に上に出ている`);
      seen.add(id);
      const kids = children.get(id) || [];
      const sub = kids.length ? el("ul", null, kids.map(node)) : null;
      const title = data.columns.map((c) => `${labelOf(m, c)}: ${fmt(r[c])}`).join("\n");
      const tags = [...new Set(varying.filter((c) => typeof r[c] === "string" && r[c] && r[c].length <= 24 && !/^\d+$/.test(r[c])).slice(0, 2).map((c) => r[c]))];
      return el("li", null,
        el("span", { class: "node", title },
          sub ? el("button", { class: "toggle", onclick: (ev) => { sub.hidden = !sub.hidden; ev.target.textContent = sub.hidden ? "+" : "−"; } }, "−") : null,
          el("span", { class: "lbl" }, fmt(r[k.label])),
          tags.map((t) => el("span", { class: "tag" }, t))),
        k.detail && r[k.detail] ? el("details", { class: "det" }, el("summary", null, labelOf(m, k.detail)), el("p", null, r[k.detail])) : null,
        sub);
    }
    if (groups.size > 1) out.append(el("div", { class: "group-title" }, linkValue(g)));
    out.append(el("ul", { class: "tree" }, roots.map(node)));
    const orphans = list.filter((r) => !seen.has(String(r[k.id])));
    if (orphans.length) {
      out.append(el("p", { class: "err" }, `${orphans.length} 行は根から辿れない (親子関係が循環している)。以下にそのまま出す`));
      out.append(el("ul", { class: "tree" }, orphans.map((r) => (seen.has(String(r[k.id])) ? null : node(r)))));
    }
  }
  return out;
}
