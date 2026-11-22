// 画面: datastore の最初のページ (#/data) と、種類ごとの読み書きの表 (#/access/<kind>/<入口の節>)。行も列も開閉。
// datastore はまず表で見渡し、列の名前から個々の datastore (それを使う入口と経路) へ降りる

import { el } from "../lib/dom.js";
import { hEntries, hData, hAccess } from "../lib/hash.js";
import { tree } from "../lib/api.js";
import {
  model,
  physLink,
  levelLabelsText,
  kindOf,
  kindsOf,
  dataLevelsText,
  opsText,
} from "../model/catalog.js";
import { crumbs } from "../ui/crumbs.js";
import { loading } from "../ui/card.js";
import { pivotTable } from "../views/matrix.js";
import { pageData } from "./data.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");

// kind が無いとき (#/data) は、使われている最初の種類を開く
export async function pageAccess(kind, rowRoot, query) {
  if (!model.dataMart) {
    pageData();
    return;
  }
  const k = model.dataMart.keys;
  $main.replaceChildren(loading());
  const used = await tree(model.dataMart, k.col, "/", {}).catch(() => []);
  const by = Object.fromEntries(used.map((c) => [c.name, c]));
  const kinds = kindsOf();
  const first = !kind;
  if (first) kind = (kinds.find((x) => by[x.id]) || kinds[0] || { id: "" }).id;
  const kindSpec = kindOf(kind);
  const colRoot = query.get("col") || "/" + kind;
  renderAccessMatrix({ first, kindSpec, rowRoot, kind, k, kinds, by, colRoot });
}

function renderAccessMatrix({ first, kindSpec, rowRoot, kind, k, kinds, by, colRoot }) {
  $main.replaceChildren(
    ...[
      first
        ? null
        : crumbs([{ text: term("datastore"), href: "#/data" }, { text: kindSpec.label }]),
      el(
        "div",
        { class: "head" },
        el(
          "div",
          null,
          el("h1", null, first ? term("datastore") : `${kindSpec.label} の ${term("data_access")}`),
          el(
            "p",
            { class: "sub" },
            `行 = ${term("entry")} (${levelLabelsText()})`,
            rowRoot !== "/"
              ? [" の ", el("a", { href: hEntries(rowRoot) }, rowRoot), " 配下"]
              : null,
            ` · 列 = ${kindSpec.label} (${dataLevelsText(kind)}) · 操作 ${opsText(kind)}`,
          ),
        ),
        el(
          "div",
          { class: "actions" },
          el("a", { href: hData(kind) }, `${kindSpec.label} を階層から探す`),
          physLink(model.dataMart, { [k.kind]: kind }),
        ),
      ),
      // 種類の切り替え (使われていない種類は押せない)
      kindTabs(kinds, by, kind, rowRoot),
      pivotTable(model.dataMart, { kind, rowRoot, colRoot }),
    ].filter(Boolean),
  );
}

function kindTabs(kinds, by, kind, rowRoot) {
  return kinds.length > 1
    ? el(
        "div",
        { class: "tabs" },
        kinds.map((x) =>
          el(
            "button",
            {
              class: x.id === kind ? "on" : null,
              disabled: by[x.id] ? null : "",
              title: by[x.id] ? null : "まだ無い",
              onclick: () => {
                location.hash = hAccess(x.id, rowRoot);
              },
            },
            x.label,
            el("span", { class: "n" }, by[x.id] ? by[x.id].leaves : 0),
          ),
        ),
      )
    : null;
}
