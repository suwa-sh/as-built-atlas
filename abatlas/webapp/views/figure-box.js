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
    const tail = parts.slice(-1)[0], head = "/" + parts.slice(0, -1).join("/");
    return [head.length > n ? "…" + head.slice(-(n - 1)) : head, tail.length > n ? tail.slice(0, n - 1) + "…" : tail];
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
  const mk = (mid, cls) => svg("marker", { id: mid, class: cls, viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7, markerHeight: 7, markerUnits: "userSpaceOnUse", orient: "auto-start-reverse" },
    svg("path", { d: "M 0 0 L 10 5 L 0 10 z" }));
  return svg("defs", null, mk(id, null), mk(`${id}-u`, "faint"), mk(`${id}-on`, "on")); // -on は強調中の辺用 (墨)
}
export const markerFor = (id, unknown) => `url(#${unknown ? `${id}-u` : id})`;
let figSerial = 0;
export function figureBox(o) {
  const state = { kinds: new Set(Object.keys(KIND_TERM)), q: "", unknownOnly: false, scale: 1, manual: false, full: false, mode: o.filterMode || "either" };
  const marker = `fig-arrow-${++figSerial}`; // 図ごとに別の id (同じページに図が複数あっても重複しない)
  const head = o.hasHead ? el("div", { class: "fbox-head" }) : null;
  const body = el("div", { class: "fbox-body" });
  const scroller = el("div", { class: "fbox-scroll", tabindex: "0", "aria-label": "図のスクロール領域 (矢印キーで動かす)" }, head, body);
  const view = el("div", { class: "fbox-view" }, scroller);
  const count = el("span", { class: "count" });
  const pct = el("span", { class: "pct mono" });
  const fullBtn = el("button", { type: "button", onclick: () => setFull(!state.full) }, "全画面");
  const chips = el("div", { class: "chips" });
  for (const kind of Object.keys(KIND_TERM)) {
    if (!o.present.has(kind)) continue;
    const c = el("button", { type: "button", class: "chip on", "aria-pressed": "true", onclick: () => {
      if (state.kinds.has(kind)) state.kinds.delete(kind); else state.kinds.add(kind);
      c.classList.toggle("on", state.kinds.has(kind));
      c.setAttribute("aria-pressed", String(state.kinds.has(kind)));
      draw();
    } }, term(KIND_TERM[kind]));
    chips.append(c);
  }
  if (o.hasUnknown) {
    const c = el("button", { type: "button", class: "chip", "aria-pressed": "false", onclick: () => {
      state.unknownOnly = !state.unknownOnly;
      c.classList.toggle("on", state.unknownOnly);
      c.setAttribute("aria-pressed", String(state.unknownOnly));
      draw();
    } }, o.unknownLabel);
    chips.append(c);
  }
  const search = el("input", { type: "search", placeholder: o.searchLabel, "aria-label": o.searchLabel, oninput: () => { state.q = search.value.trim().toLowerCase(); draw(); } });
  const zoom = el("span", { class: "zoom" },
    el("button", { type: "button", "aria-label": "縮小", onclick: () => zoomAt(state.scale / 1.25) }, "−"),
    pct,
    el("button", { type: "button", "aria-label": "拡大", onclick: () => zoomAt(state.scale * 1.25) }, "+"),
    el("button", { type: "button", title: "できるだけ横幅に合わせる (5% でも収まらない分は横スクロール)", onclick: () => { state.manual = false; state.fitAll = true; fit(); } }, "全体"),
    el("button", { type: "button", onclick: () => zoomAt(1) }, "100%"));
  const toolbar = el("div", { class: "toolbar" }, search, chips, count, zoom, fullBtn);
  const legend = el("div", { class: "fbox-legend" });
  const aside = el("div", { class: "fbox-foot" }); // 図の下 (倍率の外)。draw が返す aside (辺の一覧など) を置く
  const box = el("div", { class: "fbox", role: "group", "aria-label": o.title }, toolbar, view, legend, aside);

  // 凡例のスウォッチは実際の図と同じクラスで描く (見た目と凡例がずれない)。線には矢じりも付ける
  let keySerial = 0;
  function swatch(cls) {
    const sw = svg("svg", { viewBox: "0 0 28 14", width: 28, height: 14, "aria-hidden": "true" });
    const isBox = /^(node|life)\b/.test(cls);
    if (!isBox) sw.append(arrowDefs(`${marker}-key-${++keySerial}`));
    sw.append(svg("g", { class: cls }, isBox ? svg("rect", { x: 1, y: 1, width: 26, height: 12, rx: 2 }) : svg("path", { d: "M 1 7 H 24", "marker-end": markerFor(`${marker}-key-${keySerial}`, /\bunknown\b/.test(cls)) })));
    return sw;
  }
  // 強調表示 (data-n / data-e / data-f / data-t を draw が付ける)
  let pinned = null;
  function clearFocus() {
    box.classList.remove("fb-focus");
    for (const x of view.querySelectorAll(".on, .cur")) x.classList.remove("on", "cur");
    for (const x of view.querySelectorAll("[data-mk]")) { x.setAttribute("marker-end", x.dataset.mk); delete x.dataset.mk; } // 矢じりを元に戻す
  }
  function focusOn(target) {
    clearFocus();
    const nodesOn = new Set(), edgesOn = new Set();
    if (target.dataset.n != null) {
      nodesOn.add(target.dataset.n);
      for (const e of view.querySelectorAll("[data-e]")) if (e.dataset.f === target.dataset.n || e.dataset.t === target.dataset.n) { edgesOn.add(e.dataset.e); nodesOn.add(e.dataset.f); nodesOn.add(e.dataset.t); }
    } else { edgesOn.add(target.dataset.e); nodesOn.add(target.dataset.f); nodesOn.add(target.dataset.t); }
    for (const x of view.querySelectorAll("[data-n]")) { if (nodesOn.has(x.dataset.n)) x.classList.add("on"); if (x.dataset.n === target.dataset.n) x.classList.add("cur"); }
    for (const x of view.querySelectorAll("[data-e]")) if (edgesOn.has(x.dataset.e)) x.classList.add("on");
    for (const x of view.querySelectorAll("[data-e].on [marker-end]")) { if (!x.dataset.mk) x.dataset.mk = x.getAttribute("marker-end"); x.setAttribute("marker-end", `url(#${marker}-on)`); } // 強調中は矢じりも墨に
    box.classList.add("fb-focus");
  }
  const keyOf = (t) => (t.dataset.n != null ? `n:${t.dataset.n}` : `e:${t.dataset.e}`);
  function installFocus() {
    pinned = null;
    clearFocus();
    for (const x of (head || body).querySelectorAll("[data-n]")) { x.setAttribute("tabindex", "0"); x.setAttribute("role", "button"); } // Tab は箱だけ (見出しがあれば見出しの箱だけ。辺は数百本あると実用にならない。辺の内容はキーボードでは一覧から)
  }
  view.addEventListener("pointerover", (ev) => { if (ev.pointerType !== "mouse" || pinned) return; const t = ev.target.closest("[data-n], [data-e]"); if (t) focusOn(t); });
  view.addEventListener("pointerout", (ev) => { if (ev.pointerType !== "mouse" || pinned) return; const t = ev.target.closest("[data-n], [data-e]"); if (t && !(ev.relatedTarget && t.contains(ev.relatedTarget))) clearFocus(); });
  view.addEventListener("click", (ev) => {
    if (ev.target.closest("a")) return; // リンクはそのまま
    const t = ev.target.closest("[data-n], [data-e]");
    if (!t || keyOf(t) === pinned) { pinned = null; clearFocus(); return; }
    pinned = keyOf(t);
    focusOn(t);
  });
  view.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    if (ev.target.closest && ev.target.closest("a")) return; // リンクの上の Enter はリンクを優先
    const t = ev.target.closest && ev.target.closest("[data-n], [data-e]");
    if (!t) return;
    ev.preventDefault();
    t.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });

  let natural = { w: 0, headH: 0, bodyH: 0 };
  const countText = (c) => `${o.nouns[0]} ${c[0]} / ${o.totals[0]} · ${o.nouns[1]} ${c[1]} / ${o.totals[1]}`;
  function draw() {
    if (head) head.replaceChildren();
    body.replaceChildren();
    const wasOpen = !!aside.querySelector("details[open]"); // 開いていた一覧は絞り込み後も開いたまま
    aside.replaceChildren();
    const r = o.draw(state, marker);
    if (!r) { count.textContent = countText([0, 0]); body.append(emptyMsg("絞り込みに合うものが無い")); legend.replaceChildren(); natural = { w: 0, headH: 0, bodyH: 0 }; installFocus(); apply(); return; }
    if (head && r.head) head.append(r.head);
    body.append(r.body);
    natural = { w: r.w, headH: r.headH || 0, bodyH: r.bodyH };
    if (r.aside) { aside.append(r.aside); if (wasOpen && r.aside.tagName === "DETAILS") r.aside.open = true; }
    legend.replaceChildren(...(r.legend || []).map(([cls, label]) => el("span", { class: "key" }, swatch(cls), label)),
      el("span", { class: "key hint" }, "箱や矢印に触れるとつながりだけ濃く残る (タップで固定)"));
    installFocus();
    count.textContent = countText(r.counts);
    if (state.manual) apply(); else fit();
  }
  function apply() {
    const s = state.scale;
    for (const [wrap, h] of [[head, natural.headH], [body, natural.bodyH]]) {
      const sv = wrap && wrap.querySelector("svg");
      if (!sv) continue;
      sv.setAttribute("width", String(Math.max(1, Math.round(natural.w * s))));
      sv.setAttribute("height", String(Math.max(1, Math.round(h * s))));
    }
    pct.textContent = `${Math.round(s * 100)}%`;
    for (const mk of view.querySelectorAll("marker")) { const size = String(Math.round((7 / s) * 10) / 10); mk.setAttribute("markerWidth", size); mk.setAttribute("markerHeight", size); } // 矢じりも線と同じく画面上の大きさを保つ
    edges();
  }
  function setScale(s, manual) {
    state.scale = Math.min(4, Math.max(0.05, s));
    if (manual) state.manual = true;
    apply();
  }
  // 倍率を変えても、表示領域の点 (px, py。省略時は中心) の下にある図の点を動かさない
  function zoomAt(s, px, py) {
    if (px == null) { px = scroller.clientWidth / 2; py = scroller.clientHeight / 2; }
    const before = state.scale;
    setScale(s, true);
    const f = state.scale / before;
    scroller.scrollLeft = (scroller.scrollLeft + px) * f - px;
    scroller.scrollTop = (scroller.scrollTop + py) * f - py;
  }
  function fit() {
    const avail = scroller.clientWidth;
    if (!avail || !natural.w) { state.scale = 1; apply(); return; }
    const before = state.scale;
    const s = (avail - 2) / natural.w;
    // 横幅に合わせると文字が読めなくなる図 (50% 未満) は、読める倍率 (60%) で左上から始める。全体の形は「全体」のボタンで見る
    state.scale = s >= 0.5 || state.fitAll ? Math.max(0.05, Math.min(1, s)) : 0.6; // 手動と同じ最小倍率。収まらない分は枠内スクロール
    apply();
    scroller.scrollTop = scroller.scrollTop * (state.scale / before); // 縦の位置は比率で保つ (横は収まるので 0 のまま)
  }
  function edges() {
    box.classList.toggle("more-l", scroller.scrollLeft > 1);
    box.classList.toggle("more-r", scroller.scrollLeft + scroller.clientWidth < scroller.scrollWidth - 1);
    box.classList.toggle("more-b", scroller.scrollTop + scroller.clientHeight < scroller.scrollHeight - 1);
  }
  function onKey(ev) { if (ev.key === "Escape") setFull(false); }
  let inerted = [];
  function setFull(on) {
    if (on === state.full) return;
    state.full = on;
    box.classList.toggle("full", on);
    document.body.classList.toggle("fbox-full-open", on);
    fullBtn.textContent = on ? "全画面を閉じる (Esc)" : "全画面";
    if (on) {
      document.addEventListener("keydown", onKey);
      // 背後 (祖先の兄弟) をキーボード操作の対象から外す
      for (let n = box; n && n !== document.body; n = n.parentElement) {
        for (const sib of n.parentElement ? n.parentElement.children : []) if (sib !== n && !sib.inert) { sib.inert = true; inerted.push(sib); }
      }
    } else {
      document.removeEventListener("keydown", onKey);
      for (const n of inerted) n.inert = false;
      inerted = [];
      fullBtn.focus();
    }
    if (!state.manual) requestAnimationFrame(fit); else requestAnimationFrame(edges);
  }
  let ro = null;
  function destroy() {
    if (state.full) setFull(false);
    if (ro) { ro.disconnect(); ro = null; }
    window.removeEventListener("hashchange", onRoute);
  }
  function onRoute() { if (!box.isConnected) destroy(); else if (state.full) setFull(false); } // 経路が変わったら全画面は閉じる
  window.addEventListener("hashchange", onRoute);
  scroller.addEventListener("scroll", edges, { passive: true });
  scroller.addEventListener("wheel", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey)) return; // ふつうのホイールはスクロール
    ev.preventDefault();
    const rect = scroller.getBoundingClientRect();
    zoomAt(state.scale * (ev.deltaY < 0 ? 1.1 : 1 / 1.1), ev.clientX - rect.left, ev.clientY - rect.top); // カーソルの下の点を動かさない
  }, { passive: false });
  if (typeof ResizeObserver === "function") { ro = new ResizeObserver(() => { if (!box.isConnected) { destroy(); return; } if (!state.manual) fit(); else edges(); }); ro.observe(scroller); }
  draw();
  requestAnimationFrame(() => { if (!state.manual) fit(); }); // DOM に載ってから幅が決まる
  return box;
}
