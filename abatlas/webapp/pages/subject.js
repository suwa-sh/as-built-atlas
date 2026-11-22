// 画面: 外部接続 / 共有処理 (一覧 → 詳細)

import { el } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { hEntry } from "../lib/hash.js";
import { rowsAll } from "../lib/api.js";
import { model, titleOf, labelOf, physLink, entryLabel, lineOf } from "../model/catalog.js";
import { crumbs } from "../ui/crumbs.js";
import { cardFor, loading, emptyMsg } from "../ui/card.js";
import { linkValue } from "../ui/link.js";
import { listTable, pickTable } from "../ui/table.js";
import { routePanel } from "../views/route.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");

export function pageSubjectList(subject, title, note, hashFor, id) {
  const marts = (model.subj[subject] || []).filter((m) => m.declaration.view === "table");
  if (!marts.length) {
    $main.replaceChildren(
      el("div", { class: "head" }, el("div", null, el("h1", null, title))),
      el("p", { class: "note" }, `subject: ${subject} の表が宣言されていない`),
    );
    return;
  }
  if (id != null) return pageSubjectDetail(subject, title, hashFor, id);
  $main.replaceChildren(
    el(
      "div",
      { class: "head" },
      el("div", null, el("h1", null, title), el("p", { class: "sub" }, note)),
    ),
    ...marts.map((m) => cardFor(m, listTable(m, { link: (r) => hashFor(m, r[m.keys.id]) }), {})),
  );
}
export async function pageSubjectDetail(subject, title, hashFor, id) {
  const cut = id.indexOf("/"); // `<mart>/<id>` (それぞれ encodeURIComponent 済み。ID に / や :: が入っても壊れない)
  const martName = decodeURIComponent(cut < 0 ? id : id.slice(0, cut));
  const value = cut < 0 ? "" : decodeURIComponent(id.slice(cut + 1));
  const m = model.catalog.find((x) => x.name === martName);
  if (!m) {
    $main.replaceChildren(el("h1", null, "無い"));
    return;
  }
  $main.replaceChildren(loading());
  const d = await rowsAll(m, { [m.keys.id]: value }); // 同じ名前の行をすべて読む (入口の集合と経路の照合を、一部の行だけで作らない)
  const { list, facts, row0 } = collectMemberFacts(m, d);
  // 終点: 外部接続はそのホストのパス (配下も含む)、共有処理はその部品の名前
  const { routable, target } = resolveMemberTarget(m, d, subject, value);
  const pane = el("div", { class: "pane" });
  const title2 = el(
    "div",
    { class: "card-head" },
    el("h2", null, term("referenced_by")),
    el(
      "span",
      { class: "hint" },
      `これを変えると影響を受ける ${term("entry")}。行を選ぶと ${term("call_path")} が出る`,
    ),
    physLink(m, { [m.keys.id]: value }),
  );
  const parts = subjectHeader({ title, hashFor, value, m, list, d, facts, row0 });
  appendSubjectMembers({ list, parts, title2, m, pane, routable, target, d });
  if (d.total > 1)
    parts.push(cardFor(m, listTable(m, { base: { [m.keys.id]: value } }), { [m.keys.id]: value }));
  $main.replaceChildren(...parts);
}

function collectMemberFacts(m, d) {
  const cols = (m.columns || []).map((c) => c.name);
  const members = subjectMembers(m, d);
  const facts = cols.filter((c) => c !== m.keys.members && c !== m.keys.id);
  const list = [...members].sort();
  const row0 = d.rows[0] || {};
  return { list, facts, row0 };
}

function resolveMemberTarget(m, d, subject, value) {
  const sources = new Set(
    m.keys.source ? d.rows.map((r) => String(r[m.keys.source] || "")).filter(Boolean) : [],
  );
  const target =
    subject === "external"
      ? { kind: "data", path: "/external_api/" + value, label: value }
      : { kind: "frame", name: value, label: value, sources };
  // 指している段がパスに現れない外部接続 (例: ホストが分からないもの) は、終点のパスを決められないので経路を引かない
  const routable =
    subject !== "external" ||
    d.rows.some((r) => m.keys.id && r[m.keys.id] === value && !/^\(.*\)$/.test(value));
  return { routable, target };
}

function subjectHeader({ title, hashFor, value, m, list, d, facts, row0 }) {
  return [
    crumbs([{ text: title, href: hashFor.root }, { text: value }]),
    el(
      "div",
      { class: "head" },
      el("span", { class: "badge" }, title),
      el("div", null, el("h1", null, value), el("p", { class: "sub" }, titleOf(m))),
      el(
        "div",
        { class: "kpis" },
        el("div", null, el("b", null, list.length), term("referenced_by")),
      ),
    ),
    d.rows.length > 1
      ? el(
          "p",
          { class: "note" },
          `この名前の行が ${d.total} 件ある (${term("source")} などが違う)。${term("referenced_by")} と ${term("call_path")} は、全部の行を合わせたもの。行ごとの中身は下の表で見る`,
        )
      : el(
          "dl",
          { class: "facts" },
          facts.flatMap((c) =>
            row0[c] != null && row0[c] !== ""
              ? [el("dt", null, labelOf(m, c)), el("dd", null, linkValue(row0[c], m, c))]
              : [],
          ),
        ),
  ];
}

function appendSubjectMembers({ list, parts, title2, m, pane, routable, target, d }) {
  if (!list.length)
    parts.push(
      el(
        "section",
        { class: "card" },
        title2,
        emptyMsg(
          m.keys.members
            ? "無し"
            : `この表は ${term("entry")} の列 (keys.members) を宣言していない`,
        ),
      ),
    );
  else {
    const t = pickTable({
      label: term("referenced_by"),
      rows: list,
      line: (p) => lineOf(p),
      kind: (p) => entryLabel(p, segs(p).length),
      onPick: (p) =>
        pane.replaceChildren(
          routable
            ? routePanel(p, target, {
                link: { href: hEntry(p), text: `この ${term("entry")} を開く` },
              })
            : el(
                "p",
                { class: "note" },
                `この ${term("external")} は相手が特定できていないので、ここからは ${term("call_path")} を引けない。`,
                el("a", { href: hEntry(p) }, `${term("entry")} のページ`),
                `の「${term("dependencies")}」から辿る`,
              ),
        ),
      cols: [
        { label: term("kind"), cls: "kind", cell: (p) => entryLabel(p, segs(p).length) },
        { label: term("entry"), cls: "path", cell: (p) => el("a", { href: hEntry(p) }, p) },
      ],
    });
    parts.push(
      el(
        "div",
        { class: "split" },
        el(
          "section",
          null,
          title2,
          t.el,
          d.total > d.rows.length
            ? el(
                "p",
                { class: "note" },
                `行が ${d.total} 件あり、先頭 ${d.rows.length} 件から集めた。全部は下の表で`,
              )
            : null,
        ),
        pane,
      ),
    );
    t.pick(0);
  }
}

function subjectMembers(m, d) {
  const members = new Set();
  if (m.keys.members)
    for (const r of d.rows)
      for (const p of String(r[m.keys.members] || "").split(", ")) if (p) members.add(p);
  return members;
}
