// 層を斜めから見た固定投影で描く。接点の選択は濃淡だけ、層の間隔だけが高さを変える。
import { el, svg, short, isPathLike } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { model, lineOf, opLabel, isWrite, kindOf } from "../model/catalog.js";
import { term } from "../model/vocab.js";

export function sectionData(layers, data) {
  const tk = model.treeMart.keys,
    sk = model.seqMart.keys;
  const floors = new Map(layers.map((l) => [l.id, []]));
  const frames = new Map(),
    targets = new Map();
  indexFrames(data, tk, floors, frames);
  indexTargets(data, frames, sk, targets);
  return { floors, frames, targets };
}

function indexFrames(data, tk, floors, frames) {
  for (const row of data.frames) {
    const layer = row[tk.tag] || term("unknown");
    if (!floors.has(layer)) floors.set(layer, []);
    const caller = row[tk.parent];
    const parent = caller == null || caller === "" ? null : String(caller);
    const station = {
      id: String(row[tk.id]),
      layer,
      parent,
      name: row[tk.label],
      source: row[tk.source],
      unknown: false,
    };
    frames.set(station.id, station);
    floors.get(layer).push(station);
  }
}

function indexTargets(data, frames, sk, targets) {
  for (const row of data.msgs) {
    const frame = frames.get(String(row[sk.node])),
      path = row[sk.to];
    if (!frame) continue;
    const unknown = row[sk.status] === "unknown";
    if (path === frame.name && row[sk.from] === frames.get(frame.parent)?.name) {
      frame.unknown = unknown;
      continue;
    }
    if (!isPathLike(path)) continue;
    if (!targets.has(path)) targets.set(path, { path, ops: new Map(), origins: new Map() });
    const t = targets.get(path),
      op = row[sk.label];
    if (op) t.ops.set(opLabel(path, op), isWrite(path, op));
    t.origins.set(frame.id, unknown || t.origins.get(frame.id));
  }
}

export function sectionDiagram(path, data) {
  return new SectionDiagram().mount(path, data);
}

class SectionDiagram {
  constructor() {
    this.highlight = this.highlight.bind(this);
    this.draw = this.draw.bind(this);
  }

  mount(path, { floors, frames, targets }) {
    this.path = path;
    this.floors = floors;
    this.frames = frames;
    this.targets = targets;

    this.spacing = el("input", {
      type: "range",
      min: 16,
      max: 88,
      value: 26,
      "aria-label": `${term("layer")} の間隔`,
    });

    this.select = el(
      "select",
      { "aria-label": term("target"), disabled: this.targets.size === 0 },
      el("option", { value: "" }, "すべて"),
      [...this.targets.keys()].map((p) => el("option", { value: p }, p)),
    );

    this.caption = el("p", { class: "section-caption", role: "status" });

    this.canvas = el("div", { class: "section-canvas", tabindex: "0", "aria-label": "断面図" });

    this.marks = [];

    this.select.addEventListener("change", this.highlight);

    this.spacing.addEventListener("input", this.draw);

    this.draw();

    const unknown =
      [...this.frames.values()].some((f) => f.unknown) ||
      [...this.targets.values()].some((t) => [...t.origins.values()].some(Boolean));

    return el(
      "div",
      { class: `section-drawing ${lineOf(this.path)}` },
      el(
        "div",
        { class: "toolbar section-tools" },
        el("label", null, term("target"), this.select),
        el("label", null, `${term("layer")} の間隔`, this.spacing),
      ),
      this.canvas,
      this.caption,
      unknown ? el("p", { class: "note" }, `点線は ${term("unknown")} を含むつながり`) : null,
    );
  }

  highlight() {
    const target = this.targets.get(this.select.value);
    const ancestors = new Set();
    for (const origin of target?.origins.keys() || []) {
      let cur = this.frames.get(origin);
      while (cur && !ancestors.has(cur.id)) {
        ancestors.add(cur.id);
        cur = this.frames.get(cur.parent);
      }
    }
    for (const { node, id, endpoint } of this.marks) {
      const active = !target || (endpoint ? endpoint === target.path : ancestors.has(id));
      node.classList.toggle("dim", !active);
      if (node.getAttribute("role") === "button")
        node.setAttribute("aria-pressed", String(endpoint === this.select.value));
    }
    this.caption.textContent = target
      ? `${target.path} · ${[...target.ops.keys()].join(" / ")} · 経由する ${term("frame")} ${ancestors.size} 件`
      : `${term("frame")} ${this.frames.size} 件 · ${term("target")} ${this.targets.size} 件`;
  }

  draw() {
    const component = this;

    // 1 枚の面に 3 列まで並べる。大きな入口では行を増やす。
    const cols = 3,
      pitch = 155,
      gap = Number(this.spacing.value);
    const planes = svg("g"),
      wires = svg("g"),
      stations = svg("g"),
      contacts = svg("g");
    this.marks = [];
    function mark(group, node, id, endpoint) {
      group.append(node);
      component.marks.push({ node, id, endpoint });
    }
    let y = this.drawFloors(cols, pitch, planes, gap);
    this.drawStations(mark, wires, stations);
    const dock = 606,
      sorted = [...this.targets.values()].sort(
        (a, b) => firstY(a) - firstY(b) || a.path.localeCompare(b.path),
      );
    function firstY(t) {
      return component.frames.get(t.origins.keys().next().value).y;
    }
    let last = 12;
    for (const t of sorted) {
      const ty = Math.max(last + 44, firstY(t));
      last = ty;
      this.drawContactWires(t, mark, wires, dock, ty);
      drawContact(t, dock, ty, component, mark, contacts);
    }
    const height = Math.max(y - gap, last + 32);
    this.canvas.replaceChildren(
      svg(
        "svg",
        {
          class: "section-svg",
          viewBox: `0 0 870 ${height}`,
          role: "group",
          "aria-label": `3D · ${this.path}`,
        },
        planes,
        wires,
        stations,
        contacts,
      ),
    );
    this.highlight();
  }

  drawFloors(cols, pitch, planes, gap) {
    const slope = 0.055;
    let y = 48;
    for (const [name, items] of this.floors) {
      const rows = Math.max(1, Math.ceil(items.length / cols));
      const depth = rows * 38,
        front = y + depth,
        width = pitch * cols + 30;
      const rise = width * slope;
      const top = `M 80 ${y} l ${width} ${-rise} l -60 ${depth} l ${-width} ${rise} Z`;
      planes.append(
        svg(
          "g",
          { class: items.length ? "floor" : "floor vacant" },
          svg("path", { class: "surface", d: top }),
          svg("path", {
            class: "fascia",
            d: `M 20 ${front} l ${width} ${-rise} l 60 -${depth} v 8 l -60 ${depth} l ${-width} ${rise} Z`,
          }),
          svg("text", { x: 22, y: front + 24 }, items.length ? name : `${name} · 0`),
          svg("title", {}, `${name} · ${items.length} ${term("frame")}`),
        ),
      );
      items.forEach((f, i) => {
        const row = Math.floor(i / cols);
        f.x = 138 - ((row + 0.5) * 60) / rows + (i % cols) * pitch;
        f.y = y + row * 38 + 22 - (f.x - 50) * slope;
      });
      y = front + 29 + gap;
    }
    return y;
  }

  drawStations(mark, wires, stations) {
    for (const f of this.frames.values()) {
      const parent = this.frames.get(f.parent);
      if (parent) {
        // 同じ面の直線は途中の駅や札を貫くため、上側を通す。
        const mid = parent.layer === f.layer ? Math.min(parent.y, f.y) - 32 : (parent.y + f.y) / 2;
        mark(
          wires,
          svg("path", {
            class: f.unknown ? "wire uncertain" : "wire",
            d: `M ${parent.x} ${parent.y} C ${parent.x} ${mid}, ${f.x} ${mid}, ${f.x} ${f.y}`,
          }),
          f.id,
        );
      }
      mark(
        stations,
        svg(
          "g",
          { class: "station" },
          svg("title", {}, [f.name, f.source].filter(Boolean).join("\n")),
          svg("circle", { cx: f.x, cy: f.y, r: 4.5 }),
          svg("text", { x: f.x + 9, y: f.y + 4 }, short(f.name, 20)),
        ),
        f.id,
      );
    }
  }

  drawContactWires(t, mark, wires, dock, ty) {
    for (const [id, unknown] of t.origins) {
      const f = this.frames.get(id);
      mark(
        wires,
        svg("path", {
          class: `wire access${unknown ? " uncertain" : ""}`,
          d: `M ${f.x} ${f.y} C ${f.x + 64} ${f.y - 33}, ${dock - 58} ${ty}, ${dock} ${ty}`,
        }),
        id,
        t.path,
      );
    }
  }
}

function drawContact(t, dock, ty, component, mark, contacts) {
  const [kind, ...parts] = segs(t.path);
  const label = short(parts.join("/") || t.path, 32);
  const action = svg(
    "g",
    { class: "contact", tabindex: 0, role: "button", "aria-label": t.path },
    svg("title", {}, t.path),
    svg("rect", { x: dock - 9, y: ty - 16, width: 260, height: 40, rx: 5 }),
    svg("circle", { cx: dock, cy: ty, r: 4 }),
    svg("text", { x: dock + 12, y: ty + 3 }, label),
    svg(
      "text",
      { class: "op-label", x: dock + 12, y: ty + 19 },
      kindOf(kind).label || kind,
      " · ",
      ...[...t.ops].map(([op, write], i) =>
        svg("tspan", { class: write ? "write" : null }, (i ? " / " : "") + op),
      ),
    ),
  );
  function choose() {
    component.select.value = component.select.value === t.path ? "" : t.path;
    component.highlight();
  }
  action.addEventListener("click", choose);
  action.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      choose();
    }
  });
  mark(contacts, action, null, t.path);
}
