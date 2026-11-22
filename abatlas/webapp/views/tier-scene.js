// アプリを同心円の断面として描き、下のストアと外の接続先を同じ座標系で投影する。
import { el, svg } from "../lib/dom.js";
import { model, lineOf } from "../model/catalog.js";
import { term } from "../model/vocab.js";
import {
  callMesh,
  callerChain,
  layerMesh,
  pointOnFace,
  resolveTierSelection,
} from "./call-mesh.js";

import { pathPanels, radialLayout, visibleWallParts } from "./radial-layout.js";

const VIEWS = [
  { name: "斜め", yaw: 0, pitch: 12 },
  { name: "上から", yaw: 0, pitch: 90 },
];
const clamp = (n, low, high) => Math.max(low, Math.min(high, n));
const wrap = (angle) => ((((angle + 180) % 360) + 360) % 360) - 180;
const describe = (node) => node.tier + " / " + node.label;

export function tierScene(layers, entries, camera, onTierChange, filterHost) {
  const prepared = prepareTiers(entries, camera, layers, onTierChange);
  const { fullMesh, tiers } = prepared;
  const host = el("section", { class: "tier-view" });
  function openTier(tier) {
    camera.drillTier = tier;
    camera.detail = null;
    onTierChange(tier);
    render();
    const buttons = filterHost.querySelectorAll(".tier-navigation button");
    ([...buttons].find((b) => b.dataset.openTier === lastTier) || buttons[0])?.focus({
      preventScroll: true,
    });
  }
  let lastTier = camera.drillTier;
  function render() {
    const tier = camera.drillTier;
    if (tier) lastTier = tier;
    const { layout, mesh, state } = tierLayout(tier, layers, camera, prepared);
    const navigation = navigationBar(tier, openTier, tiers);
    const { faceControls, content } = scene(layout, mesh, fullMesh, entries, state, tier, openTier);
    filterHost.replaceChildren(faceControls, navigation);
    host.replaceChildren(content);
  }
  render();
  return host;
}

function prepareTiers(entries, camera, layers, onTierChange) {
  const fullMesh = callMesh(entries || []);
  for (const dot of fullMesh.dots.values()) camera.knownIds.add(dot.area);
  const kinds = Object.entries(model.meta.resource_kinds || {}).map(([id, k]) => [id, k.label]);
  const labels = {
    unknown: term("unknown"),
    store: term("datastore"),
    external: term("external_group"),
  };
  const overview = radialLayout(layers, kinds, camera.knownIds, labels);
  const tiers = new Set(layers.map((l) => l.tier).filter(Boolean));
  if (camera.drillTier && !tiers.has(camera.drillTier)) {
    camera.drillTier = "";
    onTierChange("");
  }
  return { kinds, labels, overview, fullMesh, tiers };
}

function tierLayout(tier, layers, camera, { kinds, labels, overview, fullMesh }) {
  const layout = tier ? radialLayout(layers, kinds, camera.knownIds, labels, tier) : overview;
  const mesh = tier ? layerMesh(fullMesh, layout.nodes) : fullMesh;
  const state = tier
    ? (camera.detail ||= { yaw: 0, pitch: 12, zoom: 1, panX: 0, panY: 0 })
    : camera;
  return { layout, mesh, state };
}

function navigationBar(tier, openTier, tiers) {
  return el(
    "div",
    { class: "tier-navigation" },
    tier
      ? [
          el(
            "button",
            { type: "button", class: "link", onclick: () => openTier("") },
            "← 全体図に戻る",
          ),
          el("strong", null, tier),
        ]
      : tiers.size
        ? [
            el("span", null, term("tier") + " を開く"),
            [...tiers].map((id) =>
              el(
                "button",
                {
                  type: "button",
                  class: "chip",
                  "data-open-tier": id,
                  onclick: () => openTier(id),
                },
                id,
              ),
            ),
          ]
        : [],
  );
}

function scene(layout, mesh, fullMesh, entries, state, tier, openTier) {
  return new TierScene().mount(layout, mesh, fullMesh, entries, state, tier, openTier);
}

class TierScene {
  constructor() {
    this.stop = this.stop.bind(this);
  }

  mount({ nodes, discs, radius }, mesh, fullMesh, entries, state, tier, openTier) {
    this.nodes = nodes;
    this.discs = discs;
    this.radius = radius;
    this.mesh = mesh;
    this.fullMesh = fullMesh;
    this.entries = entries;
    this.state = state;
    this.tier = tier;
    this.openTier = openTier;

    this.interLayer = this.tier
      ? this.mesh.edges.filter(
          (e) => this.mesh.dots.get(e.from).area !== this.mesh.dots.get(e.to).area,
        ).length
      : 0;

    this.panels = this.tier && this.entries ? pathPanels(this.nodes, this.mesh.dots) : null;

    const { linkedAreas, points } = createMeshPoints(this.mesh, this.panels, this.nodes);
    this.linkedAreas = linkedAreas;
    this.points = points;

    this.selectionContext = {
      nodes: this.nodes,
      mesh: this.mesh,
      fullMesh: this.fullMesh,
      panels: this.panels,
    };

    this.selection = this.resolve(this.state.selection);

    this.createCameraControls();

    this.createPointControls();

    this.listenToPickers();

    this.createZoomControls();

    // 範囲は全円盤の寸法から決める。線の選択・絞り込みで中心や倍率を変えない。
    this.halfWidth = this.radius + 110;

    this.pending = 0;

    this.listenToCamera();

    this.listenToKeyboard();

    this.drag = null;
    this.suppressClick = false;

    this.startDragOnPress();

    this.dragOnMove();

    this.endDragOnRelease();

    this.selectOnClick();

    this.updateCamera();

    this.updateSelectionControls();

    const faceControls = el(
      "div",
      { class: "toolbar tier-face-controls" },
      el("label", null, "面", this.picker),
      this.pointLabel,
      this.reset,
    );

    const cameraTools = el(
      "div",
      { class: "toolbar tier-camera-tools", role: "group", "aria-label": "図の操作" },
      el("div", { class: "chips", role: "group", "aria-label": "視点" }, this.cameras),
      el("label", null, "回転", this.yaw),
      el("div", { class: "chips" }, this.minus, this.plus, this.panMode),
    );

    const canvas = el("div", { class: "tier-canvas" }, cameraTools, this.diagram);

    const content = el(
      "div",
      null,
      this.pathKey,
      canvas,
      el(
        "p",
        { class: "note tier-help" },
        "ドラッグで回転 · ホイールで拡大縮小 · Shift＋ドラッグで移動",
      ),
      el(
        "p",
        { class: "note tier-legend" },
        this.tier
          ? `各段は ${term("layer")}、曲面はその段を通る ${term("entry")} の ${term("api_path")}、点は ${term("frame")}。凡例を選ぶと同じ ${term("api_path")} の面を全段で強調します。矢印は ${term("caller")} → ${term("callee")}。段をまたぐ線で ${term("layer")} 間の ${term("call")} をたどれます。`
          : `側面は ${term("layer")} や ${term("datastore")} の ${term("kind")} を表す。内周は ${term("datastore")}、外周は ${term("external")}。白丸は起点。面や点を選ぶと、そこまでの ${term("call_path")} が濃くなる。`,
      ),
      this.info,
      this.mesh.edges.some((e) => e.unknown)
        ? el("p", { class: "note" }, `点線は ${term("unknown")} を含むつながり`)
        : null,
    );

    return { faceControls, content };
  }
  createCameraControls() {
    this.diagram = svg("svg", {
      class: this.tier ? "tier-svg tier-detail" : "tier-svg",
      role: "group",
      tabindex: 0,
      "aria-label": this.tier
        ? `${this.tier} の ${term("layer")} 図`
        : `${term("tier")} の同心円図`,
    });

    if (this.tier) this.diagram.style.setProperty("--layer-count", this.discs.length);

    this.info = el("div", { class: "tier-info", role: "status" });

    this.yaw = el("input", {
      type: "range",
      min: -180,
      max: 180,
      value: this.state.yaw,
      "aria-label": "左右の回転",
    });

    this.cameras = VIEWS.map((v) =>
      el(
        "button",
        {
          type: "button",
          class: "chip",
          onclick: () => {
            Object.assign(this.state, { yaw: v.yaw, pitch: v.pitch, zoom: 1, panX: 0, panY: 0 });
            this.updateCamera();
          },
        },
        v.name,
      ),
    );

    this.picker = el("select", { "aria-label": "面を選ぶ" }, el("option", { value: "" }, "すべて"));

    populateAreaPicker(this.nodes, this.panels, this.picker);

    this.reset = el(
      "button",
      { type: "button", class: "link", onclick: () => this.select("") },
      "選択を解除",
    );

    this.pointPicker = el("select", { "aria-label": "点を選ぶ" });
  }
  createPointControls() {
    this.pathKey = this.panels?.paths.length
      ? el(
          "ol",
          { class: "path-key", "aria-label": term("entry") + " の " + term("api_path") },
          this.panels.paths.map((path, i) =>
            el(
              "li",
              { class: lineOf(path) },
              el(
                "button",
                {
                  type: "button",
                  "data-path": path,
                  onclick: () =>
                    this.select(
                      "",
                      "",
                      !this.selection.area && this.selection.path === path ? "" : path,
                    ),
                },
                el("b", null, String(i + 1)),
                path,
              ),
            ),
          ),
        )
      : null;

    this.pointLabel = el("label", null, "点", this.pointPicker);
  }
  listenToPickers() {
    this.pointPicker.addEventListener("change", () =>
      this.select(this.selection.area?.id || "", this.pointPicker.value, this.selection.path),
    );

    this.picker.addEventListener("change", () => {
      const option = this.picker.selectedOptions[0];
      this.select(option.dataset.area || "", "", option.dataset.path || "");
    });
  }
  createZoomControls() {
    this.panMode = el(
      "button",
      {
        type: "button",
        class: "chip canvas-icon",
        title: "移動モード",
        "aria-label": "移動モード",
        "aria-pressed": "false",
        onclick: () => {
          this.state.panMode = !this.state.panMode;
          this.updateCameraControls();
        },
      },
      svg(
        "svg",
        {
          viewBox: "0 0 24 24",
          width: 19,
          height: 19,
          fill: "none",
          stroke: "currentColor",
          "stroke-width": 1.65,
          "stroke-linejoin": "round",
          "stroke-linecap": "round",
          "aria-hidden": "true",
        },
        svg("path", {
          d: "M8 14V6a1.5 1.5 0 0 1 3 0v5-7a1.5 1.5 0 0 1 3 0v7-6a1.5 1.5 0 0 1 3 0v7-4a1.5 1.5 0 0 1 3 0v6c0 5-2.5 8-7 8-3 0-4.5-1.4-6.2-3.7l-3.3-4.6a1.5 1.5 0 0 1 2.3-1.9L8 14Z",
        }),
      ),
    );

    this.minus = el(
      "button",
      {
        type: "button",
        class: "chip canvas-icon",
        title: "縮小",
        "aria-label": "縮小",
        onclick: () => this.zoomBy(1 / 1.2),
      },
      "−",
    );

    this.plus = el(
      "button",
      {
        type: "button",
        class: "chip canvas-icon",
        title: "拡大",
        "aria-label": "拡大",
        onclick: () => this.zoomBy(1.2),
      },
      "＋",
    );
  }
  listenToCamera() {
    this.yaw.addEventListener("input", () => {
      this.state.yaw = Number(this.yaw.value);
      this.updateCamera();
    });

    this.diagram.addEventListener(
      "wheel",
      (ev) => {
        ev.preventDefault();
        const delta = ev.deltaY * (ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? 320 : 1);
        this.state.zoom = clamp(
          this.state.zoom * Math.exp(-clamp(delta, -350, 350) * 0.002),
          0.65,
          3.5,
        );
        this.schedule();
      },
      { passive: false },
    );
  }
  listenToKeyboard() {
    this.diagram.addEventListener("keydown", (ev) => {
      const drill = ev.target.closest("[data-open-tier]");
      if (drill && (ev.key === "Enter" || ev.key === " ")) {
        ev.preventDefault();
        this.openTier(drill.dataset.openTier);
        return;
      }
      const id = ev.target.closest("[data-node]")?.dataset.node;
      if (id && (ev.key === "Enter" || ev.key === " ")) {
        ev.preventDefault();
        this.select(id === this.selection.area?.id && !this.selection.path ? "" : id);
      }
    });
  }
  startDragOnPress() {
    this.diagram.addEventListener("pointerdown", (ev) => {
      if (!ev.isPrimary || ev.button !== 0) return;
      this.suppressClick = false;
      this.drag = {
        x: ev.clientX,
        y: ev.clientY,
        yaw: this.state.yaw,
        pitch: this.state.pitch,
        panX: this.state.panX,
        panY: this.state.panY,
        pan: ev.shiftKey || this.state.panMode,
      };
    });
  }
  dragOnMove() {
    this.diagram.addEventListener("pointermove", (ev) => {
      if (!this.drag || !ev.isPrimary) return;
      const dx = ev.clientX - this.drag.x,
        dy = ev.clientY - this.drag.y;
      if (!this.suppressClick && Math.hypot(dx, dy) < 4) return;
      if (!this.suppressClick) {
        this.diagram.setPointerCapture(ev.pointerId);
        this.suppressClick = true;
      }
      if (this.drag.pan) {
        const scale = this.diagram.getScreenCTM().a;
        this.state.panX = this.drag.panX - dx / scale;
        this.state.panY = this.drag.panY - dy / scale;
      } else {
        this.state.yaw = wrap(this.drag.yaw + dx * 0.55);
        this.state.pitch = clamp(this.drag.pitch + dy * 0.38, 8, 90);
      }
      this.schedule();
    });
  }
  endDragOnRelease() {
    this.diagram.addEventListener("pointerup", this.stop);

    this.diagram.addEventListener("pointercancel", this.stop);

    this.diagram.addEventListener("lostpointercapture", this.stop);

    this.diagram.addEventListener("pointerleave", () => {
      if (!this.suppressClick) this.stop();
    });
  }
  selectOnClick() {
    this.diagram.addEventListener("click", (ev) => {
      if (this.suppressClick && ev.detail) return;
      const drill = ev.target.closest("[data-open-tier]");
      if (drill) {
        this.openTier(drill.dataset.openTier);
        return;
      }
      const dot = this.mesh.dots.get(ev.target.closest("[data-point]")?.dataset.point);
      if (dot) {
        this.select(
          dot.area,
          dot.id === this.selection.point?.id ? "" : dot.id,
          this.panels ? dot.entry : "",
        );
        return;
      }
      this.selectHitFace(ev);
    });
  }

  selectHitFace(ev) {
    const hit = ev.target.closest("[data-node],[data-face]");
    const id = hit?.dataset.node || hit?.dataset.face;
    if (id) {
      const path = hit.dataset.path || "";
      if (id === this.selection.area?.id && path === this.selection.path) this.select("");
      else this.select(id, "", path);
    }
  }

  resolve(choice) {
    const result = resolveTierSelection(this.selectionContext, choice);
    // 描画を作り直すときは、新しいグラフで選択を復元する。
    this.state.selection = { area: result.area?.id, path: result.path, point: result.point?.id };
    return result;
  }

  select(id, point = "", path = "") {
    this.selection = this.resolve({ area: id, point, path });
    this.drawDiagram();
    this.updateSelectionControls();
  }

  zoomBy(factor) {
    this.state.zoom = clamp(this.state.zoom * factor, 0.65, 3.5);
    this.updateCamera();
  }

  schedule() {
    if (!this.pending)
      this.pending = requestAnimationFrame(() => {
        this.pending = 0;
        if (this.diagram.isConnected) this.updateCamera();
      });
  }

  updateCamera() {
    this.drawDiagram();
    this.updateCameraControls();
  }

  drawDiagram() {
    const focused = this.diagram.contains(document.activeElement)
      ? document.activeElement.dataset
      : {};
    const projection = cameraProjection(this.state);
    const surfaces = svg("g"),
      wires = svg("g"),
      names = svg("g"),
      titles = svg("g");
    // 高さの異なる筒は下の段から描く。各段では手前の曲面が奥の曲面に重なる。
    for (const d of [...this.discs].reverse()) {
      const { back, front } = this.discShell(d, projection, names);
      back.append(front);
      surfaces.append(back);
    }

    // 同じ線幅・濃さの辺は一本の SVG path にまとめる。線の両端は必ず実在する点。
    drawCallEdges(this.mesh, projection.project, this.selection, this.tier, wires);
    // 各筒の輪郭と名前を結ぶ。真上で高さが重なっても半径で所属を識別できる。
    // 左奥の輪郭に引出線を付け、低い視点で近接する見出しの間隔を確保する。
    const labelBoxes = addDiscLabels(this, projection, titles);
    addOverviewLabels(this, projection, labelBoxes, names);
    fitScene(this, projection, labelBoxes);
    this.diagram.replaceChildren(surfaces, wires, titles, names, this.points);
    if (focused.node || focused.openTier)
      [...titles.children, ...names.children]
        .find((g) =>
          focused.node ? g.dataset.node === focused.node : g.dataset.openTier === focused.openTier,
        )
        ?.focus({ preventScroll: true });
  }

  discShell(d, projection, names) {
    const back = svg("g", { class: "disc " + d.type, "data-tier": d.tier }),
      front = svg("g");
    for (const ring of d.rings)
      back.append(svg("polyline", { class: "tier-ring", points: projection.polygon(ring) }));
    const faces = this.panels ? this.panels.byLayer.get(d.faces[0].id).values() : d.faces;
    drawDiscFaces(faces, this, projection, back, front, names);
    return { back, front };
  }

  updateCameraControls() {
    this.yaw.value = Math.round(this.state.yaw);
    this.cameras.forEach((btn, i) => {
      const v = VIEWS[i],
        on = this.state.yaw === v.yaw && this.state.pitch === v.pitch;
      btn.setAttribute("aria-pressed", String(on));
      btn.classList.toggle("on", on);
    });
    this.panMode.setAttribute("aria-pressed", String(Boolean(this.state.panMode)));
    this.panMode.classList.toggle("on", Boolean(this.state.panMode));
    this.diagram.classList.toggle("pan-mode", Boolean(this.state.panMode));
    this.plus.disabled = this.state.zoom >= 3.5;
    this.minus.disabled = this.state.zoom <= 0.65;
  }

  updateSelectionControls() {
    this.picker.value =
      this.selection.area && this.selection.path
        ? JSON.stringify([this.selection.area.id, this.selection.path])
        : this.selection.area?.id || "";
    this.reset.hidden = !this.selection.trace;
    for (const button of this.pathKey?.querySelectorAll("button") || []) {
      button.setAttribute(
        "aria-pressed",
        String(!this.selection.area && this.selection.path === button.dataset.path),
      );
    }
    updatePointOptions(this.selection, this.pointPicker, this.pointLabel);
    const key = JSON.stringify([
      this.selection.area?.id,
      this.selection.path,
      this.selection.point?.id,
    ]);
    if (this.info.dataset.selection === key) return;
    this.info.dataset.selection = key;
    this.info.replaceChildren(
      this.entries
        ? el(
            "span",
            { class: "count" },
            this.tier
              ? `${this.mesh.dots.size} 点 · ${term("layer")} 間 ${this.interLayer} 本 · 同じ ${term("layer")} 内 ${this.mesh.edges.length - this.interLayer} 本`
              : `${this.mesh.dots.size} 点 · ${this.mesh.edges.length} 本`,
          )
        : el(
            "p",
            { class: "note" },
            `面の配置のみ表示中。点と線の表示には ${term("frame")} と ${term("call")} の集計が必要です。`,
          ),
    );
    showSelectionDetails(this);
  }

  stop() {
    this.drag = null;
  }
}

function cameraProjection(state) {
  const y = (state.yaw * Math.PI) / 180,
    p = (state.pitch * Math.PI) / 180;
  const cosY = Math.cos(y),
    sinY = Math.sin(y),
    cosP = Math.cos(p),
    sinP = Math.sin(p);
  function project([x, h, z]) {
    const away = x * sinY + z * cosY;
    return { x: x * cosY - z * sinY, y: away * sinP - h * cosP, depth: away * cosP + h * sinP };
  }
  function polygon(points) {
    return points
      .map((point) => {
        const q = project(point);
        return q.x.toFixed(2) + "," + q.y.toFixed(2);
      })
      .join(" ");
  }
  return { project, polygon, yaw: y, sinP, cosP, sinY, cosY };
}

function createMeshPoints(mesh, panels, nodes) {
  const linkedAreas = new Set();
  const points = svg("g", { class: "stack-points" });
  for (const dot of mesh.dots.values()) {
    linkedAreas.add(dot.area);
    dot.line = dot.entry ? lineOf(dot.entry) : "";
    dot.point = pointOnFace(
      panels ? panels.byLayer.get(dot.area).get(dot.entry) : nodes.get(dot.area),
      dot.id,
    );
    dot.element = svg(
      "circle",
      {
        "data-point": dot.id,
        r: dot.root ? 3.8 : 2.4,
        class: "stack-dot" + (dot.root ? " root" : "") + " " + dot.line,
      },
      svg("title", {}, [dot.name, dot.source, dot.entry].filter(Boolean).join("\n")),
    );
    points.append(dot.element);
  }
  return { linkedAreas, points };
}

function populateAreaPicker(nodes, panels, picker) {
  const groups = new Map();
  for (const n of nodes.values()) {
    const group = panels ? n.label : n.tier;
    if (!groups.has(group)) {
      const g = el("optgroup", { label: group });
      groups.set(group, g);
      picker.append(g);
    }
    groups
      .get(group)
      .append(
        el("option", { value: n.id, "data-area": n.id }, panels ? n.label + "（段全体）" : n.label),
      );
    for (const face of panels?.byLayer.get(n.id).values() || []) {
      groups
        .get(group)
        .append(
          el(
            "option",
            { value: JSON.stringify([n.id, face.path]), "data-area": n.id, "data-path": face.path },
            face.number + " · " + face.path,
          ),
        );
    }
  }
}

function drawDiscFaces(
  faces,
  { selection, state, panels },
  { project, polygon, yaw: y },
  back,
  front,
  names,
) {
  for (const face of faces) {
    const { attrs, title, chosen } = faceAttributes(selection, face);
    if (state.pitch === 90) {
      back.append(
        svg("polyline", { ...attrs, points: polygon(face.topArc) }, svg("title", {}, title)),
      );
    } else
      for (const part of visibleWallParts(face, y)) {
        (part.front ? front : back).append(
          svg("polygon", { ...attrs, points: polygon(part.points) }, svg("title", {}, title)),
        );
      }
    drawFaceNumber(face, panels, chosen, selection, project, names);
  }
}

function faceAttributes(selection, face) {
  const chosen = selection.chosenFaces.has(face);
  const onPath = selection.visitedFaces.has(face);
  const highlight = chosen
    ? " chosen"
    : onPath
      ? " on-path"
      : selection.trace && face.path
        ? " muted"
        : "";
  const attrs = {
    class: "layer-wall" + highlight + (face.path ? " path-panel " + lineOf(face.path) : ""),
    "data-face": face.id,
    "data-path": face.path,
  };
  const title = face.path ? face.label + " · " + face.path : describe(face);
  return { attrs, title, chosen };
}

function drawFaceNumber(face, panels, chosen, selection, project, names) {
  if (face.path && (panels.paths.length <= 8 || (chosen && (selection.path || selection.point)))) {
    const point = project(face.point);
    names.append(
      svg(
        "text",
        {
          class: "path-number",
          x: point.x,
          y: point.y - 2,
          "text-anchor": "middle",
          "aria-hidden": "true",
        },
        String(face.number),
      ),
    );
  }
}

function drawCallEdges(mesh, project, selection, tier, wires) {
  const arrows = [];
  const paths = new Map();
  for (const dot of mesh.dots.values()) {
    dot.screen = project(dot.point);
  }
  for (const edge of mesh.edges) {
    const src = mesh.dots.get(edge.from),
      dst = mesh.dots.get(edge.to);
    const active = !selection.trace || selection.trace.lines.has(edge);
    const cls =
      "tier-wire " +
      src.line +
      (active ? (selection.trace ? " strong" : "") : " dim") +
      (edge.unknown ? " uncertain" : "");
    if (!paths.has(cls)) paths.set(cls, []);
    const a = src.screen,
      b = dst.screen;
    paths.get(cls).push(`M${a.x.toFixed(2)},${a.y.toFixed(2)}L${b.x.toFixed(2)},${b.y.toFixed(2)}`);
    appendCallArrow(active, tier, selection, b, a, arrows);
  }
  for (const [cls, d] of [...paths].sort(
    ([a], [b]) => Number(b.includes(" dim")) - Number(a.includes(" dim")),
  )) {
    wires.append(svg("path", { class: cls, d: d.join("") }));
  }
  if (arrows.length) wires.append(svg("path", { class: "tier-call-arrows", d: arrows.join("") }));
  drawMeshPoints(mesh, selection);
}

function appendCallArrow(active, tier, selection, b, a, arrows) {
  if (active && (tier || selection.trace)) {
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    if (length > (tier ? 0 : 18)) {
      const tip = Math.min(5, length * 0.28),
        wing = tip * 0.6;
      const dx = (b.x - a.x) / length,
        dy = (b.y - a.y) / length;
      const x = (a.x + b.x) / 2,
        y = (a.y + b.y) / 2;
      arrows.push(
        `M${x - tip * dx + wing * dy},${y - tip * dy - wing * dx}L${x},${y}l${-tip * dx - wing * dy},${-tip * dy + wing * dx}`,
      );
    }
  }
}

function drawMeshPoints(mesh, selection) {
  for (const dot of mesh.dots.values()) {
    const on = dot.id === selection.point?.id;
    const visible = selection.trace ? selection.trace.keep.has(dot.id) : true;
    dot.element.setAttribute("cx", dot.screen.x);
    dot.element.setAttribute("cy", dot.screen.y);
    dot.element.classList.toggle("dim", !visible);
    dot.element.classList.toggle("on", on);
    dot.element.setAttribute("r", on ? 5 : dot.root ? 3.8 : 2.4);
  }
}

function addDiscLabels({ discs, radius, tier, selection }, { yaw: y, project }, titles) {
  const guides = discs
    .map((d) => {
      const angle = -Math.PI * 0.82 - y;
      const anchor = project([
        d.rx * Math.cos(angle),
        d.h - d.thickness / 2,
        d.rz * Math.sin(angle),
      ]);
      return { d, anchor };
    })
    .sort((a, b) => a.anchor.y - b.anchor.y);
  let previous = -Infinity;
  const labelBoxes = [];
  for (const { d, anchor } of guides) {
    const x = -radius - 12,
      ty = Math.max(anchor.y, previous + (tier ? 26 : 20));
    const label = tier ? d.faces[0].label : d.tier;
    const selectable = tier || d.declared;
    const action = tier
      ? {
          "data-node": d.faces[0].id,
          "aria-pressed": String(selection.area?.id === d.faces[0].id),
        }
      : { "data-open-tier": d.tier, "aria-label": d.tier + " を開く" };
    titles.append(
      svg("path", {
        class: "tier-guide",
        d: `M ${x + 4} ${ty} L ${anchor.x - 10} ${ty} L ${anchor.x} ${anchor.y}`,
      }),
      svg(
        "text",
        {
          class: "tier-title",
          x,
          y: ty + 4,
          "text-anchor": "end",
          ...(selectable ? { ...action, role: "button", tabindex: 0 } : {}),
        },
        label,
      ),
    );
    labelBoxes.push({ x: x - label.length * (tier ? 14 : 9) - 6, right: x + 4, y: ty });
    previous = ty;
  }
  return labelBoxes;
}

function addOverviewLabels(
  { tier, nodes, selection, linkedAreas },
  { project, sinP, cosP },
  labelBoxes,
  names,
) {
  for (const n of tier ? [] : nodes.values()) {
    const pt = project(n.point),
      on = selection.area?.id === n.id;
    const width = Array.from(n.label).reduce((w, ch) => w + (ch.codePointAt(0) < 128 ? 8 : 14), 16);
    // 真上では点と名前を別の半径に置く。斜めでは投影後の文字幅を使って衝突を避ける。
    const { x, labelY } = positionAreaLabel(sinP, n, pt, cosP, width, labelBoxes, names);
    const g = svg(
      "g",
      {
        class: `tier-node${!linkedAreas.has(n.id) ? " unlinked" : ""}${on ? " on" : ""}${selection.area && !on && !selection.visitedFaces.has(n) ? " dim" : ""}`,
        transform: `translate(${x} ${labelY})`,
        role: "button",
        tabindex: 0,
        "data-node": n.id,
        "aria-label": describe(n),
        "aria-pressed": String(on),
      },
      svg("title", {}, describe(n)),
      svg("rect", { x: -width / 2, y: -12, width, height: 24, rx: 4 }),
      svg("text", { x: 0, y: 4, "text-anchor": "middle" }, n.label),
    );
    names.append(g);
  }
}

function positionAreaLabel(sinP, n, pt, cosP, width, labelBoxes, names) {
  const inset = (16 * sinP ** 4) / n.rx;
  const x = pt.x * (1 - inset),
    wanted = pt.y * (1 - inset) - 7 * cosP;
  const left = x - width / 2,
    right = x + width / 2;
  const near = labelBoxes.filter((box) => left < box.right && right > box.x);
  const options = [wanted, ...near.flatMap((box) => [box.y - 25, box.y + 25])];
  const labelY = options
    .filter((v) => near.every((box) => Math.abs(box.y - v) >= 24))
    .sort((a, b) => Math.abs(a - wanted) - Math.abs(b - wanted))[0];
  labelBoxes.push({ x: left, right, y: labelY });
  if (Math.abs(labelY - wanted) > 4)
    names.append(svg("path", { class: "tier-guide", d: `M ${pt.x} ${pt.y} L ${x} ${labelY}` }));
  return { x, labelY };
}

function fitScene(
  { discs, halfWidth, tier, radius, state, diagram },
  { project, sinY, cosY, sinP, cosP },
  labelBoxes,
) {
  let top = Infinity,
    bottom = -Infinity;
  for (const d of discs) {
    const center = project([d.x, d.h, d.z]);
    const extent = Math.hypot(d.rx * sinY, d.rz * cosY) * sinP;
    top = Math.min(top, center.y - extent - 32);
    bottom = Math.max(bottom, center.y + extent + d.thickness * cosP + 36);
  }
  const width = Math.max(halfWidth, ...labelBoxes.map((b) => Math.max(-b.x, b.right) + 4));
  top = Math.min(top, ...labelBoxes.map((b) => b.y - 15));
  bottom = Math.max(bottom, ...labelBoxes.map((b) => b.y + 15));
  const right = tier ? radius + 12 : width;
  const w = (width + right) / state.zoom,
    h = (bottom - top) / state.zoom;
  diagram.setAttribute(
    "viewBox",
    `${(right - width - w) / 2 + state.panX} ${(bottom + top - h) / 2 + state.panY} ${w} ${h}`,
  );
}

function updatePointOptions(selection, pointPicker, pointLabel) {
  const selectionKey = JSON.stringify([selection.area?.id, selection.path]);
  if (pointPicker.dataset.area !== selectionKey) {
    const available = selection.area ? selection.members : [];
    pointPicker.replaceChildren(
      el("option", { value: "" }, "すべて"),
      ...available.map((dot) =>
        el(
          "option",
          { value: dot.id },
          dot.entry ? `${dot.name} · ${dot.entry} · ${dot.source || dot.id}` : dot.name,
        ),
      ),
    );
    pointPicker.dataset.area = selectionKey;
    pointLabel.hidden = !available.length;
  }
  pointPicker.value = selection.point?.id || "";
}

function showSelectionDetails({ mesh, info, entries, fullMesh, selection }) {
  const { point: chosen, area } = selection;
  if (chosen) {
    showPointConnections(mesh, chosen, info, area, entries);
    showCallerChain(chosen, fullMesh, info);
  } else if (area) {
    showAreaSelection(info, area, selection, entries);
  } else if (selection.path) {
    const dots = selection.members;
    info.append(
      el(
        "p",
        null,
        el("strong", null, selection.path),
        ` · ${new Set(dots.map((dot) => dot.area)).size} 段 · ${dots.length} 点`,
      ),
    );
  }
}

function showPointConnections(mesh, chosen, info, area, entries) {
  const direct = mesh.edges.filter((e) => e.from === chosen.id || e.to === chosen.id);
  info.append(
    el(
      "p",
      null,
      el("strong", null, chosen.name),
      " · ",
      describe(area),
      chosen.entry ? [" · ", chosen.entry] : [],
      chosen.source ? [" · ", chosen.source] : [],
    ),
    el(
      "details",
      null,
      el("summary", null, `直接のつながり ${direct.length} 本`),
      el(
        "ul",
        null,
        direct.map((e) =>
          el(
            "li",
            null,
            mesh.dots.get(e.from).name,
            " → ",
            mesh.dots.get(e.to).name,
            entries.length > 1 ? " · " + mesh.dots.get(e.from).entry : "",
            e.unknown ? ` · ${term("unknown")}` : "",
          ),
        ),
      ),
    ),
  );
}

function showCallerChain(chosen, fullMesh, info) {
  if (chosen.entry) {
    const chain = callerChain(fullMesh, chosen.id);
    info.append(
      el(
        "p",
        { class: "tier-chain" },
        el("b", null, term("call_path")),
        " · ",
        chain.map((dot, i) => [i ? " → " : "", el("span", null, dot.area, " / ", dot.name)]),
      ),
    );
  }
}

function showAreaSelection(info, area, selection, entries) {
  info.append(
    el(
      "p",
      null,
      el("strong", null, describe(area), selection.path ? " · " + selection.path : ""),
      entries
        ? ` · この面に ${selection.members.length} 点 · 強調中の線 ${selection.visibleLineCount} 本`
        : "",
    ),
  );
  if (entries) {
    const { roots } = selection;
    if (roots.size)
      info.append(
        el(
          "details",
          null,
          el("summary", null, `この面に至る ${term("entry")} ${roots.size} 件`),
          el(
            "ul",
            null,
            [...roots].sort().map((path) => el("li", null, path)),
          ),
        ),
      );
  }
}
