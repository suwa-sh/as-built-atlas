// 画面: データ (#/data/<kind>/<path>)。データから「触る入口」を逆引きし、選んだ入口の経路を右に描く

import { el, fmt, isNum } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { hEntry, hData, hAccess, hMart } from "../lib/hash.js";
import { rows, tree, countOf } from "../lib/api.js";
import {
  model,
  physLink,
  kindOf,
  dataLevelLabel,
  dataLevelsText,
  entryLabel,
  lineOf,
  splitOps,
  labelOf,
  progressOf,
} from "../model/catalog.js";
import { pathCrumbs } from "../ui/crumbs.js";
import { cardFor, loading, emptyMsg } from "../ui/card.js";
import { pickTable } from "../ui/table.js";
import { render, panelBody } from "../views/index.js";
import { routePanel } from "../views/route.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");
const CAP = 2000; // 触る入口を集めるために読む行の上限

// datastore の階層の元になる表が無いときの代わりのページ (あるときは pages/access.js の表が最初のページ)
export async function pageData() {
  if (!model.dataMart) {
    $main.replaceChildren(
      el("div", { class: "head" }, el("div", null, el("h1", null, term("datastore")))),
      el(
        "p",
        { class: "note" },
        `${term("datastore")} の階層の元になる表 (subject: data の matrix で keys.kind を持つもの) が宣言されていないので、${term("kind")} ごとの階層を辿れない。宣言されている ${term("datastore")} の表は下に出す`,
      ),
      ...(model.subj.data || []).map((m) => cardFor(m, panelBody(m, {}, {}), {})),
    );
  }
}

// 配下の読み書きの行を入口ごとにまとめる (操作は和集合、数の列は和、不明はどれかが真なら真)
function byEntry(list, k, numCols) {
  const m = new Map();
  for (const r of list) {
    const p = String(r[k.row]);
    if (!m.has(p))
      m.set(p, {
        path: p,
        ops: "",
        flag: false,
        nums: Object.fromEntries(numCols.map((c) => [c, 0])),
      });
    accumulateOperations({ m, p, r, k, numCols });
  }
  return [...m.values()];
}

export async function pageDataKind(kind, path) {
  if (!model.dataMart) {
    pageData();
    return;
  }
  $main.replaceChildren(loading());
  const k = model.dataMart.keys;
  const kindSpec = kindOf(kind);
  const full = "/" + kind + (path === "/" ? "" : path); // 列の実際の値 (/種類/…)
  const base = { [k.kind]: kind };
  const [kids, selfRows, touch, prog] = await fetchDataNode(k, full, base, path);
  const depth = path === "/" ? 0 : segs(path).length;
  const isLeaf = selfRows.total > 0 && kids.length === 0;
  const name = path === "/" ? kindSpec.label : segs(path).slice(-1)[0];
  const { entries, numCols } = collectEntryOperations(k, touch, kind);
  const partial = touch.total > touch.rows.length; // 上限までしか読めていない (数字は下限)
  const parts = dataHeader({
    path,
    kind,
    kindSpec,
    name,
    depth,
    isLeaf,
    kids,
    entries,
    partial,
    numCols,
    full,
    prog,
  });
  appendDataChildren({ kids, parts, kind, depth, path });
  // 触る入口 (左) と、選んだ入口の経路 (右)
  const pane = el("div", { class: "pane" });
  const title = el(
    "div",
    { class: "card-head" },
    el("h2", null, isLeaf ? term("referenced_by") : `${term("referenced_by")} (配下のどれか)`),
    el(
      "span",
      { class: "hint" },
      isLeaf
        ? `ここを変えると影響を受ける ${term("entry")}。行を選ぶと ${term("call_path")} が出る`
        : `この段を変える (移行・ホストの変更) ときに影響を受ける ${term("entry")}`,
    ),
    physLink(model.dataMart, { ...base, [`${k.col}__under`]: full }),
  );
  appendReferencingEntries({ entries, parts, title, pane, full, name, numCols, k, partial, touch });
  // このデータを含む流れ
  appendDataFlow(parts, full);
  $main.replaceChildren(...parts.filter(Boolean));
}

async function fetchDataNode(k, full, base, path) {
  return await Promise.all([
    tree(model.dataMart, k.col, full, { ...base, flag: k.flag, distinct: k.row }),
    path === "/"
      ? Promise.resolve({ total: 0 })
      : rows(model.dataMart, { ...base, [k.col]: full }, 1),
    rows(model.dataMart, { ...base, [`${k.col}__under`]: full }, CAP),
    progressOf(),
  ]);
}

function collectEntryOperations(k, touch, kind) {
  const numCols = numericDataColumns(k, touch);
  const entries = byEntry(touch.rows, k, numCols)
    .map((e) => ({ ...e, ...splitOps(kind, e.ops) }))
    .sort(
      (a, b) =>
        b.write.length - a.write.length ||
        (numCols[0] ? b.nums[numCols[0]] - a.nums[numCols[0]] : 0) ||
        a.path.localeCompare(b.path),
    );
  return { entries, numCols };
}

function dataHeader({
  path,
  kind,
  kindSpec,
  name,
  depth,
  isLeaf,
  kids,
  entries,
  partial,
  numCols,
  full,
  prog,
}) {
  const parts = [
    pathCrumbs(path, (p) => hData(kind, p), term("datastore"), "#/data"),
    el(
      "div",
      { class: "head" },
      el("span", { class: "badge" }, kindSpec.label),
      el("div", null, el("h1", null, name), dataSubtitle({ depth, kind, kindSpec, isLeaf, kids })),
      dataIndicators(entries, partial, numCols),
      el(
        "div",
        { class: "actions" },
        el(
          "a",
          { href: hAccess(kind, "/") + (path === "/" ? "" : "?col=" + encodeURIComponent(full)) },
          `${term("access_matrix")} を開く`,
        ),
      ),
    ),
  ];
  if (prog && prog.done < prog.total)
    parts.push(
      el(
        "p",
        { class: "caveat" },
        `${prog.doneLabel} の ${term("entry")} は ${prog.total} 件中 ${prog.done} 件。`,
        el("b", null, `残りの ${prog.total - prog.done} 件`),
        "がここを使うかどうかは、まだ分からない",
      ),
    );
  return parts;
}

function appendDataChildren({ kids, parts, kind, depth, path }) {
  if (kids.length) {
    parts.push(el("h2", null, `配下の${dataLevelLabel(kind, depth + 1)} (${kids.length})`));
    parts.push(
      el(
        "div",
        { class: "treelist" },
        kids.map((c) =>
          el(
            "a",
            {
              class: `trow${c.is_leaf ? " leaf" : ""}`,
              href: hData(kind, (path === "/" ? "" : path) + "/" + c.name),
            },
            el(
              "span",
              { class: "lbl" },
              el("b", null, c.name),
              el(
                "span",
                { class: "cap" },
                c.is_leaf
                  ? dataLevelLabel(kind, depth + 1, true)
                  : `${dataLevelLabel(kind, depth + 1, false)} · ${c.leaves} 件`,
              ),
            ),
            el("span", { class: "n" }, `${term("referenced_by")} ${c.distinct}`),
            c.has_flag ? el("span", { class: "tag dash" }, term("has_unknown")) : el("span"),
          ),
        ),
      ),
    );
  }
}

function appendReferencingEntries({
  entries,
  parts,
  title,
  pane,
  full,
  name,
  numCols,
  k,
  partial,
  touch,
}) {
  if (!entries.length) {
    parts.push(
      el(
        "section",
        { class: "card" },
        title,
        emptyMsg(`${term("analyzed")} の ${term("entry")} には、ここを使うものが無い`),
      ),
    );
  } else {
    const opTags = (labels, w) =>
      labels.length
        ? el(
            "span",
            { class: "ops" },
            labels.map((t) => el("span", { class: `op${w ? " w" : ""}` }, t)),
          )
        : "";
    const t = pickTable({
      label: term("referenced_by"),
      rows: entries,
      line: (e) => lineOf(e.path),
      kind: (e) => entryLabel(e.path, segs(e.path).length),
      onPick: (e) =>
        pane.replaceChildren(
          routePanel(
            e.path,
            { kind: "data", path: full, label: name },
            { link: { href: hEntry(e.path), text: `この ${term("entry")} を開く` } },
          ),
        ),
      cols: [
        { label: term("kind"), cls: "kind", cell: (e) => entryLabel(e.path, segs(e.path).length) },
        {
          label: term("entry"),
          cls: "path",
          cell: (e) => el("a", { href: hEntry(e.path) }, e.path),
        },
        { label: term("read"), cell: (e) => opTags(e.read, false) },
        { label: term("write"), cell: (e) => opTags(e.write, true) },
        ...numCols.map((c) => ({
          label: labelOf(model.dataMart, c),
          cls: "num",
          cell: (e) => fmt(e.nums[c]),
        })),
        ...(k.flag
          ? [
              {
                label: "",
                cell: (e) => (e.flag ? el("span", { class: "tag dash" }, term("has_unknown")) : ""),
              },
            ]
          : []),
      ],
    });
    parts.push(
      el(
        "div",
        { class: "split" },
        el(
          "section",
          null,
          title,
          partial
            ? el(
                "p",
                { class: "caveat" },
                el(
                  "b",
                  null,
                  `${term("data_access")} の行が ${touch.total} 件あり、先頭 ${touch.rows.length} 件から集めた。`,
                ),
                `ここに出ていない ${term("entry")} がある。配下の段を開いて絞るか、「${term("mart")} で見る」で全部を見る`,
              )
            : null,
          t.el,
        ),
        pane,
      ),
    );
    t.pick(0);
  }
}

function appendDataFlow(parts, full) {
  if (model.graphMart) {
    const gk = model.graphMart.keys;
    const flow = el(
      "section",
      { class: "card" },
      el(
        "div",
        { class: "card-head" },
        el("h2", null, `この ${term("datastore")} を含む流れ`),
        el(
          "span",
          { class: "hint" },
          `左が${term("write")} する ${term("entry")}、右が${term("read")} する ${term("entry")}`,
        ),
        physLink(model.graphMart, {}),
      ),
      loading(),
    );
    parts.push(flow);
    const FCAP = 200; // 図に描く辺の上限 (両方向の合計。それ以上は一覧で見る)。両方向に半分ずつ配り、片方が少なければ残りをもう片方へ
    Promise.all([
      rows(model.graphMart, { [`${gk.from}__under`]: full }, FCAP),
      rows(model.graphMart, { [`${gk.to}__under`]: full }, FCAP),
    ])
      .then(([a, b]) => {
        const half = Math.floor(FCAP / 2);
        const nA = Math.min(a.rows.length, Math.max(half, FCAP - b.rows.length));
        const nB = Math.min(b.rows.length, FCAP - nA);
        const data = { ...a, rows: [...a.rows.slice(0, nA), ...b.rows.slice(0, nB)] };
        const total = a.total + b.total;
        flow.replaceChildren(
          ...[
            flow.firstChild,
            total > data.rows.length
              ? el(
                  "p",
                  { class: "note" },
                  `矢印が ${total} 本ある。図は出る矢印 ${nA} 本と入る矢印 ${nB} 本だけ。全部は一覧で: `,
                  el(
                    "a",
                    { href: hMart(model.graphMart.name, { [`${gk.from}__under`]: full }) },
                    `この ${term("datastore")} から出る矢印 (${a.total})`,
                  ),
                  " / ",
                  el(
                    "a",
                    { href: hMart(model.graphMart.name, { [`${gk.to}__under`]: full }) },
                    `この ${term("datastore")} へ入る矢印 (${b.total})`,
                  ),
                )
              : null,
            data.rows.length ? render(model.graphMart, data, {}) : emptyMsg("流れが無い"),
          ].filter(Boolean),
        );
      })
      .catch((e) => flow.append(el("p", { class: "err" }, e.message)));
  }
}

function accumulateOperations({ m, p, r, k, numCols }) {
  const e = m.get(p);
  e.ops += String(r[k.value] || "");
  if (k.flag && r[k.flag]) e.flag = true;
  for (const c of numCols) e.nums[c] += Number(r[c]) || 0;
}

function numericDataColumns(k, touch) {
  const numCols = (model.dataMart.columns || [])
    .map((c) => c.name)
    .filter(
      (c) =>
        !Object.values(k).includes(c) &&
        touch.rows.length &&
        touch.rows.every((r) => r[c] == null || isNum(r[c])) &&
        !/^level\d$/.test(c),
    );
  return numCols;
}

function dataSubtitle({ depth, kind, kindSpec, isLeaf, kids }) {
  return el(
    "p",
    { class: "sub" },
    depth
      ? `${kindSpec.label} の ${isLeaf && !kindSpec.repeat ? (kindSpec.levels || []).slice(-1)[0] || "" : dataLevelLabel(kind, depth, isLeaf)}`
      : dataLevelsText(kind),
    isLeaf ? "" : ` · 配下の ${term("datastore")} ${kids.reduce((a, c) => a + c.leaves, 0)} 件`,
  );
}

function dataIndicators(entries, partial, numCols) {
  return el(
    "div",
    { class: "kpis" },
    el("div", null, el("b", null, entries.length, partial ? " 以上" : ""), term("referenced_by")),
    el(
      "div",
      null,
      el("b", null, entries.filter((e) => e.write.length).length, partial ? " 以上" : ""),
      `${term("write")} する ${term("entry")}`,
    ),
    ...numCols.slice(0, 1).map((c) =>
      el(
        "div",
        null,
        el(
          "b",
          null,
          entries.reduce((a, e) => a + e.nums[c], 0),
          partial ? " 以上" : "",
        ),
        labelOf(model.dataMart, c),
      ),
    ),
  );
}
