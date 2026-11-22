// 汎用部品: mart 1 つ分の節と、読み込み中 / 空の表示

import { el } from "../lib/dom.js";
import { titleOf, hintOf, physLink } from "../model/catalog.js";

export function cardFor(m, body, params) {
  return el(
    "section",
    { class: "card" },
    el(
      "div",
      { class: "card-head" },
      el("h2", null, titleOf(m)),
      el("span", { class: "hint" }, hintOf(m)),
      physLink(m, params),
    ),
    body,
  );
}
// 読み込み中は、文字の行の形をした灰色の帯を出す (中身が入る場所が先に分かる)
export function loading() {
  return el(
    "div",
    { role: "status", "aria-label": "読み込み中" },
    el("span", { class: "skel" }),
    el("span", { class: "skel" }),
    el("span", { class: "skel" }),
  );
}
export function emptyMsg(text) {
  return el("p", { class: "empty" }, text);
}
