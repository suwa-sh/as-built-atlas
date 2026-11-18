// 画面: 分析の観点 (#/aspects、#/aspects/<組の id か、表の名前>)。入口をまたいで見る表を、答える問いの組 (宣言の topic) ごとにまとめる
//   組の中は、図 (全体の形) → 物ごとのまとめ (宣言の rollup。1 つの物 = 1 行) の順。まとめは、行の一覧にも切り替えられる

import { el } from "../lib/dom.js";
import { hEntry } from "../lib/hash.js";
import { model, titleOf } from "../model/catalog.js";
import { cardFor } from "../ui/card.js";
import { rollupList } from "../ui/rollup.js";
import { panelBody, byView } from "../views/index.js";
import { term, topics } from "../model/vocab.js";

const $main = document.getElementById("main");

export const hAspect = (name) => "#/aspects/" + encodeURIComponent(name);

// 表 1 つ分の節。物ごとのまとめ (宣言の rollup) がある表は、まとめを先に出し、行の一覧に切り替えられる
function aspectCard(m) {
  const ctx = { link: m.keys.path ? (r) => hEntry(r[m.keys.path]) : null };
  if (m.declaration.view !== "table" || !m.declaration.rollup) return cardFor(m, panelBody(m, {}, ctx), {});
  const body = el("div");
  const modes = [["rollup", "まとめ"], ["rows", "行"]];
  const sw = el("div", { class: "seg", role: "group", "aria-label": "見え方" });
  function show(mode) {
    sw.replaceChildren(...modes.map(([id, text]) => el("button", { class: id === mode ? "on" : "", "aria-pressed": String(id === mode), onclick: () => show(id) }, text)));
    body.replaceChildren(mode === "rollup" ? rollupList(m, { base: {}, link: ctx.link }) : panelBody(m, {}, ctx));
  }
  show("rollup");
  const card = cardFor(m, body, {});
  card.querySelector(".card-head").append(sw);
  return card;
}

export async function pageAspects(name) {
  const marts = [...(model.subj.aspect || [])].sort((a, b) => byView(a, b) || titleOf(a).localeCompare(titleOf(b)));
  const head = el("div", { class: "head" }, el("div", null, el("h1", null, term("aspects")),
    el("p", { class: "sub" }, `${term("entry")} をまたいで見る表。知りたいことの組を選ぶ`)));
  if (!marts.length) { $main.replaceChildren(head, el("p", { class: "note" }, "subject: aspect の表が宣言されていない")); return; }
  // 組 (宣言の topic) ごとに分ける。topic の無い表 (プロファイルや分析リポジトリが足した表) は、最後の「そのほか」に出す
  const known = topics().map((t) => ({ ...t, marts: marts.filter((m) => m.declaration.topic === t.id) })).filter((t) => t.marts.length);
  const rest = marts.filter((m) => !known.some((t) => t.marts.includes(m)));
  const tabs = rest.length ? [...known, { id: "other", name: "そのほか", ask: "組を持たない表", marts: rest }] : known;
  // 経路の後ろは、組の id か、表の名前 (前の版の経路)。表の名前なら、その表のある組を開いて、その表まで送る
  const byMart = name ? marts.find((m) => m.name === name) : null;
  const cur = Math.max(0, tabs.findIndex((t) => t.id === name || (byMart && t.marts.includes(byMart))));
  const tabBar = el("div", { class: "tabs", role: "tablist" }, tabs.map((t, i) => el("a", {
    href: hAspect(t.id), role: "tab", class: i === cur ? "on" : "", "aria-selected": String(i === cur), title: t.ask }, t.name, el("span", { class: "n" }, `(${t.marts.length})`))));
  const t = tabs[cur];
  const cards = t.marts.map((m) => [m, aspectCard(m)]);
  const jump = cards.length > 1 ? el("nav", { class: "jump", "aria-label": "この組の表" }, cards.map(([m, card]) => el("button", { class: "link", onclick: () => card.scrollIntoView({ behavior: "smooth", block: "start" }) }, titleOf(m)))) : null;
  $main.replaceChildren(head, tabBar, el("div", { role: "tabpanel" }, el("p", { class: "ask" }, t.ask), jump, cards.map(([, card]) => card)));
  if (byMart) { const hit = cards.find(([m]) => m === byMart); if (hit) hit[1].scrollIntoView({ block: "start" }); }
}
