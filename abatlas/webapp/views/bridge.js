// 表示の種類: 真ん中の物と、左右につながる入口 (view: bridge)。物を 1 つ選ぶと、左 → 物 → 右 の 3 列で描く
//   全部を 1 枚に描くと線が絡むので、真ん中を 1 つ選ぶ形にする。左右の入口は、keys.left / keys.right の列 (パスを ", " で連ねたもの)

import { el, fmt } from "../lib/dom.js";
import { labelOf } from "../model/catalog.js";
import { emptyMsg } from "../ui/card.js";
import { linkOne } from "../ui/link.js";

const SHOWN = 12; // 片側に、最初に並べる数 (残りは、開く)
const split = (v) => (typeof v === "string" && v ? v.split(", ").filter(Boolean) : []);

export function bridge(m, data) {
  return new BridgeView().mount(m, data);
}

class BridgeView {
  mount(m, data) {
    this.m = m;
    this.k = this.m.keys;
    if (!data.rows.length) return emptyMsg("行が無い (該当が無いか、まだ分析されていない)");
    this.indexHubs(data);
    this.st = { q: "", cur: this.hubs[0].id };
    this.list = el("ul", {
      class: "bridge-hubs",
      "aria-label": labelOf(this.m, this.k.label || this.k.id),
    });
    this.fig = el("div", { class: "bridge-fig" });
    this.count = el("span", { class: "count" });
    const search = el("input", {
      type: "search",
      "aria-label": `${labelOf(this.m, this.k.label || this.k.id)} で探す`,
      placeholder: `${labelOf(this.m, this.k.label || this.k.id)} で探す`,
      oninput: () => {
        this.st.q = search.value.trim().toLowerCase();
        this.drawList();
      },
    });
    this.drawList();
    this.drawFig();
    return el(
      "div",
      null,
      el("div", { class: "toolbar" }, search, this.count),
      el(
        "div",
        { class: "bridge" },
        el(
          "div",
          { class: "bridge-pick" },
          el(
            "div",
            { class: "cap" },
            `${labelOf(this.m, this.k.left)} の数 · ${labelOf(this.m, this.k.right)} の数`,
          ),
          this.list,
        ),
        this.fig,
      ),
    );
  }

  indexHubs(data) {
    this.hubs = data.rows
      .map((r) => ({
        id: String(r[this.k.id]),
        label: String(r[this.k.label || this.k.id] ?? ""),
        kind: this.k.kind ? r[this.k.kind] : null,
        left: split(r[this.k.left]),
        right: split(r[this.k.right]),
      }))
      .sort(
        (a, b) =>
          b.left.length + b.right.length - (a.left.length + a.right.length) ||
          a.label.localeCompare(b.label),
      );

    this.top = Math.max(1, ...this.hubs.map((h) => Math.max(h.left.length, h.right.length)));
  }

  side(paths, cls, title) {
    const items = paths.map((p) => el("li", null, linkOne(p)));
    const rest = items.slice(SHOWN);
    for (const li of rest) li.hidden = true;
    const more = rest.length
      ? el(
          "button",
          {
            class: "link",
            onclick: () => {
              for (const li of rest) li.hidden = false;
              more.remove();
            },
          },
          `ほか ${rest.length} 件を開く`,
        )
      : null;
    return el(
      "div",
      { class: `bridge-side ${cls}` },
      el("div", { class: "cap" }, `${title} (${paths.length})`),
      paths.length ? el("ul", null, items) : el("p", { class: "empty" }, "無い"),
      more,
    );
  }

  drawFig() {
    const h = this.hubs.find((x) => x.id === this.st.cur) || this.hubs[0];
    this.fig.replaceChildren(
      this.side(h.left, "left", labelOf(this.m, this.k.left)),
      el("div", { class: "bridge-arrow", "aria-hidden": "true" }),
      el(
        "div",
        { class: "bridge-hub" },
        h.kind ? el("span", { class: "tag" }, h.kind) : null,
        el("div", { class: "nm" }, linkOne(h.id)),
      ),
      el("div", { class: "bridge-arrow", "aria-hidden": "true" }),
      this.side(h.right, "right", labelOf(this.m, this.k.right)),
    );
  }

  drawList() {
    const shown = this.hubs.filter((h) => !this.st.q || h.label.toLowerCase().includes(this.st.q));
    this.list.replaceChildren(
      ...shown.map((h) =>
        el(
          "li",
          null,
          el(
            "button",
            {
              class: `hub${h.id === this.st.cur ? " on" : ""}`,
              "aria-pressed": String(h.id === this.st.cur),
              title: h.id,
              onclick: () => {
                this.st.cur = h.id;
                this.drawList();
                this.drawFig();
              },
            },
            el("span", { class: "nm" }, h.label),
            el(
              "span",
              { class: "io" },
              el("span", { class: "num" }, fmt(h.left.length)),
              el(
                "span",
                { class: "bar l" },
                el("i", { style: `width:${(h.left.length / this.top) * 100}%` }),
              ),
              el("span", { class: "dot" }),
              el(
                "span",
                { class: "bar r" },
                el("i", { style: `width:${(h.right.length / this.top) * 100}%` }),
              ),
              el("span", { class: "num" }, fmt(h.right.length)),
            ),
          ),
        ),
      ),
    );
    if (!shown.length) this.list.replaceChildren(el("li", { class: "empty" }, "該当する物が無い"));
    this.count.textContent =
      shown.length === this.hubs.length
        ? `${this.hubs.length} 件`
        : `${shown.length} / ${this.hubs.length} 件`;
  }
}
