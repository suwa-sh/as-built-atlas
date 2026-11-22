// 汎用部品: 一覧 (検索 / 絞り込み / 並べ替え / 読み継ぎ) と表

import { el, fmt, isNum, isPathLike } from "../lib/dom.js";
import { enc, hEntry } from "../lib/hash.js";
import { api, countOf, PAGE } from "../lib/api.js";
import { showCols, labelOf, relPath } from "../model/catalog.js";
import { loading, emptyMsg } from "./card.js";
import { linkValue } from "./link.js";
import { term } from "../model/vocab.js";

// 一覧の部品: 検索 / 絞り込み (宣言の filters) / 並べ替え / 50 件ずつ。サーバ側で絞る
export function listTable(m, opts) {
  const o = { base: {}, pageSize: PAGE, ...opts };
  const { searchCol, cols } = listColumns(o, m);
  const state = { q: "", chip: null, order: o.order || null, total: 0, acc: [] }; // acc = ここまでに読んだ行 (offset で読み継ぐ)
  const filters = m.declaration.filters || [];
  const search = el("input", {
    type: "search",
    placeholder: `${labelOf(m, searchCol)} で探す`,
    oninput: () => {
      state.q = search.value.trim();
      load();
    },
  });
  const chips = el("div", { class: "chips" });
  const count = el("span", { class: "count" });
  const body = el("div");
  const pager = el("div", { class: "pager" });
  const toolbar = el("div", { class: "toolbar" }, search, chips, count);
  const box = el("div", { class: "list" }, toolbar, body, pager);
  function params() {
    return listParameters(o, state, searchCol, filters);
  }
  async function drawChips() {
    await renderFilterChips({ m, o, state, searchCol, filters, chips, load });
  }
  let seq = 0;
  async function load(more) {
    const my = ++seq;
    if (!more) {
      state.acc = [];
      body.replaceChildren(loading());
      drawChips();
    }
    try {
      const data = await api(`marts/${enc(m.name)}/rows`, {
        ...params(),
        limit: o.pageSize,
        offset: state.acc.length,
      });
      if (my !== seq) return;
      state.total = data.total;
      state.acc.push(...data.rows);
      count.textContent = `${data.total} 件`;
      if (!state.acc.length) {
        body.replaceChildren(emptyMsg(o.empty || "該当する行が無い"));
        pager.replaceChildren();
        return;
      }
      renderSortedRows({ body, m, state, cols, load, o });
      renderPager({ data, state, pager, load, o });
    } catch (e) {
      if (my === seq) body.replaceChildren(el("p", { class: "err" }, e.message));
    }
  }
  load();
  return box;
}
function listColumns(o, m) {
  const cols =
    o.cols ||
    showCols(
      m,
      (m.columns || []).map((c) => c.name),
    );
  const searchCol = o.searchCol || m.keys.label || m.keys.path || m.keys.id;
  return { searchCol, cols };
}

async function renderFilterChips({ m, o, state, searchCol, filters, chips, load }) {
  const all = await countOf(m, {
    ...o.base,
    ...(state.q ? { [`${searchCol}__contains`]: state.q } : {}),
  }).catch(() => null);
  const counts = await Promise.all(
    filters.map((f) =>
      countOf(m, {
        ...o.base,
        ...(state.q ? { [`${searchCol}__contains`]: state.q } : {}),
        ...f.where,
      }).catch(() => null),
    ),
  );
  chips.replaceChildren(
    el(
      "button",
      {
        class: `chip${state.chip == null ? " on" : ""}`,
        onclick: () => {
          state.chip = null;
          load();
        },
      },
      "すべて",
      all != null ? ` ${all}` : "",
    ),
    ...filters.map((f, i) =>
      el(
        "button",
        {
          class: `chip${state.chip === i ? " on" : ""}`,
          onclick: () => {
            state.chip = state.chip === i ? null : i;
            load();
          },
        },
        f.label,
        counts[i] != null ? ` ${counts[i]}` : "",
      ),
    ),
  );
}

function renderSortedRows({ body, m, state, cols, load, o }) {
  body.replaceChildren(
    gridTable(m, state.acc, cols, {
      order: state.order,
      onOrder: (col) => {
        state.order = state.order === col ? "-" + col : col;
        load();
      },
      link: o.link,
      rel: o.rel,
    }),
  );
}

function renderPager({ data, state, pager, load, o }) {
  const rest = data.total - state.acc.length;
  pager.replaceChildren(
    el("span", null, `${state.acc.length} 件を表示`, rest > 0 ? ` · 残り ${rest} 件` : ""),
    ...(rest > 0
      ? [
          el(
            "button",
            { onclick: () => load(true) },
            `さらに ${Math.min(o.pageSize, rest)} 件を表示`,
          ),
        ]
      : []),
  );
}

// 表 (宣言の labels で見出し、階層パスはリンク、長い文字は 3 行で畳む)
export function gridTable(m, list, cols, opts) {
  const o = opts || {};
  const { long, numeric, boolish } = classifyColumns(cols, list);
  const thead = gridHead(cols, o, m);
  const tbody = gridBody({ list, cols, o, long, m, numeric, boolish });
  return el("div", { class: "scroll" }, el("table", { class: "grid" }, thead, tbody));
}
function classifyColumns(cols, list) {
  const numeric = Object.fromEntries(
    cols.map((c) => [c, list.every((r) => r[c] == null || isNum(r[c]))]),
  );
  const boolish = Object.fromEntries(
    cols.map((c) => [c, list.every((r) => r[c] == null || typeof r[c] === "boolean")]),
  );
  const long = Object.fromEntries(
    cols.map((c) => [c, list.some((r) => typeof r[c] === "string" && r[c].length > 60)]),
  );
  return { long, numeric, boolish };
}

function gridHead(cols, o, m) {
  return el(
    "thead",
    null,
    el(
      "tr",
      null,
      cols.map((c) =>
        el(
          "th",
          {
            onclick: o.onOrder ? () => o.onOrder(c) : null,
            title: o.onOrder ? "押すと並べ替え" : null,
          },
          labelOf(m, c),
          o.order === c
            ? el("span", { class: "dir" }, "▲")
            : o.order === "-" + c
              ? el("span", { class: "dir" }, "▼")
              : null,
        ),
      ),
      o.link ? el("th", null, "") : null,
    ),
  );
}

function gridBody({ list, cols, o, long, m, numeric, boolish }) {
  return el(
    "tbody",
    null,
    list.map((r) =>
      el(
        "tr",
        null,
        cols.map((c) => {
          const content = gridValue({ r, c, o, long, m });
          return el(
            "td",
            { class: numeric[c] ? "num" : boolish[c] ? "bool" : long[c] ? "text" : null },
            content,
          );
        }),
        o.link ? el("td", null, el("a", { class: "open", href: o.link(r) }, "開く")) : null,
      ),
    ),
  );
}

// 選べる表: 行を 1 つ選ぶと onPick(行) を呼ぶ (クリック、Enter / スペース、上下の矢印キー)。行頭に路線の色の帯 (line(行) が返すクラス) を出す。
// cols は [{ label, cls, cell(行) }]。返すのは { el, pick(番号) }
export function pickTable(o) {
  const trs = [];
  let cur = -1;
  // Tab で止まるのは選んだ行と、その行の中のリンクだけ (行が多くても Tab の回数が増えない)。ほかの行へは上下の矢印で移る
  const setTab = (tr, v) => {
    tr.tabIndex = v;
    for (const a of tr.querySelectorAll("a, button")) a.tabIndex = v;
  };
  function pick(i, focus) {
    if (i < 0 || i >= o.rows.length) return;
    if (cur >= 0) {
      trs[cur].setAttribute("aria-selected", "false");
      setTab(trs[cur], -1);
    }
    cur = i;
    trs[i].setAttribute("aria-selected", "true");
    setTab(trs[i], 0);
    if (focus) trs[i].focus();
    if (i !== pick.last) {
      pick.last = i;
      o.onPick(o.rows[i]);
    }
  }
  const tbody = selectionBody(o, pick, setTab, trs);
  const table = el(
    "table",
    { class: "grid pick", role: "grid", "aria-label": o.label },
    el(
      "thead",
      null,
      el(
        "tr",
        null,
        o.line ? el("th", { class: "line" }) : null,
        o.cols.map((c) => el("th", { class: c.cls === "num" ? "num" : null }, c.label)),
      ),
    ),
    tbody,
  );
  // 行頭の帯の色の意味 (入口の種類) は、この表の下に出す。色を使う場所のそばにだけ置く
  const legend = selectionLegend(o);
  return { el: el("div", null, el("div", { class: "scroll" }, table), legend), pick };
}

function selectionBody(o, pick, setTab, trs) {
  return el(
    "tbody",
    null,
    o.rows.map((r, i) => {
      const tr = el(
        "tr",
        {
          tabindex: i === 0 ? "0" : "-1",
          "aria-selected": "false",
          class: o.line ? o.line(r) : null,
          onclick: (ev) => {
            if (!ev.target.closest("a, button")) pick(i);
          },
          onkeydown: (ev) => {
            handleRowKey(ev, tr, pick, i);
          },
        },
        o.line ? el("td", { class: "line" }) : null,
        o.cols.map((c) => el("td", { class: c.cls || null }, c.cell(r))),
      );
      setTab(tr, i === 0 ? 0 : -1);
      trs.push(tr);
      return tr;
    }),
  );
}

function selectionLegend(o) {
  const kinds = new Map();
  if (o.line && o.kind)
    for (const r of o.rows) {
      const k = o.kind(r);
      if (k && !kinds.has(k)) kinds.set(k, o.line(r));
    }
  const legend = kinds.size
    ? el(
        "ul",
        { class: "line-legend" },
        el(
          "li",
          { class: "cap" },
          `行頭と ${term("call_path")} の線の色は、${term("entry")} の ${term("kind")}`,
        ),
        [...kinds].map(([label, cls]) => el("li", { class: cls }, el("i"), label)),
      )
    : null;
  return legend;
}

function listParameters(o, state, searchCol, filters) {
  const p = { ...o.base };
  if (state.q) p[`${searchCol}__contains`] = state.q;
  if (state.chip != null) Object.assign(p, filters[state.chip].where);
  if (state.order) p.order = state.order;
  return p;
}

function gridValue({ r, c, o, long, m }) {
  const v = r[c];
  let content;
  if (o.rel && c === o.rel.col && isPathLike(v))
    content = el("a", { href: hEntry(v), title: v }, relPath(v, o.rel.root));
  else if (v === false)
    content = el("span", { class: "muted" }, fmt(v)); // いいえは灰にして、はいを拾いやすくする
  else if (long[c]) content = el("span", { title: v == null ? null : String(v) }, fmt(v));
  else content = linkValue(v, m, c);
  return content;
}

function handleRowKey(ev, tr, pick, i) {
  if ((ev.key === "Enter" || ev.key === " ") && ev.target === tr) {
    ev.preventDefault();
    pick(i);
  } // リンクの上の Enter はリンクを開く
  else if (ev.key === "ArrowDown") {
    ev.preventDefault();
    pick(i + 1, true);
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();
    pick(i - 1, true);
  }
}
