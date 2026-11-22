// 表示の種類: ツリー (view: tree)

import { el, fmt } from "../lib/dom.js";
import { labelOf } from "../model/catalog.js";
import { emptyMsg } from "../ui/card.js";
import { linkValue } from "../ui/link.js";

export function tree(m, data) {
  const k = m.keys;
  if (!data.rows.length) return emptyMsg("行が無い");
  const groups = groupRows(data, k);
  const out = el("div");
  appendDetailToggle(k, data, m, out);
  for (const [g, list] of groups) {
    const { roots, children } = indexChildren(list, k);
    const seen = new Set();
    const varying = varyingColumns(data, k, list);
    // 数の列 (keys.value) があるとき: 名前の横に棒と数を出し、子は数の多い順に並べて、畳んで出す (フォルダごとの件数など)
    const has = (r) => typeof r[k.value] === "number"; // 数の無い行 (null) は、0 と区別して「?」で出し、棒を引かない
    const num = (r) => (k.value && has(r) ? r[k.value] : 0);
    const top = sortBySize(k, roots, num, children);
    const group = { m, k, data, seen, children, varying, has, num, top };
    const node = (r) => renderNode(group, r);
    if (groups.size > 1) out.append(el("div", { class: "group-title" }, linkValue(g)));
    out.append(el("ul", { class: k.value ? "tree valued" : "tree" }, roots.map(node)));
    showOrphans(list, seen, k, out, node);
  }
  return out;
}

function renderNode(group, r) {
  const { m, k, data, seen, children, varying, has, num, top } = group;
  const id = String(r[k.id]);
  if (seen.has(id))
    return el("li", { class: "err" }, `循環: ${fmt(r[k.label])} (${id}) は既に上に出ている`);
  seen.add(id);
  const kids = children.get(id) || [];
  const sub = kids.length
    ? el(
        "ul",
        { hidden: !!k.value },
        kids.map((child) => renderNode(group, child)),
      )
    : null;
  const title = data.columns.map((c) => `${labelOf(m, c)}: ${fmt(r[c])}`).join("\n");
  const tags = nodeTags(varying, r);
  return el(
    "li",
    null,
    el(
      "span",
      { class: "node", title },
      branchToggle(sub, k),
      el("span", { class: "lbl" }, fmt(r[k.label])),
      nodeBar(k, has, r, num, top),
      k.value ? null : tags.map((t) => el("span", { class: "tag" }, t)),
    ),
    k.detail && r[k.detail]
      ? el(
          "details",
          { class: "det" },
          el("summary", null, labelOf(m, k.detail)),
          el("p", null, r[k.detail]),
        )
      : null,
    sub,
  );
}

function groupRows(data, k) {
  const groups = new Map();
  for (const r of data.rows) {
    const g = k.group ? String(r[k.group] ?? "") : "";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(r);
  }
  return groups;
}

function appendDetailToggle(k, data, m, out) {
  if (k.detail && data.rows.some((r) => r[k.detail])) {
    // 説明は畳んでおく (名前と並びを先に読む)。まとめて開く操作は先頭に 1 つ
    const name = labelOf(m, k.detail);
    const all = el(
      "button",
      {
        class: "link",
        onclick: () => {
          const open = all.dataset.open !== "1";
          all.dataset.open = open ? "1" : "0";
          all.textContent = `${name} をすべて${open ? "畳む" : "開く"}`;
          for (const d of out.querySelectorAll("details.det")) d.open = open;
        },
      },
      `${name} をすべて開く`,
    );
    out.append(el("div", { class: "tree-tools" }, all));
  }
}

function indexChildren(list, k) {
  const byId = new Map(list.map((r) => [String(r[k.id]), r]));
  const children = new Map();
  const roots = [];
  for (const r of list) {
    const p = r[k.parent];
    if (p == null || p === "" || !byId.has(String(p))) roots.push(r);
    else {
      if (!children.has(String(p))) children.set(String(p), []);
      children.get(String(p)).push(r);
    }
  }
  return { roots, children };
}

function varyingColumns(data, k, list) {
  const used = new Set([k.id, k.parent, k.label, k.group, k.detail, k.value].filter(Boolean));

  const varying = data.columns.filter(
    (c) => !used.has(c) && new Set(list.map((r) => r[c])).size > 1,
  );
  return varying;
}

function sortBySize(k, roots, num, children) {
  const top = k.value ? Math.max(1, ...roots.map(num)) : 0;
  if (k.value) {
    roots.sort((a, b) => num(b) - num(a));
    for (const kids of children.values()) kids.sort((a, b) => num(b) - num(a));
  }
  return top;
}

function nodeTags(varying, r) {
  return [
    ...new Set(
      varying
        .filter((c) => typeof r[c] === "string" && r[c] && r[c].length <= 24 && !/^\d+$/.test(r[c]))
        .slice(0, 2)
        .map((c) => r[c]),
    ),
  ];
}

function branchToggle(sub, k) {
  return sub
    ? el(
        "button",
        {
          class: "toggle",
          "aria-expanded": String(!k.value),
          title: "下の階層を開く・畳む",
          onclick: (ev) => {
            sub.hidden = !sub.hidden;
            ev.target.textContent = sub.hidden ? "+" : "−";
            ev.target.setAttribute("aria-expanded", String(!sub.hidden));
          },
        },
        k.value ? "+" : "−",
      )
    : k.value
      ? el("span", { class: "toggle-gap" })
      : null;
}

function nodeBar(k, has, r, num, top) {
  return k.value
    ? [
        el(
          "span",
          { class: "tbar" },
          has(r)
            ? el("i", { style: `width:${Math.max(1, Math.round((num(r) / top) * 100))}%` })
            : null,
        ),
        el(
          "span",
          { class: "tnum", title: has(r) ? null : "値が無い" },
          has(r) ? fmt(num(r)) : "?",
        ),
      ]
    : null;
}

function showOrphans(list, seen, k, out, node) {
  const orphans = list.filter((r) => !seen.has(String(r[k.id])));
  if (orphans.length) {
    out.append(
      el(
        "p",
        { class: "err" },
        `${orphans.length} 行は根から辿れない (親子関係が循環している)。以下にそのまま出す`,
      ),
    );
    out.append(
      el(
        "ul",
        { class: "tree" },
        orphans.map((r) => (seen.has(String(r[k.id])) ? null : node(r))),
      ),
    );
  }
}
