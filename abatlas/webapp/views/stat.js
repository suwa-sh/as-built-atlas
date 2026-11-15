// 表示の種類: 指標 (view: stat)

import { el, fmt, isNum, isPathLike } from "../lib/dom.js";
import { hEntries } from "../lib/hash.js";
import { model, titleOf, labelOf } from "../model/catalog.js";
import { emptyMsg } from "../ui/card.js";
import { linkValue } from "../ui/link.js";

export function stat(m, data) {
  const k = m.keys;
  if (!data.rows.length) return emptyMsg("行が無い");
  const used = new Set([k.group, k.value, k.total].filter(Boolean));
  return el("div", { class: "stats" }, data.rows.map((r) => {
    const v = r[k.value], t = k.total ? r[k.total] : null;
    const ratio = isNum(v) && isNum(t) && Number(t) > 0 ? Math.min(1, Number(v) / Number(t)) : null;
    const more = data.columns.filter((c) => !used.has(c) && r[c] != null && r[c] !== "").map((c) => `${labelOf(m, c)}: ${fmt(r[c])}`).join(" · ");
    return el("div", { class: "stat" },
      el("div", { class: "g" }, k.group ? (isPathLike(r[k.group]) ? linkValue(r[k.group]) : (model.entryMart && r[k.group] ? el("a", { href: hEntries("/" + r[k.group]) }, r[k.group]) : fmt(r[k.group]))) : titleOf(m)),
      el("div", { class: "v" }, `${fmt(v)}`, t != null ? el("small", null, ` / ${fmt(t)} ${labelOf(m, k.total)}`) : null),
      ratio != null ? el("div", { class: "bar" }, el("i", { style: `width:${Math.round(ratio * 100)}%` })) : null,
      more ? el("div", { class: "more" }, more) : null);
  }));
}
