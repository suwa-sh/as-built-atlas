// 表示の種類: 行列 (view: matrix)。行も列も開閉できるクロス表 (読み書きの表のページで使う)

import { el, fmt } from "../lib/dom.js";
import { segs, joinPath } from "../lib/path.js";
import { hEntries, hEntry, hData } from "../lib/hash.js";
import { tree, pivot } from "../lib/api.js";
import { kindOf, dataLevelLabel } from "../model/catalog.js";
import { loading } from "../ui/card.js";
import { listTable } from "../ui/table.js";
import { toast } from "../ui/toast.js";
import { term } from "../model/vocab.js";

const $ctx = document.getElementById("ctx");

export function pivotTable(m, opts) {
  return new PivotTable().mount(m, opts);
}

class PivotTable {
  mount(m, opts) {
    this.m = m;
    this.k = this.m.keys;
    this.kind = opts.kind;
    this.kindSpec = kindOf(this.kind);
    this.rowRoot = opts.rowRoot || "/";
    this.colRoot = opts.colRoot || "/" + this.kind;
    this.st = {
      rowOpen: new Set([this.rowRoot]),
      colOpen: new Set([this.colRoot]),
      touched: true,
      unknownOnly: false,
      q: "",
      swap: false,
    };
    const base = { [this.k.kind]: this.kind };
    const rowBase = () => (this.rowRoot !== "/" ? { [`${this.k.row}__under`]: this.rowRoot } : {});
    // 木 (行・列の見出し) と pivot (セルの値) に同じ条件を渡す。表示中の条件に無い行をセルに合算しない
    this.cellFilter = () => ({
      ...base,
      ...(this.st.unknownOnly && this.k.flag ? { [this.k.flag]: "true" } : {}),
      ...(this.st.q ? { [`${this.k.col}__contains`]: this.st.q } : {}),
    });
    this.colFilter = () => ({ ...this.cellFilter(), ...(this.st.touched ? rowBase() : {}) });
    this.rowFilter = () => ({ ...this.cellFilter() });
    this.wrap = el("div", { class: "pivot-wrap" }, loading());
    this.status = el("span", { class: "count" });
    this.detail = el("div");
    this.createToolbar();
    const legend = el(
      "div",
      { class: "legend" },
      "畳んだ行・列の値はサーバで集計した配下の和 · ",
      el("span", { class: "box flag" }),
      `点線 = ${term("unknown")} を含む · 列の名前を押すと、その ${term("datastore")} の ${term("referenced_by")} と ${term("call_path")} · セルを押すと内訳 · ▸ ▾ で開閉、見出しの右クリックで配下をまとめて開閉`,
    );
    this.hideCtx = hideCtxGlobal;
    this.seq = 0;
    this.draw();
    return el("div", null, this.tb, this.wrap, legend, this.detail);
  }
  createToolbar() {
    const search = el("input", {
      type: "search",
      placeholder: `${dataLevelLabel(this.kind, (this.kindSpec.levels || []).length)} で列を探す`,
      oninput: () => {
        this.st.q = search.value.trim();
        this.draw();
      },
    });

    this.tb = el(
      "div",
      { class: "toolbar" },
      el(
        "span",
        null,
        "行: ",
        el("button", { class: "link", onclick: () => this.openAll("row") }, "すべて開く"),
        " | ",
        el(
          "button",
          {
            class: "link",
            onclick: () => {
              this.st.rowOpen = new Set([this.rowRoot]);
              this.draw();
            },
          },
          "畳む",
        ),
      ),
      el(
        "span",
        null,
        "列: ",
        el("button", { class: "link", onclick: () => this.openAll("col") }, "すべて開く"),
        " | ",
        el(
          "button",
          {
            class: "link",
            onclick: () => {
              this.st.colOpen = new Set([this.colRoot]);
              this.draw();
            },
          },
          "畳む",
        ),
      ),
      search,
      el(
        "label",
        null,
        el("input", {
          type: "checkbox",
          checked: this.st.touched,
          onchange: (ev) => {
            this.st.touched = ev.target.checked;
            this.draw();
          },
        }),
        "表示中の行が使う列だけ",
      ),
      this.k.flag
        ? el(
            "label",
            null,
            el("input", {
              type: "checkbox",
              onchange: (ev) => {
                this.st.unknownOnly = ev.target.checked;
                this.draw();
              },
            }),
            `${term("unknown")} を含むものだけ`,
          )
        : null,
      this.status,
    );
  }

  // 木を可視の節に展開する (開いている節の子を並べる)
  axisSettings(axis) {
    const open = axis === "row" ? this.st.rowOpen : this.st.colOpen;
    const root = axis === "row" ? this.rowRoot : this.colRoot;
    const col = axis === "row" ? this.k.row : this.k.col;
    const filt = axis === "row" ? this.rowFilter() : this.colFilter();
    return { open, root, col, filt };
  }

  async visible(axis) {
    const { open, root, col, filt } = this.axisSettings(axis);
    const mart = this.m;
    const out = []; // {key, name, depth, open, isLeaf, parent}
    async function walk(key, depth, parentIdx) {
      const kids = await tree(mart, col, key, filt);
      for (const c of kids) {
        const idx = out.length;
        const node = {
          key: c.key,
          name: c.name,
          depth,
          isLeaf: c.is_leaf,
          open: open.has(c.key) && !c.is_leaf,
          parent: parentIdx,
          children: [],
          leaves: c.leaves,
        };
        out.push(node);
        if (parentIdx != null) out[parentIdx].children.push(idx);
        if (node.open) await walk(c.key, depth + 1, idx);
      }
    }
    await walk(root, 1, null);
    if (!out.length && root !== "/")
      out.push({
        key: root,
        name: segs(root).slice(-1)[0] || root,
        depth: 1,
        isLeaf: true,
        open: false,
        parent: null,
        children: [],
        leaves: 1,
      }); // 根が葉 (1 つのデータ・1 つの入口) ならそれ自身を見せる
    return out;
  }

  async openAll(axis) {
    const open = axis === "row" ? this.st.rowOpen : this.st.colOpen;
    const root = axis === "row" ? this.rowRoot : this.colRoot;
    const n = await this.openUnder(axis, root, 400);
    if (n >= 400)
      toast("開く行・列が多いので 400 個まで開いた。検索で列を絞るか、配下を個別に開く");
    void open;
    this.draw();
  }

  async openUnder(axis, key, cap) {
    const open = axis === "row" ? this.st.rowOpen : this.st.colOpen;
    const col = axis === "row" ? this.k.row : this.k.col;
    const filt = axis === "row" ? this.rowFilter() : this.colFilter();
    let n = 0;
    const stack = [key];
    while (stack.length && n < cap) {
      const cur = stack.pop();
      open.add(cur);
      n++;
      const kids = await tree(this.m, col, cur, filt);
      for (const c of kids) if (!c.is_leaf) stack.push(c.key);
    }
    return n;
  }

  closeUnder(axis, key) {
    const open = axis === "row" ? this.st.rowOpen : this.st.colOpen;
    for (const x of [...open]) if (x === key || x.startsWith(key + "/")) open.delete(x);
    if (key === (axis === "row" ? this.rowRoot : this.colRoot)) open.add(key); // 根は閉じない (子は見せる)
  }

  toggle(axis, key) {
    const open = axis === "row" ? this.st.rowOpen : this.st.colOpen;
    if (open.has(key)) this.closeUnder(axis, key);
    else open.add(key);
    this.draw();
  }

  contextMenu(ev, axis, key) {
    ev.preventDefault();
    $ctx.replaceChildren(
      el("div", { class: "ttl" }, key),
      el(
        "button",
        {
          onclick: async () => {
            this.hideCtx();
            const n = await this.openUnder(axis, key, 400);
            if (n >= 400) toast("配下が多いので 400 個まで開いた");
            this.draw();
          },
        },
        "配下をすべて開く",
      ),
      el(
        "button",
        {
          onclick: () => {
            this.hideCtx();
            this.closeUnder(axis, key);
            this.draw();
          },
        },
        "配下をすべて閉じる",
      ),
      el(
        "button",
        {
          onclick: () => {
            this.hideCtx();
            location.hash =
              axis === "row" ? hEntries(key) : hData(this.kind, joinPath(segs(key).slice(1)));
          },
        },
        axis === "row" ? `この ${term("entry")} の階層を開く` : `この ${term("datastore")} を開く`,
      ),
    );
    $ctx.hidden = false;
    const x = Math.min(ev.clientX, window.innerWidth - 240),
      y = Math.min(ev.clientY, window.innerHeight - 160);
    $ctx.style.cssText = `left:${x}px;top:${y}px`;
  }

  loadCells(rowsV, colLeaves) {
    return pivot(this.m, {
      row: this.k.row,
      col: this.k.col,
      value: this.k.value,
      flag: this.k.flag,
      row_keys: rowsV.map((r) => r.key),
      col_keys: colLeaves.map((c) => c.key),
      filters: this.cellFilter(),
    });
  }

  async draw() {
    const my = ++this.seq;
    this.wrap.replaceChildren(loading());
    try {
      const [rowsV, colsV] = await Promise.all([this.visible("row"), this.visible("col")]);
      if (my !== this.seq) return;
      // 列の見出し: 開いた節は配下の葉をまたぐ。葉列 = 開いていない可視の節
      const colLeaves = colsV.filter((c) => !c.open);
      const cells = await this.loadCells(rowsV, colLeaves);
      if (my !== this.seq) return;
      const cellMap = new Map(cells.cells.map((c) => [c.row + "\u0000" + c.col, c]));
      const maxDepth = Math.max(1, ...colsV.map((c) => c.depth));
      // 列見出しの行 (段ごと)。開いた節は colspan = 配下の葉列の数、rowspan は葉で深さが浅いとき
      const headRows = this.columnHeadingRows(maxDepth, colsV);
      const thead = tableHead(headRows, maxDepth, rowsV, colLeaves);
      const tbody = this.tableBody(rowsV, colLeaves, cellMap);
      this.wrap.replaceChildren(el("table", { class: "pivot" }, thead, tbody));
      this.status.textContent = `行 ${rowsV.length} · 列 ${colLeaves.length} (開いた階層 ${colsV.filter((c) => c.open).length})`;
    } catch (e) {
      if (my === this.seq) this.wrap.replaceChildren(el("p", { class: "err" }, e.message));
    }
  }

  tableCell(r, c, cellMap) {
    const cell = cellMap.get(r.key + "\u0000" + c.key);
    if (!cell || cell.value == null) return el("td", null, "—");
    return el(
      "td",
      {
        class: `has${cell.flag ? " flag" : ""}`,
        title: `${r.key} × ${c.key}: ${cell.rows} 行。押すと内訳`,
        onclick: () => this.showDetail(r, c, cell),
      },
      fmt(cell.value),
    );
  }

  tableBody(rowsV, colLeaves, cellMap) {
    return el(
      "tbody",
      null,
      rowsV.map((r) =>
        el(
          "tr",
          { class: r.isLeaf ? null : "group" },
          el(
            "th",
            {
              "data-node": r.key,
              title: r.key,
              style: `padding-left:${8 + (r.depth - 1) * 16}px`,
              oncontextmenu: r.isLeaf ? null : (ev) => this.contextMenu(ev, "row", r.key),
            },
            el(
              "button",
              {
                class: "tg" + (r.isLeaf ? " leaf" : ""),
                onclick: () => this.toggle("row", r.key),
                title: r.isLeaf ? null : r.open ? "畳む" : "配下を開く",
              },
              r.open ? "▾" : "▸",
            ),
            el("a", { href: r.isLeaf ? hEntry(r.key) : hEntries(r.key), title: r.key }, r.name),
          ),
          colLeaves.map((c) => this.tableCell(r, c, cellMap)),
        ),
      ),
    );
  }

  columnHeadingRows(maxDepth, colsV) {
    const headRows = Array.from({ length: maxDepth }, () => []);
    colsV.forEach((c, idx) => {
      const th = el(
        "th",
        {
          class: c.open ? "group" : null,
          "data-node": c.key,
          title: c.key,
          colspan: c.open ? countLeaves(colsV, idx) : null,
          rowspan: c.open ? null : maxDepth - c.depth + 1,
          oncontextmenu: c.isLeaf ? null : (ev) => this.contextMenu(ev, "col", c.key),
        },
        el(
          "button",
          {
            class: "tg" + (c.isLeaf ? " leaf" : ""),
            onclick: () => this.toggle("col", c.key),
            title: c.isLeaf ? null : c.open ? "畳む" : "配下を開く",
          },
          c.open ? "▾" : "▸",
        ),
        el(
          "a",
          {
            class: "lbl",
            href: hData(this.kind, joinPath(segs(c.key).slice(1))),
            title: `${c.key} の ${term("referenced_by")} と ${term("call_path")} を開く`,
          },
          c.name,
        ),
      );
      headRows[c.depth - 1].push(th);
    });
    return headRows;
  }

  showDetail(r, c, cell) {
    const params = {
      ...this.cellFilter(),
      [`${this.k.row}__under`]: r.key,
      [`${this.k.col}__under`]: c.key,
    }; // セルの集計と同じ条件
    this.detail.replaceChildren(
      el(
        "div",
        { class: "detail" },
        el(
          "h3",
          null,
          `${r.key} × ${c.key}`,
          el("span", { class: "muted" }, `${cell.rows} 行`),
          el("button", { class: "close", onclick: () => this.detail.replaceChildren() }, "閉じる"),
        ),
        listTable(this.m, { base: params, pageSize: 50 }),
      ),
    );
  }
}

function countLeaves(columns, index) {
  const node = columns[index];
  if (!node.open) return 1;
  return node.children.reduce((count, child) => count + countLeaves(columns, child), 0);
}

function tableHead(headRows, maxDepth, rowsV, colLeaves) {
  return el(
    "thead",
    null,
    headRows.map((cells, i) =>
      el(
        "tr",
        null,
        i === 0
          ? el(
              "th",
              { class: "corner", rowspan: maxDepth },
              `${rowsV.length} × ${colLeaves.length}`,
            )
          : null,
        cells,
      ),
    ),
  );
}

export function hideCtxGlobal() {
  $ctx.hidden = true;
}
