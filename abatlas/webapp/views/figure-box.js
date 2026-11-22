// 表示の種類: 図の入れ物 (シーケンスと有向グラフで共用) と、図を描く小道具。図の共通機能 (枠・拡大縮小・強調) はここだけ

import { el, svg } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { KIND_TERM, term } from "../model/vocab.js";
import { emptyMsg } from "../ui/card.js";

export function wrapText(s, n) {
  const str = String(s);
  if (str.length <= n) return [str];
  const parts = segs(str);
  if (parts.length >= 2) {
    const tail = parts.slice(-1)[0],
      head = "/" + parts.slice(0, -1).join("/");
    return [
      head.length > n ? "…" + head.slice(-(n - 1)) : head,
      tail.length > n ? tail.slice(0, n - 1) + "…" : tail,
    ];
  }
  return [str.slice(0, n), str.length > 2 * n ? str.slice(n, 2 * n - 1) + "…" : str.slice(n)];
}
// 角を丸めた直角の線。(x1, y1) から右へ出て lx で曲がり (x2, y2) へ入る。y1 == y2 なら直線
export function elbow(x1, y1, lx, x2, y2) {
  const dy = y2 - y1;
  if (Math.abs(dy) < 1) return `M ${x1} ${y1} H ${x2}`;
  const r = Math.min(8, Math.abs(dy) / 2, Math.max(2, (lx - x1) / 2));
  const s = dy > 0 ? 1 : -1;
  return `M ${x1} ${y1} H ${lx - r} Q ${lx} ${y1} ${lx} ${y1 + s * r} V ${y2 - s * r} Q ${lx} ${y2} ${lx + r} ${y2} H ${x2}`;
}
// ------------------------------------------------------------ 図の入れ物 (シーケンスと有向グラフで共用)
// 参加者 (ノード) が何人でも扱えるように:
//   枠 (見切れている側に影が出る) / 拡大縮小 (初期表示はできるだけ横幅に合わせた倍率。最小 5% でも収まらない分は枠内で横スクロール。Ctrl + ホイールでも) /
//   全画面 (背後は inert、Esc で閉じる) / 見出し (あれば) は縦スクロールしても固定 /
//   絞り込み (種類: 入口・処理 (frame)・データ・外部接続、名前、不明の辺だけ)。名前は「どちらかの端が合う辺」を残す。種類は図ごとに意味が違う (filterMode):
//     either (シーケンス): どちらかの端が選んだ種類なら残し、相手側は文脈として描く。処理 (frame) は全メッセージに現れるので、処理を外す = 処理同士の呼び出しを隠す
//     both (有向グラフ): 外した種類のノードとその辺を隠す。辺は入口 ↔ データ / 外部接続の 2 部構造なので、either だと何も消えない
// 図が DOM から外れたら (タブや経路の切り替え) 全画面を閉じてリスナーと observer を解く
// o: { title, nouns: [点の名詞, 辺の名詞], totals: [点の総数, 辺の総数], present: Set<種類>, hasUnknown, unknownLabel, searchLabel, hasHead, filterMode: either | both,
//      draw(state, markerId) → { head?: svg, body: svg, w, headH?, bodyH, counts: [点, 辺], aside?: 図の下に置く要素, legend?: [[クラス, 意味], …] } | null (絞り込みに合うものが無い) }
// 強調表示: draw が箱に data-n、辺に data-e / data-f / data-t を付けておくと、マウスを乗せた要素とつながる箱・辺だけを濃く残す。
//   クリック / タップで固定、同じ要素か余白をもう一度で解除。Tab で箱 (見出しがあれば見出しの箱) に移り Enter / Space でクリックと同じ。辺の内容はキーボードでは一覧から (mental-modeling スキルの流儀)
// 矢じり 3 種: 通常 (id)、不明を含む辺用の薄いもの (id-u)、強調中の辺用の墨 (id-on)。色は CSS (svg marker path)
export function arrowDefs(id) {
  const mk = (mid, cls) =>
    svg(
      "marker",
      {
        id: mid,
        class: cls,
        viewBox: "0 0 10 10",
        refX: 10,
        refY: 5,
        markerWidth: 7,
        markerHeight: 7,
        markerUnits: "userSpaceOnUse",
        orient: "auto-start-reverse",
      },
      svg("path", { d: "M 0 0 L 10 5 L 0 10 z" }),
    );
  return svg("defs", null, mk(id, null), mk(`${id}-u`, "faint"), mk(`${id}-on`, "on")); // -on は強調中の辺用 (墨)
}
export const markerFor = (id, unknown) => `url(#${unknown ? `${id}-u` : id})`;
let figSerial = 0;
export function figureBox(o) {
  return new FigureBox().mount(o);
}

class FigureBox {
  constructor() {
    this.fit = this.fit.bind(this);
    this.edges = this.edges.bind(this);
    this.onKey = this.onKey.bind(this);
    this.onRoute = this.onRoute.bind(this);
  }

  mount(o) {
    this.o = o;

    this.state = {
      kinds: new Set(Object.keys(KIND_TERM)),
      q: "",
      unknownOnly: false,
      scale: 1,
      manual: false,
      full: false,
      mode: this.o.filterMode || "either",
    };

    this.marker = `fig-arrow-${++figSerial}`;
    // 図ごとに別の id (同じページに図が複数あっても重複しない)
    this.head = this.o.hasHead ? el("div", { class: "fbox-head" }) : null;

    this.body = el("div", { class: "fbox-body" });

    this.scroller = el(
      "div",
      {
        class: "fbox-scroll",
        tabindex: "0",
        "aria-label": "図のスクロール領域 (矢印キーで動かす)",
      },
      this.head,
      this.body,
    );

    this.view = el("div", { class: "fbox-view" }, this.scroller);

    this.count = el("span", { class: "count" });

    this.pct = el("span", { class: "pct mono" });

    this.fullBtn = el(
      "button",
      { type: "button", onclick: () => this.setFull(!this.state.full) },
      "全画面",
    );

    this.createFilterChips();

    const search = el("input", {
      type: "search",
      placeholder: this.o.searchLabel,
      "aria-label": this.o.searchLabel,
      oninput: () => {
        this.state.q = search.value.trim().toLowerCase();
        this.draw();
      },
    });

    const zoom = el(
      "span",
      { class: "zoom" },
      el(
        "button",
        {
          type: "button",
          "aria-label": "縮小",
          onclick: () => this.zoomAt(this.state.scale / 1.25),
        },
        "−",
      ),
      this.pct,
      el(
        "button",
        {
          type: "button",
          "aria-label": "拡大",
          onclick: () => this.zoomAt(this.state.scale * 1.25),
        },
        "+",
      ),
      el(
        "button",
        {
          type: "button",
          title: "できるだけ横幅に合わせる (5% でも収まらない分は横スクロール)",
          onclick: () => {
            this.state.manual = false;
            this.state.fitAll = true;
            this.fit();
          },
        },
        "全体",
      ),
      el("button", { type: "button", onclick: () => this.zoomAt(1) }, "100%"),
    );

    const toolbar = el(
      "div",
      { class: "toolbar" },
      search,
      this.chips,
      this.count,
      zoom,
      this.fullBtn,
    );

    this.legend = el("div", { class: "fbox-legend" });

    this.aside = el("div", { class: "fbox-foot" });
    // 図の下 (倍率の外)。draw が返す aside (辺の一覧など) を置く
    this.box = el(
      "div",
      { class: "fbox", role: "group", "aria-label": this.o.title },
      toolbar,
      this.view,
      this.legend,
      this.aside,
    );

    // 凡例のスウォッチは実際の図と同じクラスで描く (見た目と凡例がずれない)。線には矢じりも付ける
    this.keySerial = 0;

    // 強調表示 (data-n / data-e / data-f / data-t を draw が付ける)
    this.pinned = null;

    this.keyOf = (t) => (t.dataset.n != null ? `n:${t.dataset.n}` : `e:${t.dataset.e}`);

    this.installHover();

    this.installSelectionHandlers();

    this.natural = { w: 0, headH: 0, bodyH: 0 };

    this.countText = (c) =>
      `${this.o.nouns[0]} ${c[0]} / ${this.o.totals[0]} · ${this.o.nouns[1]} ${c[1]} / ${this.o.totals[1]}`;

    this.inerted = [];

    this.ro = null;

    this.observeViewport();

    this.observeSize();

    this.draw();

    requestAnimationFrame(() => {
      if (!this.state.manual) this.fit();
    });
    // DOM に載ってから幅が決まる
    return this.box;
  }
  createFilterChips() {
    this.chips = el("div", { class: "chips" });

    for (const kind of Object.keys(KIND_TERM)) {
      if (!this.o.present.has(kind)) continue;
      const c = el(
        "button",
        {
          type: "button",
          class: "chip on",
          "aria-pressed": "true",
          onclick: () => {
            if (this.state.kinds.has(kind)) this.state.kinds.delete(kind);
            else this.state.kinds.add(kind);
            c.classList.toggle("on", this.state.kinds.has(kind));
            c.setAttribute("aria-pressed", String(this.state.kinds.has(kind)));
            this.draw();
          },
        },
        term(KIND_TERM[kind]),
      );
      this.chips.append(c);
    }

    if (this.o.hasUnknown) {
      const c = el(
        "button",
        {
          type: "button",
          class: "chip",
          "aria-pressed": "false",
          onclick: () => {
            this.state.unknownOnly = !this.state.unknownOnly;
            c.classList.toggle("on", this.state.unknownOnly);
            c.setAttribute("aria-pressed", String(this.state.unknownOnly));
            this.draw();
          },
        },
        this.o.unknownLabel,
      );
      this.chips.append(c);
    }
  }
  installHover() {
    this.view.addEventListener("pointerover", (ev) => {
      if (ev.pointerType !== "mouse" || this.pinned) return;
      const t = ev.target.closest("[data-n], [data-e]");
      if (t) this.focusOn(t);
    });

    this.view.addEventListener("pointerout", (ev) => {
      if (ev.pointerType !== "mouse" || this.pinned) return;
      const t = ev.target.closest("[data-n], [data-e]");
      if (t && !(ev.relatedTarget && t.contains(ev.relatedTarget))) this.clearFocus();
    });
  }
  installSelectionHandlers() {
    this.view.addEventListener("click", (ev) => {
      if (ev.target.closest("a")) return; // リンクはそのまま
      const t = ev.target.closest("[data-n], [data-e]");
      if (!t || this.keyOf(t) === this.pinned) {
        this.pinned = null;
        this.clearFocus();
        return;
      }
      this.pinned = this.keyOf(t);
      this.focusOn(t);
    });

    this.view.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      if (ev.target.closest && ev.target.closest("a")) return; // リンクの上の Enter はリンクを優先
      const t = ev.target.closest && ev.target.closest("[data-n], [data-e]");
      if (!t) return;
      ev.preventDefault();
      t.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  }
  observeViewport() {
    // 経路が変わったら全画面は閉じる
    window.addEventListener("hashchange", this.onRoute);

    this.scroller.addEventListener("scroll", this.edges, { passive: true });

    this.scroller.addEventListener(
      "wheel",
      (ev) => {
        if (!(ev.ctrlKey || ev.metaKey)) return; // ふつうのホイールはスクロール
        ev.preventDefault();
        const rect = this.scroller.getBoundingClientRect();
        this.zoomAt(
          this.state.scale * (ev.deltaY < 0 ? 1.1 : 1 / 1.1),
          ev.clientX - rect.left,
          ev.clientY - rect.top,
        ); // カーソルの下の点を動かさない
      },
      { passive: false },
    );
  }
  observeSize() {
    if (typeof ResizeObserver === "function") {
      this.ro = new ResizeObserver(() => {
        if (!this.box.isConnected) {
          this.destroy();
          return;
        }
        if (!this.state.manual) this.fit();
        else this.edges();
      });
      this.ro.observe(this.scroller);
    }
  }

  swatch(cls) {
    const sw = svg("svg", { viewBox: "0 0 28 14", width: 28, height: 14, "aria-hidden": "true" });
    const isBox = /^(node|life)\b/.test(cls);
    if (!isBox) sw.append(arrowDefs(`${this.marker}-key-${++this.keySerial}`));
    sw.append(
      svg(
        "g",
        { class: cls },
        isBox
          ? svg("rect", { x: 1, y: 1, width: 26, height: 12, rx: 2 })
          : svg("path", {
              d: "M 1 7 H 24",
              "marker-end": markerFor(
                `${this.marker}-key-${this.keySerial}`,
                /\bunknown\b/.test(cls),
              ),
            }),
      ),
    );
    return sw;
  }

  clearFocus() {
    this.box.classList.remove("fb-focus");
    for (const x of this.view.querySelectorAll(".on, .cur")) x.classList.remove("on", "cur");
    for (const x of this.view.querySelectorAll("[data-mk]")) {
      x.setAttribute("marker-end", x.dataset.mk);
      delete x.dataset.mk;
    } // 矢じりを元に戻す
  }

  focusOn(target) {
    this.clearFocus();
    const { nodesOn, edgesOn } = this.focusedIds(target);
    for (const x of this.view.querySelectorAll("[data-n]")) {
      if (nodesOn.has(x.dataset.n)) x.classList.add("on");
      if (x.dataset.n === target.dataset.n) x.classList.add("cur");
    }
    for (const x of this.view.querySelectorAll("[data-e]"))
      if (edgesOn.has(x.dataset.e)) x.classList.add("on");
    for (const x of this.view.querySelectorAll("[data-e].on [marker-end]")) {
      if (!x.dataset.mk) x.dataset.mk = x.getAttribute("marker-end");
      x.setAttribute("marker-end", `url(#${this.marker}-on)`);
    } // 強調中は矢じりも墨に
    this.box.classList.add("fb-focus");
  }

  focusedIds(target) {
    const nodesOn = new Set(),
      edgesOn = new Set();
    if (target.dataset.n != null) {
      nodesOn.add(target.dataset.n);
      for (const e of this.view.querySelectorAll("[data-e]"))
        if (e.dataset.f === target.dataset.n || e.dataset.t === target.dataset.n) {
          edgesOn.add(e.dataset.e);
          nodesOn.add(e.dataset.f);
          nodesOn.add(e.dataset.t);
        }
    } else {
      edgesOn.add(target.dataset.e);
      nodesOn.add(target.dataset.f);
      nodesOn.add(target.dataset.t);
    }
    return { nodesOn, edgesOn };
  }

  installFocus() {
    this.pinned = null;
    this.clearFocus();
    for (const x of (this.head || this.body).querySelectorAll("[data-n]")) {
      x.setAttribute("tabindex", "0");
      x.setAttribute("role", "button");
    } // Tab は箱だけ (見出しがあれば見出しの箱だけ。辺は数百本あると実用にならない。辺の内容はキーボードでは一覧から)
  }

  draw() {
    if (this.head) this.head.replaceChildren();
    this.body.replaceChildren();
    const wasOpen = !!this.aside.querySelector("details[open]"); // 開いていた一覧は絞り込み後も開いたまま
    this.aside.replaceChildren();
    const r = this.o.draw(this.state, this.marker);
    if (!r) {
      this.count.textContent = this.countText([0, 0]);
      this.body.append(emptyMsg("絞り込みに合うものが無い"));
      this.legend.replaceChildren();
      this.natural = { w: 0, headH: 0, bodyH: 0 };
      this.installFocus();
      this.apply();
      return;
    }
    if (this.head && r.head) this.head.append(r.head);
    this.body.append(r.body);
    this.natural = { w: r.w, headH: r.headH || 0, bodyH: r.bodyH };
    this.showLegendAndAside(r, wasOpen);
    this.installFocus();
    this.count.textContent = this.countText(r.counts);
    if (this.state.manual) this.apply();
    else this.fit();
  }

  showLegendAndAside(r, wasOpen) {
    if (r.aside) {
      this.aside.append(r.aside);
      if (wasOpen && r.aside.tagName === "DETAILS") r.aside.open = true;
    }
    this.legend.replaceChildren(
      ...(r.legend || []).map(([cls, label]) =>
        el("span", { class: "key" }, this.swatch(cls), label),
      ),
      el("span", { class: "key hint" }, "箱や矢印に触れるとつながりだけ濃く残る (タップで固定)"),
    );
  }

  apply() {
    const s = this.state.scale;
    for (const [wrap, h] of [
      [this.head, this.natural.headH],
      [this.body, this.natural.bodyH],
    ]) {
      const sv = wrap && wrap.querySelector("svg");
      if (!sv) continue;
      sv.setAttribute("width", String(Math.max(1, Math.round(this.natural.w * s))));
      sv.setAttribute("height", String(Math.max(1, Math.round(h * s))));
    }
    this.pct.textContent = `${Math.round(s * 100)}%`;
    for (const mk of this.view.querySelectorAll("marker")) {
      const size = String(Math.round((7 / s) * 10) / 10);
      mk.setAttribute("markerWidth", size);
      mk.setAttribute("markerHeight", size);
    } // 矢じりも線と同じく画面上の大きさを保つ
    this.edges();
  }

  setScale(s, manual) {
    this.state.scale = Math.min(4, Math.max(0.05, s));
    if (manual) this.state.manual = true;
    this.apply();
  }

  // 倍率を変えても、表示領域の点 (px, py。省略時は中心) の下にある図の点を動かさない
  zoomAt(s, px, py) {
    if (px == null) {
      px = this.scroller.clientWidth / 2;
      py = this.scroller.clientHeight / 2;
    }
    const before = this.state.scale;
    this.setScale(s, true);
    const f = this.state.scale / before;
    this.scroller.scrollLeft = (this.scroller.scrollLeft + px) * f - px;
    this.scroller.scrollTop = (this.scroller.scrollTop + py) * f - py;
  }

  fit() {
    const avail = this.scroller.clientWidth;
    if (!avail || !this.natural.w) {
      this.state.scale = 1;
      this.apply();
      return;
    }
    const before = this.state.scale;
    const s = (avail - 2) / this.natural.w;
    // 横幅に合わせると文字が読めなくなる図 (50% 未満) は、読める倍率 (60%) で左上から始める。全体の形は「全体」のボタンで見る
    this.state.scale = s >= 0.5 || this.state.fitAll ? Math.max(0.05, Math.min(1, s)) : 0.6; // 手動と同じ最小倍率。収まらない分は枠内スクロール
    this.apply();
    this.scroller.scrollTop = this.scroller.scrollTop * (this.state.scale / before); // 縦の位置は比率で保つ (横は収まるので 0 のまま)
  }

  edges() {
    this.box.classList.toggle("more-l", this.scroller.scrollLeft > 1);
    this.box.classList.toggle(
      "more-r",
      this.scroller.scrollLeft + this.scroller.clientWidth < this.scroller.scrollWidth - 1,
    );
    this.box.classList.toggle(
      "more-b",
      this.scroller.scrollTop + this.scroller.clientHeight < this.scroller.scrollHeight - 1,
    );
  }

  onKey(ev) {
    if (ev.key === "Escape") this.setFull(false);
  }

  setFull(on) {
    if (on === this.state.full) return;
    this.state.full = on;
    this.box.classList.toggle("full", on);
    document.body.classList.toggle("fbox-full-open", on);
    this.fullBtn.textContent = on ? "全画面を閉じる (Esc)" : "全画面";
    if (on) {
      document.addEventListener("keydown", this.onKey);
      // 背後 (祖先の兄弟) をキーボード操作の対象から外す
      this.makeBackgroundInert();
    } else {
      document.removeEventListener("keydown", this.onKey);
      for (const n of this.inerted) n.inert = false;
      this.inerted = [];
      this.fullBtn.focus();
    }
    if (!this.state.manual) requestAnimationFrame(this.fit);
    else requestAnimationFrame(this.edges);
  }

  makeBackgroundInert() {
    for (let n = this.box; n && n !== document.body; n = n.parentElement) {
      for (const sib of n.parentElement ? n.parentElement.children : [])
        if (sib !== n && !sib.inert) {
          sib.inert = true;
          this.inerted.push(sib);
        }
    }
  }

  destroy() {
    if (this.state.full) this.setFull(false);
    if (this.ro) {
      this.ro.disconnect();
      this.ro = null;
    }
    window.removeEventListener("hashchange", this.onRoute);
  }

  onRoute() {
    if (!this.box.isConnected) this.destroy();
    else if (this.state.full) this.setFull(false);
  }
}
