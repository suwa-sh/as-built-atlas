// 層を斜めから見た固定投影で描く。接点の選択は濃淡だけ、層の間隔だけが高さを変える。
import { el, svg, short, isPathLike } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { model, lineOf, opLabel, isWrite, kindOf } from "../model/catalog.js";
import { term } from "../model/vocab.js";

export function sectionData(layers, data) {
  const tk = model.treeMart.keys, sk = model.seqMart.keys;
  const floors = new Map(layers.map((l) => [l.id, []]));
  const frames = new Map(), targets = new Map();
  for (const row of data.frames) {
    const layer = row[tk.tag] || term("unknown");
    if (!floors.has(layer)) floors.set(layer, []);
    const caller = row[tk.parent];
    const parent = caller == null || caller === "" ? null : String(caller);
    const station = { id: String(row[tk.id]), layer, parent, name: row[tk.label], source: row[tk.source], unknown: false };
    frames.set(station.id, station);
    floors.get(layer).push(station);
  }
  for (const row of data.msgs) {
    const frame = frames.get(String(row[sk.node])), path = row[sk.to];
    if (!frame) continue;
    const unknown = row[sk.status] === "unknown";
    if (path === frame.name && row[sk.from] === frames.get(frame.parent)?.name) {
      frame.unknown = unknown;
      continue;
    }
    if (!isPathLike(path)) continue;
    if (!targets.has(path)) targets.set(path, { path, ops: new Map(), origins: new Map() });
    const t = targets.get(path), op = row[sk.label];
    if (op) t.ops.set(opLabel(path, op), isWrite(path, op));
    t.origins.set(frame.id, unknown || t.origins.get(frame.id));
  }
  return { floors, frames, targets };
}

export function sectionDiagram(path, { floors, frames, targets }) {
  const spacing = el("input", { type: "range", min: 16, max: 88, value: 26, "aria-label": `${term("layer")} の間隔` });
  const select = el("select", { "aria-label": term("target"), disabled: targets.size === 0 },
    el("option", { value: "" }, "すべて"), [...targets.keys()].map((p) => el("option", { value: p }, p)));
  const caption = el("p", { class: "section-caption", role: "status" });
  const canvas = el("div", { class: "section-canvas", tabindex: "0", "aria-label": "断面図" });
  let marks = [];
  function highlight() {
    const target = targets.get(select.value);
    const ancestors = new Set();
    for (const origin of target?.origins.keys() || []) {
      let cur = frames.get(origin);
      while (cur && !ancestors.has(cur.id)) {
        ancestors.add(cur.id);
        cur = frames.get(cur.parent);
      }
    }
    for (const { node, id, endpoint } of marks) {
      const active = !target || (endpoint ? endpoint === target.path : ancestors.has(id));
      node.classList.toggle("dim", !active);
      if (node.getAttribute("role") === "button") node.setAttribute("aria-pressed", String(endpoint === select.value));
    }
    caption.textContent = target ? `${target.path} · ${[...target.ops.keys()].join(" / ")} · 経由する ${term("frame")} ${ancestors.size} 件`
      : `${term("frame")} ${frames.size} 件 · ${term("target")} ${targets.size} 件`;
  }
  function draw() {
    // 1 枚の面に 3 列まで並べる。大きな入口では行を増やす。
    const cols = 3, pitch = 155, gap = Number(spacing.value);
    const planes = svg("g"), wires = svg("g"), stations = svg("g"), contacts = svg("g");
    marks = [];
    function mark(group, node, id, endpoint) {
      group.append(node);
      marks.push({ node, id, endpoint });
    }
    const slope = 0.055;
    let y = 48;
    for (const [name, items] of floors) {
      const rows = Math.max(1, Math.ceil(items.length / cols));
      const depth = rows * 38, front = y + depth, width = pitch * cols + 30;
      const rise = width * slope;
      const top = `M 80 ${y} l ${width} ${-rise} l -60 ${depth} l ${-width} ${rise} Z`;
      planes.append(svg("g", { class: items.length ? "floor" : "floor vacant" },
        svg("path", { class: "surface", d: top }),
        svg("path", { class: "fascia", d: `M 20 ${front} l ${width} ${-rise} l 60 -${depth} v 8 l -60 ${depth} l ${-width} ${rise} Z` }),
        svg("text", { x: 22, y: front + 24 }, items.length ? name : `${name} · 0`), svg("title", {}, `${name} · ${items.length} ${term("frame")}`)));
      items.forEach((f, i) => {
        const row = Math.floor(i / cols);
        f.x = 138 - (row + 0.5) * 60 / rows + i % cols * pitch;
        f.y = y + row * 38 + 22 - (f.x - 50) * slope;
      });
      y = front + 29 + gap;
    }
    for (const f of frames.values()) {
      const parent = frames.get(f.parent);
      if (parent) {
        // 同じ面の直線は途中の駅や札を貫くため、上側を通す。
        const mid = parent.layer === f.layer ? Math.min(parent.y, f.y) - 32 : (parent.y + f.y) / 2;
        mark(wires, svg("path", { class: f.unknown ? "wire uncertain" : "wire",
          d: `M ${parent.x} ${parent.y} C ${parent.x} ${mid}, ${f.x} ${mid}, ${f.x} ${f.y}` }), f.id);
      }
      mark(stations, svg("g", { class: "station" }, svg("title", {}, [f.name, f.source].filter(Boolean).join("\n")),
        svg("circle", { cx: f.x, cy: f.y, r: 4.5 }), svg("text", { x: f.x + 9, y: f.y + 4 }, short(f.name, 20))), f.id);
    }
    const dock = 606, sorted = [...targets.values()].sort((a, b) => firstY(a) - firstY(b) || a.path.localeCompare(b.path));
    function firstY(t) { return frames.get(t.origins.keys().next().value).y; }
    let last = 12;
    for (const t of sorted) {
      const ty = Math.max(last + 44, firstY(t));
      last = ty;
      for (const [id, unknown] of t.origins) {
        const f = frames.get(id);
        mark(wires, svg("path", { class: `wire access${unknown ? " uncertain" : ""}`,
          d: `M ${f.x} ${f.y} C ${f.x + 64} ${f.y - 33}, ${dock - 58} ${ty}, ${dock} ${ty}` }), id, t.path);
      }
      const [kind, ...parts] = segs(t.path);
      const label = short(parts.join("/") || t.path, 32);
      const action = svg("g", { class: "contact", tabindex: 0, role: "button", "aria-label": t.path },
        svg("title", {}, t.path), svg("rect", { x: dock - 9, y: ty - 16, width: 260, height: 40, rx: 5 }),
        svg("circle", { cx: dock, cy: ty, r: 4 }), svg("text", { x: dock + 12, y: ty + 3 }, label),
        svg("text", { class: "op-label", x: dock + 12, y: ty + 19 },
          kindOf(kind).label || kind, " · ", ...[...t.ops].map(([op, write], i) => svg("tspan", { class: write ? "write" : null }, (i ? " / " : "") + op))));
      function choose() { select.value = select.value === t.path ? "" : t.path; highlight(); }
      action.addEventListener("click", choose);
      action.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); choose(); } });
      mark(contacts, action, null, t.path);
    }
    const height = Math.max(y - gap, last + 32);
    canvas.replaceChildren(svg("svg", { class: "section-svg", viewBox: `0 0 870 ${height}`, role: "group", "aria-label": `3D · ${path}` }, planes, wires, stations, contacts));
    highlight();
  }
  select.addEventListener("change", highlight);
  spacing.addEventListener("input", draw);
  draw();
  const unknown = [...frames.values()].some((f) => f.unknown) || [...targets.values()].some((t) => [...t.origins.values()].some(Boolean));
  return el("div", { class: `section-drawing ${lineOf(path)}` },
    el("div", { class: "toolbar section-tools" }, el("label", null, term("target"), select),
      el("label", null, `${term("layer")} の間隔`, spacing)),
    canvas, caption, unknown ? el("p", { class: "note" }, `点線は ${term("unknown")} を含むつながり`) : null);
}
