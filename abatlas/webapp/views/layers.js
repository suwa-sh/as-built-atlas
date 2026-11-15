// 表示の部品: architecture の図 (SVG)。layer を箱にして tier (frontend / backend など) の枠に入れ、実際の呼び出しと読み書きの線でつなぐ。
// 上の段 = layer (左から呼ぶ側)。下の段 = datastore の kind と external API (group ごとに枠を分ける)。となりの層への線はまっすぐ、層を飛ばす線・戻る線は上を回る弧、データへの線は下へ降りる
//   layerDiagram({ columns: [[node, …], …], stores: [node, …], edges: [{ from, to, n, unknown }], label })。unknown の線は点線
//   返す svg は applyFilter({ q, unknownOnly }) を持つ。名前が合う箱につながる線 (unknownOnly なら unknown を含む線) だけ濃く残し、{ shown, total } (線の数) を返す。箱の位置は動かさない
//   node = { id, name, sub, group, cls, href }。group = 図の枠の名前 (上の段は分析の型の layers[].tier、下の段は datastore / external)。columns の 1 列に複数の箱を置ける (entry point の layer)。group が同じで隣り合う列・隣り合う stores は 1 つの枠に入る

import { svg, fmt } from "../lib/dom.js";
import { arrowDefs } from "./figure-box.js";

const W = 152, H = 54, GX = 74, GY = 14; // 箱の幅・高さ、列の間、同じ列の箱の間
const SW = 132, SG = 20; // データの箱の幅と間
const PAD = 18, GLAB = 26; // 枠の内側の余白、枠の名前の分 (名前は枠の下の端に置く。上は線が通るため)
let serial = 0;

export function layerDiagram(o) {
  const id = `ly${++serial}`;
  const pos = new Map(); // id -> { x, y, w, h, col, store }
  const rows = Math.max(1, ...o.columns.map((c) => c.length));
  const span = Math.max(0, ...o.edges.map((e) => { const a = colOf(o, e.from), b = colOf(o, e.to); return a >= 0 && b >= 0 && Math.abs(a - b) !== 1 ? Math.abs(a - b) : 0; }));
  const arcTop = span ? (34 + span * 16) * 0.75 + 20 : 0; // 弧のための上の空き (弧の頂点は、持ち上げた高さの 3/4)
  const colH = rows * H + (rows - 1) * GY;
  const top = 8 + arcTop + PAD;
  o.columns.forEach((col, ci) => {
    const h = col.length * H + (col.length - 1) * GY;
    col.forEach((n, ri) => pos.set(n.id, { x: PAD + 8 + ci * (W + GX), y: top + (colH - h) / 2 + ri * (H + GY), w: W, h: H, col: ci, row: ri }));
  });
  const tiersW = o.columns.length * W + (o.columns.length - 1) * GX;
  const storeTop = top + colH + PAD + GLAB + 104;
  // 下の段の箱は group (datastore / external) ごとに枠を分け、枠の間を広めに空ける
  const ZG = PAD * 2 + 14;
  const sgroups = [];
  for (const n of o.stores) { const last = sgroups[sgroups.length - 1]; if (last && last.name === (n.group || "")) last.items.push(n); else sgroups.push({ name: n.group || "", items: [n] }); }
  const storesW = o.stores.length * SW + sgroups.reduce((a, g) => a + (g.items.length - 1) * SG, 0) + Math.max(0, sgroups.length - 1) * ZG;
  const sx0 = PAD + 8 + Math.max(0, (tiersW - storesW) / 2);
  let sx = sx0;
  for (const g of sgroups) {
    g.x = sx;
    for (const n of g.items) { pos.set(n.id, { x: sx, y: storeTop + PAD, w: SW, h: H, store: true }); sx += SW + SG; }
    g.w = sx - SG - g.x;
    sx += ZG - SG;
  }
  const width = PAD * 2 + 16 + Math.max(tiersW, storesW);
  const height = (o.stores.length ? storeTop + PAD + H + PAD + GLAB : top + colH + PAD + GLAB) + 8;

  // 区分の枠 (group が同じで隣り合う列をまとめる)
  const groups = [];
  o.columns.forEach((col, ci) => {
    const z = col[0] && col[0].group;
    if (!z) return;
    const last = groups[groups.length - 1];
    if (last && last.name === z && last.to === ci - 1) last.to = ci; else groups.push({ name: z, from: ci, to: ci });
  });
  const groupEls = groups.map((z) => {
    const x = PAD + 8 + z.from * (W + GX) - PAD, w = (z.to - z.from + 1) * W + (z.to - z.from) * GX + PAD * 2;
    return svg("g", { class: "group" }, svg("rect", { x, y: top - PAD, width: w, height: colH + PAD * 2 + GLAB, rx: 6 }), svg("text", { x: x + 12, y: top + colH + PAD + GLAB - 9 }, z.name));
  });
  for (const g of sgroups) groupEls.push(svg("g", { class: "group" }, svg("rect", { x: g.x - PAD, y: storeTop, width: g.w + PAD * 2, height: PAD * 2 + H + GLAB, rx: 6 }), svg("text", { x: g.x - PAD + 12, y: storeTop + PAD + H + PAD + GLAB - 9 }, g.name)));

  // 線。重みで太さを 3 段に分ける
  const max = Math.max(1, ...o.edges.map((e) => e.n));
  // 重ねた箱の 2 段目以降から出る弧は、上の箱を突き抜けないよう下を回す
  const kindOfEdge = (a, b) => (b.store ? "down" : b.col === a.col + 1 ? "next" : b.col === a.col ? "side" : a.row > 0 || b.row > 0 ? "under" : "arc");
  const live = o.edges.filter((e) => pos.get(e.from) && pos.get(e.to) && e.from !== e.to).map((e) => ({ ...e, a: pos.get(e.from), b: pos.get(e.to) })).map((e) => ({ ...e, kind: kindOfEdge(e.a, e.b) }));
  // 辺 (箱 + 上か下) ごとに、そこを使う線を相手の x の順に並べ、番号を振る
  const slots = new Map();
  const slot = (key, e, otherX) => { if (!slots.has(key)) slots.set(key, []); slots.get(key).push({ e, otherX }); };
  for (const e of live) {
    if (e.kind === "down") { slot(e.from + "|bottom", e, e.b.x); slot(e.to + "|top", e, e.a.x); }
    if (e.kind === "arc") { slot(e.from + "|top", e, e.b.x); slot(e.to + "|top", e, e.a.x); }
    if (e.kind === "under") { slot(e.from + "|bottom", e, e.b.x); slot(e.to + "|bottom", e, e.a.x); }
  }
  const at = (key, e, box) => {
    const list = slots.get(key).sort((p, q) => p.otherX - q.otherX);
    const i = list.findIndex((x) => x.e === e), n = list.length;
    const step = Math.min(22, (box.w - 28) / Math.max(1, n - 1));
    return box.x + box.w / 2 + (i - (n - 1) / 2) * step;
  };
  const edgeEls = live.map((e) => {
    const a = e.a, b = e.b;
    let d, lx, ly;
    if (e.kind === "down") { // 下へ降りる。数字は着く側の箱のすぐ上
      const x1 = at(e.from + "|bottom", e, a), y1 = a.y + a.h, x2 = at(e.to + "|top", e, b), y2 = b.y;
      const my = (y1 + y2) / 2;
      d = `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`;
      lx = x2 + (x1 < x2 ? -4 : x1 > x2 ? 4 : 0); ly = y2 - 20;
    } else if (e.kind === "side") { // 同じ列の箱どうし: 左を回る
      const y1 = a.y + a.h / 2, y2 = b.y + b.h / 2;
      d = `M ${a.x} ${y1} C ${a.x - 26} ${y1}, ${b.x - 26} ${y2}, ${b.x} ${y2}`;
      lx = a.x - 12; ly = (y1 + y2) / 2 + 4;
    } else if (e.kind === "next") { // となりの層へ
      const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
      const mx = (x1 + x2) / 2;
      d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
      lx = mx; ly = (y1 + y2) / 2 - 6;
    } else if (e.kind === "under") { // 重ねた箱の下の段から: 下を回る
      const x1 = at(e.from + "|bottom", e, a), x2 = at(e.to + "|bottom", e, b);
      const y1 = a.y + a.h, y2 = b.y + b.h, drop = 26 + Math.abs(b.col - a.col) * 10;
      const yBot = Math.max(y1, y2) + drop;
      d = `M ${x1} ${y1} C ${x1} ${yBot}, ${x2} ${yBot}, ${x2} ${y2}`;
      lx = (x1 + x2) / 2; ly = Math.max(y1, y2) + drop * 0.75 + 12;
    } else { // 層を飛ばす・戻る: 上を回る
      const x1 = at(e.from + "|top", e, a), x2 = at(e.to + "|top", e, b);
      const lift = 34 + Math.abs(b.col - a.col) * 16;
      const yTop = Math.min(a.y, b.y) - lift;
      d = `M ${x1} ${a.y} C ${x1} ${yTop}, ${x2} ${yTop}, ${x2} ${b.y}`;
      lx = (x1 + x2) / 2; ly = Math.min(a.y, b.y) - lift * 0.75 - 4;
    }
    const wt = e.n / max > 0.5 ? "w3" : e.n / max > 0.12 ? "w2" : "w1";
    return svg("g", { class: `edge ${wt}${e.unknown ? " unknown" : ""}`, "data-f": e.from, "data-t": e.to },
      svg("path", { d, "marker-end": `url(#${id})` }),
      svg("text", { x: lx, y: ly, "text-anchor": "middle", class: "num" }, fmt(e.n)));
  });

  const nodeEls = [...o.columns.flat(), ...o.stores].map((n) => {
    const p = pos.get(n.id);
    const box = svg("g", { class: `node ${p.store ? "store" : "layer"}${n.cls ? " " + n.cls : ""}`, "data-n": n.id, tabindex: n.href ? null : "0" },
      svg("title", null, n.title || n.name),
      svg("rect", { x: p.x, y: p.y, width: p.w, height: p.h, rx: p.store ? 4 : 6 }),
      svg("text", { x: p.x + 12, y: p.y + 22, class: "nm" }, n.name),
      n.sub ? svg("text", { x: p.x + 12, y: p.y + 40, class: "sb" }, n.sub) : null);
    return n.href ? svg("a", { href: n.href }, box) : box;
  });

  const root = svg("svg", { class: "layers", viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": o.label || "" },
    arrowDefs(id), groupEls, edgeEls, nodeEls);
  // 箱に触れる・フォーカスすると、つながる線と箱だけ濃く残す
  const focus = (nid) => {
    root.classList.toggle("focus", nid != null);
    for (const g of root.querySelectorAll("[data-f]")) g.classList.toggle("on", nid != null && (g.dataset.f === nid || g.dataset.t === nid));
    const near = new Set([nid]);
    for (const g of root.querySelectorAll("[data-f].on")) { near.add(g.dataset.f); near.add(g.dataset.t); }
    for (const g of root.querySelectorAll("[data-n]")) g.classList.toggle("on", nid != null && near.has(g.dataset.n));
  };
  for (const g of root.querySelectorAll("[data-n]")) {
    const t = g.closest("a") || g;
    t.addEventListener("pointerenter", () => focus(g.dataset.n));
    t.addEventListener("pointerleave", () => focus(null));
    t.addEventListener("focus", () => focus(g.dataset.n));
    t.addEventListener("blur", () => focus(null));
  }
  // 絞り込み。合わない箱と線は薄くするだけで、並びは変えない (図の形を覚えたまま読める)
  const names = new Map([...o.columns.flat(), ...o.stores].map((n) => [n.id, `${n.id} ${n.name} ${n.title || ""}`.toLowerCase()]));
  root.applyFilter = ({ q, unknownOnly }) => {
    const active = !!q || !!unknownOnly;
    const hit = (nid) => !!q && (names.get(nid) || "").includes(q);
    const keep = new Set();
    let shown = 0;
    for (const g of root.querySelectorAll("[data-f]")) {
      const ok = active && (!q || hit(g.dataset.f) || hit(g.dataset.t)) && (!unknownOnly || g.classList.contains("unknown"));
      g.classList.toggle("keep", ok);
      if (ok) { shown++; keep.add(g.dataset.f); keep.add(g.dataset.t); }
    }
    for (const g of root.querySelectorAll("[data-n]")) g.classList.toggle("keep", active && (keep.has(g.dataset.n) || hit(g.dataset.n)));
    root.classList.toggle("filter", active);
    return { shown: active ? shown : live.length, total: live.length };
  };
  return root;
}

function colOf(o, nid) { return o.columns.findIndex((c) => c.some((n) => n.id === nid)); }
