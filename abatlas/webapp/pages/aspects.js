// 画面: 分析の観点 (#/aspects、#/aspects/<表の名前>)。列・つながり・権限・条件・設定・ルールなどの表を、タブで 1 つずつ見せる

import { el } from "../lib/dom.js";
import { hEntry } from "../lib/hash.js";
import { countOf } from "../lib/api.js";
import { model, titleOf } from "../model/catalog.js";
import { cardFor } from "../ui/card.js";
import { panelBody, byView } from "../views/index.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");

export const hAspect = (name) => "#/aspects/" + encodeURIComponent(name);

export async function pageAspects(name) {
  const marts = [...(model.subj.aspect || [])].sort((a, b) => byView(a, b) || titleOf(a).localeCompare(titleOf(b)));
  const head = el("div", { class: "head" }, el("div", null, el("h1", null, term("aspects")),
    el("p", { class: "sub" }, `${term("entry")} をまたいで見る表。件数が 0 の表は、該当が無いか、まだ分析されていない`)));
  if (!marts.length) { $main.replaceChildren(head, el("p", { class: "note" }, "subject: aspect の表が宣言されていない")); return; }
  const cur = Math.max(0, marts.findIndex((m) => m.name === name));
  const counts = await Promise.all(marts.map((m) => countOf(m, {}).catch(() => null)));
  if (!location.hash.startsWith("#/aspects")) return; // 件数を待つ間に、別のページへ移っていたら、描かない
  // タブはリンクにする (どの表を見ているかを、URL で渡せる)
  const tabBar = el("div", { class: "tabs", role: "tablist" }, marts.map((m, i) => el("a", {
    href: hAspect(m.name), role: "tab", class: i === cur ? "on" : "", "aria-selected": String(i === cur) },
    titleOf(m), counts[i] != null ? el("span", { class: "n" }, `(${counts[i]})`) : null)));
  const m = marts[cur];
  const body = el("div", { role: "tabpanel" }, cardFor(m, panelBody(m, {}, { link: m.keys.path ? (r) => hEntry(r[m.keys.path]) : null }), {}));
  $main.replaceChildren(head, tabBar, body);
}
