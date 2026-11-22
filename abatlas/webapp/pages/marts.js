// 画面: 集計表 (API / MCP) の一覧と 1 表 (#/marts、#/mart/<name>)

import { el } from "../lib/dom.js";
import { enc, hMart } from "../lib/hash.js";
import { rows, rowsAll, BIG } from "../lib/api.js";
import { model, titleOf, hintOf } from "../model/catalog.js";
import { term, subjectLabel } from "../model/vocab.js";
import { crumbs } from "../ui/crumbs.js";
import { loading } from "../ui/card.js";
import { gridTable } from "../ui/table.js";
import { render } from "../views/index.js";

const $main = document.getElementById("main");

export function pageMarts() {
  const cols = [
    "title",
    "name",
    "subject",
    "view",
    "level",
    "attach",
    "tags",
    "description",
    "columns",
  ];
  $main.replaceChildren(
    el(
      "div",
      { class: "head" },
      el(
        "div",
        null,
        el("h1", null, `${term("mart")} (API / MCP)`),
        el(
          "p",
          { class: "sub" },
          `${model.catalog.length} 件。MCP の list_marts と同じ一覧。エージェントに頼むときは ${term("name")} (name) で`,
        ),
      ),
    ),
    el(
      "div",
      { class: "scroll" },
      el(
        "table",
        { class: "grid" },
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            cols.map((c) =>
              el(
                "th",
                null,
                {
                  title: term("title"),
                  name: term("name"),
                  subject: term("subject"),
                  view: term("view"),
                  level: "level",
                  attach: "attach",
                  tags: "tags",
                  description: term("description"),
                  columns: term("columns"),
                }[c],
              ),
            ),
          ),
        ),
        el(
          "tbody",
          null,
          [...model.catalog]
            .sort(
              (a, b) =>
                (a.declaration.subject || "z").localeCompare(b.declaration.subject || "z") ||
                a.name.localeCompare(b.name),
            )
            .map((m) =>
              el(
                "tr",
                null,
                el("td", null, el("a", { href: hMart(m.name) }, titleOf(m))),
                el("td", { class: "mono" }, m.name),
                el("td", null, subjectLabel(m.declaration.subject) || "—"),
                el("td", null, m.declaration.view),
                el("td", null, m.declaration.level),
                el("td", null, m.declaration.attach || "any"),
                el("td", null, m.tags.join(", ") || "—"),
                el("td", { class: "text" }, el("span", null, m.description)),
                el("td", { class: "num" }, m.columns.length),
              ),
            ),
        ),
      ),
    ),
  );
}

export function pageMart(name, query) {
  const m = model.catalog.find((x) => x.name === name);
  if (!m) {
    $main.replaceChildren(el("h1", null, `${term("mart")} ${name} は宣言されていない`));
    return;
  }
  const d = m.declaration;
  const inputs = {};
  const preset = Object.fromEntries([...query.entries()]);
  const filters = martFilters(m, inputs, preset, run);
  const extra = Object.entries(preset).filter(([k]) => !(k in inputs)); // __under 等の付いた絞り込み
  const tabular = d.view === "table" || d.view === "matrix";
  const limitSel = el(
    "select",
    {
      disabled: !tabular,
      title: tabular ? null : `図は全行を読む (1 ${term("entry")} 分に絞って読むもの)`,
    },
    [200, 1000, BIG].map((n) =>
      el("option", { value: n, selected: n === (tabular ? 200 : BIG) }, n),
    ),
  );
  const body = el("div");
  const same = el("div", { class: "same-api" });
  async function run() {
    const { f, limit } = martQuery({ extra, inputs, limitSel, name, same });
    body.replaceChildren(loading());
    await renderMartResult({ tabular, m, f, limit, body, d });
  }
  renderMartPage({ m, name, d, extra, preset, filters, limitSel, run, same, body });
  run();
}

function martFilters(m, inputs, preset, run) {
  return el(
    "div",
    { class: "filters" },
    m.columns.map((c) =>
      el(
        "label",
        null,
        c.name,
        (inputs[c.name] = el("input", {
          placeholder: "= 値",
          value: preset[c.name] || "",
          onkeydown: (e) => {
            if (e.key === "Enter") run();
          },
        })),
      ),
    ),
  );
}

function martQuery({ extra, inputs, limitSel, name, same }) {
  const f = Object.fromEntries(extra);
  for (const [c, inp] of Object.entries(inputs)) if (inp.value !== "") f[c] = inp.value;
  const limit = Number(limitSel.value);
  const url = new URL(`marts/${enc(name)}/rows`, location.href);
  for (const [kk, v] of Object.entries(f)) url.searchParams.set(kk, v);
  url.searchParams.set("limit", limit);
  same.replaceChildren(
    "同じものを読む: ",
    el("code", null, `GET ${url.pathname}${url.search}`),
    " / MCP ",
    el(
      "code",
      null,
      `query_mart(name=${JSON.stringify(name)}, filters=${JSON.stringify(f)}, limit=${limit})`,
    ),
  );
  return { f, limit };
}

async function renderMartResult({ tabular, m, f, limit, body, d }) {
  try {
    const data = tabular ? await rows(m, f, limit) : await rowsAll(m, f);
    body.replaceChildren(
      el(
        "p",
        { class: "muted" },
        data.total > data.rows.length
          ? `${data.total} 行 (先頭 ${data.rows.length})`
          : `${data.total} 行`,
      ),
      d.view === "matrix" ? gridTable(m, data.rows, data.columns, {}) : render(m, data, {}),
    );
  } catch (e) {
    body.replaceChildren(el("p", { class: "err" }, e.message));
  }
}

function renderMartPage({ m, name, d, extra, preset, filters, limitSel, run, same, body }) {
  $main.replaceChildren(
    crumbs([{ text: term("mart"), href: "#/marts" }, { text: titleOf(m) }]),
    el(
      "div",
      { class: "head" },
      el(
        "div",
        null,
        el("h1", null, titleOf(m), el("span", { class: "phys" }, name)),
        el("p", { class: "sub" }, m.description),
      ),
    ),
    el("p", { class: "note" }, hintOf(m)),
    martDeclaration(d, m),
    el(
      "details",
      {
        class: "internals",
        open: extra.length || Object.values(preset).some(Boolean) ? true : null,
      },
      el("summary", null, "絞り込み (列 = 値)"),
      filters,
      extra.length
        ? el(
            "p",
            { class: "note" },
            "付いている絞り込み: ",
            extra.map(([kk, v]) => el("code", null, `${kk}=${v} `)),
          )
        : null,
    ),
    el(
      "div",
      { class: "toolbar" },
      el("label", null, "件数 ", limitSel),
      el("button", { class: "primary", onclick: run }, "読む"),
    ),
    same,
    body,
  );
}

function martDeclaration(d, m) {
  return el(
    "details",
    { class: "internals" },
    el("summary", null, "宣言と列 (エージェント向け)"),
    el(
      "div",
      { class: "mart-head" },
      el(
        "dl",
        null,
        el("dt", null, `${term("subject")} / ${term("view")}`),
        el("dd", null, `${subjectLabel(d.subject) || "—"} / ${d.view}`),
        el("dt", null, "origin / level / attach"),
        el("dd", null, `${d.origin} / ${d.level} / ${d.attach || "any"}`),
        el("dt", null, "tags"),
        el("dd", null, m.tags.join(", ") || "—"),
        el("dt", null, "keys"),
        el(
          "dd",
          { class: "mono" },
          Object.entries(m.keys)
            .map(([kk, v]) => `${kk}=${v}`)
            .join("  "),
        ),
        el("dt", null, "列"),
        el("dd", { class: "mono" }, m.columns.map((c) => `${c.name}:${c.type}`).join("  ")),
      ),
    ),
  );
}
