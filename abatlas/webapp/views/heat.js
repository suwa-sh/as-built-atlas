// 表示の種類: 行と列の組ごとの数 (view: heat)。階層で畳まない平らな表。全体を 1 枚で見て、偏りと例外を探す
//   濃いセルほど、その列の中で数が多い。keys.flag が真のセルは朱 (注意して見る所)

import { el, fmt } from "../lib/dom.js";
import { labelOf } from "../model/catalog.js";
import { term } from "../model/vocab.js";
import { emptyMsg } from "../ui/card.js";
import { linkValue } from "../ui/link.js";

const MAX_COLS = 60;
const MAX_ROWS = 500;

export function heat(m, data) {
  return new HeatTable().mount(m, data);
}

class HeatTable {
  mount(m, data) {
    this.m = m;
    this.data = data;
    this.k = this.m.keys;
    if (!this.data.rows.length) return emptyMsg("行が無い");
    this.indexCells();
    this.chooseColumns();
    this.measureCells();
    this.st = { q: "", flagOnly: false, sort: null };
    this.body = el("tbody");
    this.cut = el("p", { class: "caveat" });
    this.count = el("span", { class: "count" });
    this.head = el("tr");
    this.createSearchToolbar();
    this.draw();
    return el(
      "div",
      null,
      this.tools,
      this.cut,
      el(
        "div",
        { class: "scroll heat-wrap" },
        el("table", { class: "heat" }, el("thead", null, this.head), this.body),
      ),
    );
  }
  indexCells() {
    const cols = new Map();
    // 列の値 → 並び順
    this.rows = new Map();
    // 行の値 → { 列の値 → 行 }
    for (const r of this.data.rows) {
      const c = String(r[this.k.col] ?? "");
      const ord = this.k.order && typeof r[this.k.order] === "number" ? r[this.k.order] : 0;
      if (!cols.has(c) || ord < cols.get(c)) cols.set(c, ord);
      const key = String(r[this.k.row] ?? "");
      if (!this.rows.has(key)) this.rows.set(key, new Map());
      this.rows.get(key).set(c, r);
    }

    this.allCols = [...cols.keys()].sort((a, b) => cols.get(a) - cols.get(b) || a.localeCompare(b));
  }
  chooseColumns() {
    // 行と列の種類がどちらも多い表は、全部の組を描くと画面が止まる。列は MAX_COLS まで、行は MAX_ROWS までを描き、切ったことを出す
    // 切るときは、印のあるセルを持つ列を先に残す (「印だけ」で残った行の理由が、描いた列の中に必ず見える)。残した列は、元の並び順に戻す
    const flagCols = new Set(
      this.k.flag
        ? this.data.rows
            .filter((r) => r[this.k.flag] === true)
            .map((r) => String(r[this.k.col] ?? ""))
        : [],
    );

    const kept = new Set(
      this.allCols.length > MAX_COLS
        ? [
            ...this.allCols.filter((c) => flagCols.has(c)),
            ...this.allCols.filter((c) => !flagCols.has(c)),
          ].slice(0, MAX_COLS)
        : this.allCols,
    );

    this.colKeys = this.allCols.filter((c) => kept.has(c));
  }
  measureCells() {
    this.val = (cells, c) => {
      const r = cells.get(c);
      return r && typeof r[this.k.value] === "number" ? r[this.k.value] : 0;
    };

    this.flagged = (cells) =>
      !!this.k.flag &&
      this.colKeys.some((c) => {
        const r = cells.get(c);
        return !!r && r[this.k.flag] === true;
      });
    // 描いている列だけで判定する
    this.max = Object.fromEntries(
      this.colKeys.map((c) => [
        c,
        Math.max(1, ...[...this.rows.values()].map((cells) => this.val(cells, c))),
      ]),
    );
  }
  createSearchToolbar() {
    const search = el("input", {
      type: "search",
      "aria-label": `${labelOf(this.m, this.k.row)} で探す`,
      placeholder: `${labelOf(this.m, this.k.row)} で探す`,
      oninput: () => {
        this.st.q = search.value.trim().toLowerCase();
        this.draw();
      },
    });

    const flagCount = this.k.flag ? [...this.rows.values()].filter(this.flagged).length : 0;

    this.tools = el(
      "div",
      { class: "toolbar" },
      search,
      this.k.flag
        ? el(
            "label",
            null,
            el("input", {
              type: "checkbox",
              onchange: (ev) => {
                this.st.flagOnly = ev.target.checked;
                this.draw();
              },
            }),
            `${labelOf(this.m, this.k.flag)} だけ (${flagCount})`,
          )
        : null,
      this.count,
    );
  }

  draw() {
    let keys = this.sortedRows();
    const hit = keys.length;
    keys = keys.slice(0, MAX_ROWS);
    this.showTruncation(hit, keys);
    this.drawHeading();
    this.body.replaceChildren(
      ...keys.map((key) => {
        const cells = this.rows.get(key);
        return el(
          "tr",
          { class: this.flagged(cells) ? "flagrow" : null },
          el("th", { scope: "row" }, linkValue(key, this.m, this.k.row)),
          this.colKeys.map((c) => this.cell(cells, c)),
        );
      }),
    );
    this.count.textContent =
      hit === this.rows.size ? `${this.rows.size} 行` : `${hit} / ${this.rows.size} 行`;
  }

  cell(cells, c) {
    const r = cells.get(c);
    const n = this.val(cells, c);
    if (this.k.flag && r?.[this.k.flag] === true)
      return el(
        "td",
        { class: "flag" },
        n ? fmt(n) : labelOf(this.m, this.k.flag),
        typeof r[this.k.value] === "number" ? null : " ?",
      );
    // 行が無い組は「—」、値が無い (null) は「?」、数えて 0 は「0」。3 つを見分けられるようにする
    if (!r) return el("td", { class: "zero" }, "—");
    if (typeof r[this.k.value] !== "number")
      return el("td", { class: "zero", title: "値が無い" }, "?");
    if (!n) return el("td", { class: "zero" }, "0");
    const step = n / this.max[c] > 0.66 ? 3 : n / this.max[c] > 0.33 ? 2 : 1;
    return el("td", { class: `h${step}` }, fmt(n));
  }

  sortedRows() {
    let keys = [...this.rows.keys()].filter(
      (key) =>
        (!this.st.q || key.toLowerCase().includes(this.st.q)) &&
        (!this.st.flagOnly || this.flagged(this.rows.get(key))),
    );
    // 既定の並び: 印のある行を先に、その中は名前の順。列を選んだら、その列の数の多い順
    keys.sort(
      (a, b) =>
        (this.st.sort
          ? this.val(this.rows.get(b), this.st.sort) - this.val(this.rows.get(a), this.st.sort)
          : Number(this.flagged(this.rows.get(b))) - Number(this.flagged(this.rows.get(a)))) ||
        a.localeCompare(b),
    );
    return keys;
  }

  showTruncation(hit, keys) {
    this.cut.replaceChildren(
      ...(hit > keys.length || this.allCols.length > this.colKeys.length
        ? [
            el(
              "b",
              null,
              `${hit > keys.length ? `${hit} 行のうち ${keys.length} 行` : ""}${hit > keys.length && this.allCols.length > this.colKeys.length ? "、" : ""}${this.allCols.length > this.colKeys.length ? `${this.allCols.length} 列のうち ${this.colKeys.length} 列` : ""} を描いている`,
            ),
            `。検索で絞るか、全体は ${term("mart")} のページで見る`,
          ]
        : []),
    );
  }

  drawHeading() {
    this.head.replaceChildren(
      el("th", { class: "corner" }, labelOf(this.m, this.k.row)),
      ...this.colKeys.map((c) =>
        el(
          "th",
          { "aria-sort": this.st.sort === c ? "descending" : null },
          el(
            "button",
            {
              class: "link",
              title: "押すと、この列の数の多い順に並べる (もう一度押すと、元の順)",
              onclick: () => {
                this.st.sort = this.st.sort === c ? null : c;
                this.draw();
              },
            },
            c,
            this.st.sort === c ? el("span", { class: "dir" }, "▼") : null,
          ),
        ),
      ),
    );
  }
}
