// 画面: 構成 (#/overview)。層 (プロファイルの layers) を箱にして区分 (layers[].tier) の枠に入れ、分析結果にある実際の呼び出しと読み書きの線でつなぐ。
// 線は層のつながりの表 (view: layers) から引く。図は mart のページと同じ部品 (views/layer-flow.js)。入口ごとの通り道は、入口ごとの経路 (views/route.js) が描く

import { el } from "../lib/dom.js";
import { rows, rowsAll, tree, countOf } from "../lib/api.js";
import { model, levelLabelsText, hierarchyNotes, progressOf, physLink } from "../model/catalog.js";
import { loading } from "../ui/card.js";
import { layerFlow } from "../views/layer-flow.js";
import { sectionExplorer, supportsSection } from "../views/section-explorer.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");

const tableCount = (subject) => {
  const m = (model.subj[subject] || []).find((x) => x.declaration.view === "table");
  return m ? countOf(m, {}).catch(() => null) : Promise.resolve(null);
};

export async function pageOverview(query) {
  const hash = location.hash;
  const pending = loading();
  $main.replaceChildren(pending);
  const { prof, layers, lm, canShow3D, section } = overviewSettings(query);
  const [prog, entries, kinds, frm, flow] = await loadOverviewFigures(lm, section);
  if (!pending.isConnected || location.hash !== hash) return;
  const parts = overviewHeader(prof, layers, entries, prog);
  if (!layers.length) {
    parts.push(
      el(
        "p",
        { class: "note" },
        `この ${term("mart")} には ${term("layer")} の並びが入っていない。「${term("analysis_status")}」の「${term("mart")} を ${term("rebuild")}」で ${term("rebuild")} すると出る`,
      ),
    );
    $main.replaceChildren(...parts);
    return;
  }
  if (prog && prog.done < prog.total)
    parts.push(
      el(
        "p",
        { class: "caveat" },
        `線と数は、${prog.doneLabel} の ${term("entry")} ${prog.done} 件から集めたもの。`,
        el("b", null, `残りの ${prog.total - prog.done} 件`),
        `の ${term("call")} と ${term("data_access")} は、まだ入っていない`,
      ),
    );

  // 図: mart のページと同じ部品 (views/layer-flow.js) で描く
  appendViewSwitch(canShow3D, parts, section);
  appendDiagram({ section, parts, layers, query, flow, lm });

  // 層ごとの役割と、次の層の呼び方
  appendLayerRoles(layers, parts);

  // ここから進む先
  appendOverviewLinks(kinds, frm, parts);
  appendHierarchyNotes(parts);
  $main.replaceChildren(...parts);
}

async function loadOverviewFigures(lm, section) {
  return await Promise.all([
    progressOf(),
    model.entryMart ? countOf(model.entryMart, {}).catch(() => null) : null,
    model.dataMart ? tree(model.dataMart, model.dataMart.keys.col, "/").catch(() => []) : [],
    tableCount("frame"),
    lm ? (section ? rowsAll : rows)(lm, {}).catch(() => null) : null,
  ]);
}

function overviewHeader(prof, layers, entries, prog) {
  return [
    el(
      "div",
      { class: "head" },
      el(
        "div",
        null,
        el("h1", null, term("architecture")),
        el(
          "p",
          { class: "sub" },
          `${term("layer")} と、その間の ${term("call")}、${term("data_access")}`,
          prof.id ? ` · ${term("profile")}: ${prof.id}` : "",
        ),
      ),
      el(
        "div",
        { class: "kpis" },
        layers.length ? el("div", null, el("b", null, layers.length), term("layer")) : null,
        entries != null ? el("div", null, el("b", null, entries), term("entry")) : null,
        prog && prog.total !== entries
          ? el("div", null, el("b", null, prog.total), prog.totalLabel)
          : null,
        prog ? el("div", null, el("b", null, prog.done), prog.doneLabel) : null,
      ),
    ),
  ];
}

function appendViewSwitch(canShow3D, parts, section) {
  if (canShow3D) {
    parts.push(
      el(
        "nav",
        { class: "section-switch", "aria-label": "表示方法" },
        el("a", { href: "#/overview", "aria-current": section ? null : "page" }, "全体図"),
        el("a", { href: "#/overview?view=3d", "aria-current": section ? "page" : null }, "3D"),
      ),
    );
  }
}

function appendDiagram({ section, parts, layers, query, flow, lm }) {
  if (section) {
    parts.push(sectionExplorer(layers, query.get("entry"), flow, query.get("focusTier")));
  } else if (flow && lm) {
    parts.push(
      el(
        "div",
        { class: "card-head" },
        el("h2", null, term("layer_deps")),
        el(
          "span",
          { class: "hint" },
          `線の数字は、コードに書かれている ${term("call")} と ${term("data_access")} の数 (${term("call_sites")})。箱に触れると、つながる線だけ残る`,
        ),
        physLink(lm, {}),
      ),
    );
    parts.push(layerFlow(lm, flow, { list: false }));
  } else {
    parts.push(
      el(
        "p",
        { class: "note" },
        `${term("layer_deps")} の表がまだ無い。「${term("analysis_status")}」の「${term("mart")} を ${term("rebuild")}」で ${term("rebuild")} すると、図が出る`,
      ),
    );
  }
}

function appendLayerRoles(layers, parts) {
  const hasTier = layers.some((t) => t.tier);
  parts.push(el("h2", null, `${term("layer")} ごとの役割`));
  parts.push(
    el(
      "div",
      { class: "scroll" },
      el(
        "table",
        { class: "grid arch-table" },
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            [
              ...(hasTier ? [term("tier")] : []),
              term("layer"),
              "役割",
              "使う技術",
              `次の ${term("layer")} をどう呼ぶか`,
            ].map((h) => el("th", null, h)),
          ),
        ),
        el(
          "tbody",
          null,
          layers.map((t) => layerRow(t, hasTier)),
        ),
      ),
    ),
  );
}

function appendOverviewLinks(kinds, frm, parts) {
  const next = [
    model.subj.entry
      ? el(
          "a",
          { class: "row", href: "#/entries" },
          el("span", { class: "name" }, term("entry")),
          el("span", { class: "meta" }, `分類は ${levelLabelsText()}`),
          el("span"),
        )
      : null,
    model.subj.data
      ? el(
          "a",
          { class: "row", href: "#/data" },
          el("span", { class: "name" }, term("datastore")),
          el(
            "span",
            { class: "meta" },
            `${kinds.reduce((a, c) => a + c.leaves, 0)} 件。${term("referenced_by")} を逆引きする`,
          ),
          el("span"),
        )
      : null,
    model.subj.frame
      ? el(
          "a",
          { class: "row", href: "#/frames" },
          el("span", { class: "name" }, term("shared_frame")),
          el(
            "span",
            { class: "meta" },
            `${frm != null ? frm + " 件。" : ""}2 件以上の ${term("entry")} が通る ${term("frame")}`,
          ),
          el("span"),
        )
      : null,
  ].filter(Boolean);
  if (next.length) parts.push(el("h2", null, "ここから調べる"), el("div", { class: "rows" }, next));
}

function appendHierarchyNotes(parts) {
  const notes = hierarchyNotes();
  if (notes.length)
    parts.push(
      el("h2", null, `${term("entry")} の名前の読み方`),
      ...notes.map((t) => el("p", { class: "note" }, t)),
    );
}

function overviewSettings(query) {
  const prof = model.meta.profile || {};
  const layers = (Array.isArray(prof.layers) ? prof.layers : []).filter((t) => t && t.id);
  const lm = model.layerMart;
  const canShow3D = Boolean(lm) || supportsSection();
  const section = canShow3D && query.get("view") === "3d";
  return { prof, layers, lm, canShow3D, section };
}

function layerRow(t, hasTier) {
  return el(
    "tr",
    null,
    hasTier ? el("td", null, t.tier || "") : null,
    el("td", null, el("b", null, t.id)),
    el("td", { class: "text" }, t.label || ""),
    el("td", { class: "text" }, (t.stack || []).join("、")),
    el(
      "td",
      { class: "text" },
      t.invokes_next ||
        (t.role === "boundary" ? `ここで終わる。この先は ${term("data_access")} の相手` : ""),
    ),
  );
}
