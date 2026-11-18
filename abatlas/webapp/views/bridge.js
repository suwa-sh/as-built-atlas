// 表示の種類: 真ん中の物と、左右につながる入口 (view: bridge)。物を 1 つ選ぶと、左 → 物 → 右 の 3 列で描く
//   全部を 1 枚に描くと線が絡むので、真ん中を 1 つ選ぶ形にする。左右の入口は、keys.left / keys.right の列 (パスを ", " で連ねたもの)

import { el, fmt } from "../lib/dom.js";
import { labelOf } from "../model/catalog.js";
import { emptyMsg } from "../ui/card.js";
import { linkOne } from "../ui/link.js";

const SHOWN = 12; // 片側に、最初に並べる数 (残りは、開く)
const split = (v) => (typeof v === "string" && v ? v.split(", ").filter(Boolean) : []);

export function bridge(m, data) {
  const k = m.keys;
  if (!data.rows.length) return emptyMsg("行が無い (該当が無いか、まだ分析されていない)");
  const hubs = data.rows.map((r) => ({ id: String(r[k.id]), label: String(r[k.label || k.id] ?? ""), kind: k.kind ? r[k.kind] : null, left: split(r[k.left]), right: split(r[k.right]) }))
    .sort((a, b) => (b.left.length + b.right.length) - (a.left.length + a.right.length) || a.label.localeCompare(b.label));
  const top = Math.max(1, ...hubs.map((h) => Math.max(h.left.length, h.right.length)));
  const st = { q: "", cur: hubs[0].id };
  const list = el("ul", { class: "bridge-hubs", "aria-label": labelOf(m, k.label || k.id) });
  const fig = el("div", { class: "bridge-fig" });
  const count = el("span", { class: "count" });

  function side(paths, cls, title) {
    const items = paths.map((p) => el("li", null, linkOne(p)));
    const rest = items.slice(SHOWN);
    for (const li of rest) li.hidden = true;
    const more = rest.length ? el("button", { class: "link", onclick: () => { for (const li of rest) li.hidden = false; more.remove(); } }, `ほか ${rest.length} 件を開く`) : null;
    return el("div", { class: `bridge-side ${cls}` },
      el("div", { class: "cap" }, `${title} (${paths.length})`),
      paths.length ? el("ul", null, items) : el("p", { class: "empty" }, "無い"),
      more);
  }
  function drawFig() {
    const h = hubs.find((x) => x.id === st.cur) || hubs[0];
    fig.replaceChildren(
      side(h.left, "left", labelOf(m, k.left)),
      el("div", { class: "bridge-arrow", "aria-hidden": "true" }),
      el("div", { class: "bridge-hub" }, h.kind ? el("span", { class: "tag" }, h.kind) : null, el("div", { class: "nm" }, linkOne(h.id))),
      el("div", { class: "bridge-arrow", "aria-hidden": "true" }),
      side(h.right, "right", labelOf(m, k.right)));
  }
  function drawList() {
    const shown = hubs.filter((h) => !st.q || h.label.toLowerCase().includes(st.q));
    list.replaceChildren(...shown.map((h) => el("li", null, el("button", { class: `hub${h.id === st.cur ? " on" : ""}`, "aria-pressed": String(h.id === st.cur), title: h.id, onclick: () => { st.cur = h.id; drawList(); drawFig(); } },
      el("span", { class: "nm" }, h.label),
      el("span", { class: "io" },
        el("span", { class: "num" }, fmt(h.left.length)), el("span", { class: "bar l" }, el("i", { style: `width:${(h.left.length / top) * 100}%` })),
        el("span", { class: "dot" }),
        el("span", { class: "bar r" }, el("i", { style: `width:${(h.right.length / top) * 100}%` })), el("span", { class: "num" }, fmt(h.right.length)))))));
    if (!shown.length) list.replaceChildren(el("li", { class: "empty" }, "該当する物が無い"));
    count.textContent = shown.length === hubs.length ? `${hubs.length} 件` : `${shown.length} / ${hubs.length} 件`;
  }
  const search = el("input", { type: "search", "aria-label": `${labelOf(m, k.label || k.id)} で探す`, placeholder: `${labelOf(m, k.label || k.id)} で探す`, oninput: () => { st.q = search.value.trim().toLowerCase(); drawList(); } });
  drawList();
  drawFig();
  return el("div", null,
    el("div", { class: "toolbar" }, search, count),
    el("div", { class: "bridge" }, el("div", { class: "bridge-pick" }, el("div", { class: "cap" }, `${labelOf(m, k.left)} の数 · ${labelOf(m, k.right)} の数`), list), fig));
}
