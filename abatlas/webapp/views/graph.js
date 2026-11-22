// 表示の種類: 有向グラフ (view: graph)

import { el, svg, fmt, short } from "../lib/dom.js";
import { titleOf, labelOf } from "../model/catalog.js";
import { kindOfNode, passesFilter } from "../model/kinds.js";
import { emptyMsg } from "../ui/card.js";
import { linkValue, hrefFor } from "../ui/link.js";
import { figureBox, arrowDefs, markerFor, elbow } from "./figure-box.js";
import { term } from "../model/vocab.js";

export function graph(m, data, ctx) {
  const k = m.keys;
  const rows = graphRows(data, k);
  if (!rows.length) return emptyMsg("図に描くつながりが無い (該当する行が 0 件)");
  const here = ctx && ctx.here;
  const allNodes = new Set(rows.flatMap((e) => [e.from, e.to]));
  return figureBox({
    title: titleOf(m),
    nouns: ["箱", "矢印"],
    totals: [allNodes.size, rows.length],
    present: new Set([...allNodes].map(kindOfNode)),
    hasUnknown: rows.some((e) => e.status === "unknown"),
    unknownLabel: `${term("unknown")} の矢印だけ`,
    searchLabel: "箱の名前で絞る",
    filterMode: "both",
    draw(state, marker) {
      const vis = rows.filter((e) => passesFilter(state, e.from, e.to, e.status));
      if (!vis.length) return null;
      const g = layoutGraph(vis);
      const root = drawGraph(m, g, marker, here);
      return {
        body: root,
        w: g.width,
        bodyH: g.height,
        counts: [g.nodes.length, vis.length],
        aside: edgeList(
          m,
          vis.map((e) => e.raw),
          data.columns,
          "矢印の一覧",
        ),
        legend: [
          ["node entry", term("entry")],
          ["node ext", term("datastore")],
          ["node ext external", term("external")],
          ["edge", `確かめた ${term("data_access")}`],
          ["edge unknown", `${term("unknown")} を含む矢印 (点線)`],
          ["edge back", "戻る矢印 (図の上を通る)"],
        ],
      };
    },
  });
}
function graphRows(data, k) {
  return data.rows
    .filter((r) => r[k.from] != null && r[k.to] != null)
    .map((r) => ({
      from: String(r[k.from]),
      to: String(r[k.to]),
      label: k.label ? r[k.label] : null,
      status: k.status ? r[k.status] : null,
      raw: r,
    }));
}

const W = 230,
  H = 36,
  GAP = 96,
  GX = W + GAP,
  ROWGAP = 16,
  PAD = 24,
  LANE = 12,
  PITCH = 10; // PITCH = 箱に付く点の最小間隔。辺の多い箱は縦に伸ばす

// ------------------------------------------------------------ 有向グラフの配置と描画
// 同じ両端の辺は 1 本にまとめる (ラベルは列挙、不明を含めば薄い色)。層は入口側から辿った最長路。層の中の順番は隣の層のつながり先の重心で並べ替え (往復 4 回)。
// 層は縦に中央揃え。線は角を丸めた直角 (r = 8): 箱の辺に付く点は辺ごとにずらし、層の間の縦線は重ならないレーンに割り当てる。戻る辺 (循環) は図の上を通す
export function layoutGraph(vis) {
  const edges = mergeEdges(vis);
  const nodes = adjacency(edges);
  const { layers, layer } = graphLayers(nodes);
  // 重心法: 隣の層でのつながり先の位置の平均で並べ替える。左 → 右、右 → 左を 4 往復
  orderGraphLayers(layers, nodes);
  const back = edges.filter((e) => layer.get(e.to) <= layer.get(e.from));
  const fwd = edges.filter((e) => layer.get(e.to) > layer.get(e.from));
  const top = PAD + (back.length ? 10 + back.length * LANE : 0); // 戻る辺の分だけ上を空ける
  // 箱の高さ: 片側に付く辺の数 × 間隔 を確保する (辺の多い入口は縦に伸びる)
  const { tallest, layerH, hts } = measureNodes(fwd, nodes, layers);
  const pos = positionNodes(layers, top, tallest, layerH, hts);
  // 箱の辺に付く点: 出る辺は右辺、入る辺は左辺に、つながり先の高さの順に等間隔
  assignForwardPorts(fwd, pos, hts);
  // 層の間の縦線のレーン: 縦の区間が重ならないように詰める (区間の走査)
  routeGapLanes(fwd, layer);
  back.forEach((e, i) => {
    e.yTop = top - 10 - (i + 1) * LANE;
  });
  // 戻る辺が箱の上辺に付く点も、箱ごとに等間隔にずらす (出る側は右寄り、入る側は左寄りの範囲)
  assignBackPorts(back, pos);
  const width = PAD * 2 + (layers.length - 1) * GX + W;
  const height = top + tallest + PAD;
  return { nodes: [...nodes.keys()], layers, pos, hts, fwd, back, width, height, W, GX, GAP };
}
function mergeEdges(vis) {
  const merged = new Map();
  for (const e of vis) {
    const key = `${e.from}\u0000${e.to}`;
    if (!merged.has(key))
      merged.set(key, { from: e.from, to: e.to, labels: [], unknown: false, rows: [] });
    const me = merged.get(key);
    if (e.label != null && e.label !== "" && !me.labels.includes(String(e.label)))
      me.labels.push(String(e.label));
    if (e.status === "unknown") me.unknown = true;
    me.rows.push(e);
  }
  const edges = [...merged.values()];
  return edges;
}

function adjacency(edges) {
  const nodes = new Map();
  const add = (id) => {
    if (!nodes.has(id)) nodes.set(id, { id, out: new Set(), in: new Set() });
    return nodes.get(id);
  };
  for (const e of edges) {
    add(e.from).out.add(e.to);
    add(e.to).in.add(e.from);
  }
  return nodes;
}

function graphLayers(nodes) {
  const layer = new Map(),
    onstack = new Set();
  function depth(id) {
    if (layer.has(id)) return layer.get(id);
    if (onstack.has(id)) return 0;
    onstack.add(id);
    let d = 0;
    for (const p of nodes.get(id).in) d = Math.max(d, depth(p) + 1);
    onstack.delete(id);
    layer.set(id, d);
    return d;
  }
  for (const id of nodes.keys()) depth(id);
  const layers = [];
  for (const id of nodes.keys()) {
    const d = layer.get(id);
    (layers[d] = layers[d] || []).push(id);
  }
  for (let i = 0; i < layers.length; i++) layers[i] = layers[i] || [];
  return { layers, layer };
}

function orderGraphLayers(layers, nodes) {
  const posIn = new Map();
  const index = () => layers.forEach((ids) => ids.forEach((id, i) => posIn.set(id, i)));
  const bary = (id, neigh) => {
    const ps = [...neigh].filter((n) => posIn.has(n)).map((n) => posIn.get(n));
    return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : posIn.get(id);
  };
  index();
  for (let round = 0; round < 4; round++) {
    orderByParents(layers, bary, nodes, posIn, index);
    for (let L = layers.length - 2; L >= 0; L--) {
      layers[L].sort(
        (a, b) =>
          bary(a, nodes.get(a).out) - bary(b, nodes.get(b).out) || posIn.get(a) - posIn.get(b),
      );
      index();
    }
  }
}

function orderByParents(layers, bary, nodes, posIn, index) {
  for (let L = 1; L < layers.length; L++) {
    layers[L].sort(
      (a, b) => bary(a, nodes.get(a).in) - bary(b, nodes.get(b).in) || posIn.get(a) - posIn.get(b),
    );
    index();
  }
}

function measureNodes(fwd, nodes, layers) {
  const degOut = new Map(),
    degIn = new Map();
  for (const e of fwd) {
    degOut.set(e.from, (degOut.get(e.from) || 0) + 1);
    degIn.set(e.to, (degIn.get(e.to) || 0) + 1);
  }
  const hts = new Map(
    [...nodes.keys()].map((id) => [
      id,
      Math.max(H, PITCH * (Math.max(degOut.get(id) || 0, degIn.get(id) || 0) + 1)),
    ]),
  );
  const layerH = (ids) =>
    ids.reduce((sum, id) => sum + hts.get(id), 0) + Math.max(0, ids.length - 1) * ROWGAP;
  const tallest = Math.max(...layers.map(layerH));
  return { tallest, layerH, hts };
}

function positionNodes(layers, top, tallest, layerH, hts) {
  const pos = new Map();
  layers.forEach((ids, L) => {
    let y = top + (tallest - layerH(ids)) / 2; // 縦に中央揃え
    for (const id of ids) {
      pos.set(id, { x: PAD + L * GX, y });
      y += hts.get(id) + ROWGAP;
    }
  });
  return pos;
}

function assignForwardPorts(fwd, pos, hts) {
  const outs = new Map(),
    ins = new Map();
  for (const e of fwd) {
    (outs.get(e.from) || outs.set(e.from, []).get(e.from)).push(e);
    (ins.get(e.to) || ins.set(e.to, []).get(e.to)).push(e);
  }
  for (const [id, list] of outs) {
    list.sort((a, b) => pos.get(a.to).y - pos.get(b.to).y);
    list.forEach((e, i) => {
      e.ya = pos.get(id).y + (hts.get(id) * (i + 1)) / (list.length + 1);
    });
  }
  for (const [id, list] of ins) {
    list.sort((a, b) => pos.get(a.from).y - pos.get(b.from).y);
    list.forEach((e, i) => {
      e.yb = pos.get(id).y + (hts.get(id) * (i + 1)) / (list.length + 1);
    });
  }
}

function routeGapLanes(fwd, layer) {
  const gaps = new Map();
  for (const e of fwd) {
    const g = layer.get(e.from);
    (gaps.get(g) || gaps.set(g, []).get(g)).push(e);
  }
  for (const [g, list] of gaps) {
    const need = list
      .filter((e) => Math.abs(e.yb - e.ya) >= 1)
      .sort((a, b) => Math.min(a.ya, a.yb) - Math.min(b.ya, b.yb));
    const laneEnd = [];
    for (const e of need) {
      const lo = Math.min(e.ya, e.yb) - 4,
        hi = Math.max(e.ya, e.yb) + 4;
      let lane = laneEnd.findIndex((end) => end < lo);
      if (lane < 0) {
        lane = laneEnd.length;
        laneEnd.push(hi);
      } else laneEnd[lane] = hi;
      e.lane = lane;
    }
    const n = laneEnd.length;
    const x0 = PAD + g * GX + W;
    for (const e of need) e.lx = x0 + (GAP * (e.lane + 1)) / (n + 1);
  }
}

function assignBackPorts(back, pos) {
  const topOut = new Map(),
    topIn = new Map();
  for (const e of back) {
    (topOut.get(e.from) || topOut.set(e.from, []).get(e.from)).push(e);
    (topIn.get(e.to) || topIn.set(e.to, []).get(e.to)).push(e);
  }
  for (const [id, list] of topOut) {
    list.sort((a, b) => pos.get(a.to).x - pos.get(b.to).x);
    list.forEach((e, i) => {
      e.sx = pos.get(id).x + W * 0.5 + (W * 0.5 * (i + 1)) / (list.length + 1);
    });
  }
  for (const [id, list] of topIn) {
    list.sort((a, b) => pos.get(a.from).x - pos.get(b.from).x);
    list.forEach((e, i) => {
      e.tx = pos.get(id).x + (W * 0.5 * (i + 1)) / (list.length + 1);
    });
  }
}

export function drawGraph(m, g, marker, here) {
  const { W } = g;
  const root = svg("svg", { viewBox: `0 0 ${g.width} ${g.height}`, role: "img" });
  root.append(svg("title", null, titleOf(m)));
  root.append(arrowDefs(marker));
  const { outDeg, inDeg } = edgeDegrees(g);
  drawForwardEdges(g, W, marker, outDeg, inDeg, root);
  drawBackEdges(g, marker, root);
  drawNodes(g, here, W, root);
  return root;
}
function edgeDegrees(g) {
  const outDeg = new Map(),
    inDeg = new Map();
  for (const e of g.fwd) {
    outDeg.set(e.from, (outDeg.get(e.from) || 0) + 1);
    inDeg.set(e.to, (inDeg.get(e.to) || 0) + 1);
  }
  return { outDeg, inDeg };
}

const edgeTitle = (e) =>
  `${e.from} → ${e.to}${e.labels.length ? ` (${e.labels.join(", ")})` : ""}${e.unknown ? ` [${term("unknown")} を含む]` : ""}`;

function drawForwardEdges(g, W, marker, outDeg, inDeg, root) {
  for (const e of g.fwd) {
    const a = g.pos.get(e.from),
      b = g.pos.get(e.to);
    const x1 = a.x + W,
      x2 = b.x;
    const d = e.lx == null ? elbow(x1, e.ya, x1, x2, e.yb) : elbow(x1, e.ya, e.lx, x2, e.yb);
    const el2 = svg(
      "g",
      {
        class: `edge${e.unknown ? " unknown" : ""}`,
        "data-e": `f${g.fwd.indexOf(e)}`,
        "data-f": e.from,
        "data-t": e.to,
      },
      svg("path", { d, "marker-end": markerFor(marker, e.unknown) }),
    );
    if (e.labels.length) {
      // ラベルは辺の少ない側 (入口は辺が多いので、たいていデータ側) に置き、線から 6px 離す
      const nearSource = (outDeg.get(e.from) || 0) <= (inDeg.get(e.to) || 0);
      el2.append(
        nearSource
          ? svg("text", { x: x1 + 6, y: e.ya - 6, "text-anchor": "start" }, e.labels.join(", "))
          : svg("text", { x: x2 - 6, y: e.yb - 6, "text-anchor": "end" }, e.labels.join(", ")),
      );
    }
    el2.append(svg("title", null, edgeTitle(e)));
    root.append(el2);
  }
}

function drawBackEdges(g, marker, root) {
  for (const e of g.back) {
    // 戻る辺: 出る箱の上から上空のレーンへ、入る箱の上へ降りる
    const a = g.pos.get(e.from),
      b = g.pos.get(e.to);
    const sx = e.sx,
      tx = e.tx,
      y = e.yTop,
      r = 8;
    const dir = tx > sx ? 1 : -1;
    const d = `M ${sx} ${a.y} V ${y + r} Q ${sx} ${y} ${sx + dir * r} ${y} H ${tx - dir * r} Q ${tx} ${y} ${tx} ${y + r} V ${b.y}`;
    const el2 = svg(
      "g",
      {
        class: `edge back${e.unknown ? " unknown" : ""}`,
        "data-e": `b${g.back.indexOf(e)}`,
        "data-f": e.from,
        "data-t": e.to,
      },
      svg("path", { d, "marker-end": markerFor(marker, e.unknown) }),
    );
    if (e.labels.length)
      el2.append(
        svg("text", { x: (sx + tx) / 2, y: y - 6, "text-anchor": "middle" }, e.labels.join(", ")),
      );
    el2.append(svg("title", null, edgeTitle(e)));
    root.append(el2);
  }
}

function drawNodes(g, here, W, root) {
  for (const [id, p] of g.pos) {
    const kind = kindOfNode(id);
    const isHere = here === id;
    const h = g.hts.get(id);
    const node = svg(
      "g",
      {
        class: `node${kind === "data" ? " ext" : kind === "external" ? " ext external" : " entry"}${isHere ? " here" : ""}`,
        "data-n": id,
      },
      svg("rect", { x: p.x, y: p.y, width: W, height: h, rx: 4 }),
      svg("title", null, isHere ? `${id} (この ${term("entry")})` : id),
    );
    const t = svg(
      "text",
      { x: p.x + 8, y: p.y + h / 2 + 4 },
      isHere ? `◀ ${short(id, 30)}` : short(id, 36),
    ); // 現在の入口は色だけでなく印と太い枠で示す
    const href = hrefFor(id);
    if (href) {
      const a = svg("a", { href });
      a.append(t);
      node.append(a);
    } else node.append(t);
    root.append(node);
  }
}

// 図の下に付ける辺 (メッセージ) の一覧 (キーボードと読み上げで内容に到達できる。絞り込みと同期)。rows は mart の行そのもの
export function edgeList(m, rows, columns, title) {
  const k = m.keys;
  const cols = columns.filter((c) => [k.seq, k.from, k.to, k.label, k.status].includes(c));
  const table = el(
    "table",
    { class: "grid" },
    el(
      "thead",
      null,
      el(
        "tr",
        null,
        cols.map((c) => el("th", null, labelOf(m, c))),
      ),
    ),
    el(
      "tbody",
      null,
      rows.map((r) =>
        el(
          "tr",
          null,
          cols.map((c) =>
            el("td", null, c === k.from || c === k.to ? linkValue(r[c], m, c) : fmt(r[c])),
          ),
        ),
      ),
    ),
  );
  return el(
    "details",
    { class: "fbox-aside" },
    el("summary", null, `${title} (${rows.length})`),
    el("div", { class: "scroll" }, table),
  );
}
