// 点は入口内の一つのフレーム、または読み書きの相手。フレーム ID の有効範囲はその入口だけ。
export function callMesh(entries) {
  const dots = new Map(),
    edges = [];
  for (const { path, section } of entries) {
    const frameKey = (id) => JSON.stringify([path, id]);
    for (const f of section.frames.values()) {
      const id = frameKey(f.id);
      dots.set(id, {
        id,
        area: f.layer,
        name: f.name,
        source: f.source,
        entry: path,
        root: f.parent == null,
        parent: section.frames.has(f.parent) ? frameKey(f.parent) : null,
      });
      if (section.frames.has(f.parent))
        edges.push({ from: frameKey(f.parent), to: id, unknown: f.unknown });
    }
    for (const t of section.targets.values()) {
      const id = t.path,
        area = "/" + id.split("/")[1];
      if (!dots.has(id)) dots.set(id, { id, area, name: id });
      for (const [origin, unknown] of t.origins) {
        if (section.frames.has(origin))
          edges.push({ from: frameKey(origin), to: id, unknown: Boolean(unknown) });
      }
    }
  }
  return { dots, edges };
}

// 同じ点は入口を追加・絞り込みしても同じ位置。すべての点を所属する曲面の半径に固定し、角度と高さを分散する。
export function pointOnFace(face, key) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  const u = (h & 65535) / 65535,
    v = (h >>> 16) / 65535;
  const a = face.start + (face.end - face.start) * (0.065 + 0.87 * u);
  const height = face.bottom + (face.h - face.bottom) * (0.07 + 0.86 * v);
  return [face.x + face.rx * Math.cos(a), height, face.z + face.rz * Math.sin(a)];
}

// 面または個別に選んだ点への祖先を入口までまとめて遡る。複数の入口が触る資源には各入口の経路が残る。
export function traceSelection(mesh, selectedIds) {
  const selected = new Set(selectedIds),
    keep = new Set(selected),
    incoming = new Map();
  const lines = new Set();
  for (const e of mesh.edges) {
    if (!incoming.has(e.to)) incoming.set(e.to, []);
    incoming.get(e.to).push(e);
    if (selected.has(e.from)) {
      lines.add(e);
      keep.add(e.to);
    }
  }
  // 遡る起点は選択した点だけ。直接の呼び先を共有する別枝まで混ぜない。
  const pending = [...selected],
    seen = new Set();
  while (pending.length) {
    const cur = pending.pop();
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const e of incoming.get(cur) || []) {
      lines.add(e);
      keep.add(e.from);
      pending.push(e.from);
    }
  }
  return { keep, lines };
}

// 詳細の点と線は全体と同じ実体を使う。別の区分を経由する親子を短絡しない。
export function layerMesh(mesh, faces) {
  const dots = new Map([...mesh.dots].filter(([, dot]) => dot.entry && faces.has(dot.area)));
  return { dots, edges: mesh.edges.filter((edge) => dots.has(edge.from) && dots.has(edge.to)) };
}

export function callerChain(mesh, id) {
  const path = [],
    seen = new Set();
  let dot = mesh.dots.get(id);
  while (dot?.entry && !seen.has(dot.id)) {
    path.push(dot);
    seen.add(dot.id);
    dot = mesh.dots.get(dot.parent);
  }
  return path.reverse();
}

// 選択欄の範囲と、図で強調する実体を一度決める。段全体の一覧から点を選んでも、
// 強調する面はその点の入口に限る。祖先は詳細図の外も含む全体のグラフで求める。
export function resolveTierSelection({ nodes, mesh, fullMesh, panels }, choice = {}) {
  const area = nodes.get(choice.area);
  const path = selectionPath(area, panels, choice);
  const { point, members } = selectionMembers(area, path, mesh, choice);
  const trace =
    area || path
      ? traceSelection(fullMesh, point ? [point.id] : members.map((dot) => dot.id))
      : null;
  const chosenFaces = new Set(),
    visitedFaces = new Set(),
    roots = new Set();
  collectChosenFaces(panels, point, path, members, chosenFaces, area);

  collectTraceFaces(trace, fullMesh, panels, nodes, visitedFaces, roots);
  const visibleLineCount = trace ? mesh.edges.filter((edge) => trace.lines.has(edge)).length : 0;
  return { area, path, point, members, trace, chosenFaces, visitedFaces, roots, visibleLineCount };
}

function selectionPath(area, panels, choice) {
  const paths = area ? panels?.byLayer.get(area.id) : null;
  const validPath = area ? paths?.has(choice.path) : panels?.paths.includes(choice.path);
  const path = validPath ? choice.path : "";
  return path;
}

function selectionMembers(area, path, mesh, choice) {
  const members =
    area || path
      ? [...mesh.dots.values()].filter(
          (dot) => (!area || dot.area === area.id) && (!path || dot.entry === path),
        )
      : [];
  const point = choice.point ? members.find((dot) => dot.id === choice.point) : undefined;
  return { point, members };
}

function collectChosenFaces(panels, point, path, members, chosenFaces, area) {
  if (panels) {
    const selectedPath = point?.entry || path;
    for (const dot of members) {
      if (!selectedPath || dot.entry === selectedPath)
        chosenFaces.add(panels.byLayer.get(dot.area).get(dot.entry));
    }
  } else if (area) chosenFaces.add(area);
}

function collectTraceFaces(trace, fullMesh, panels, nodes, visitedFaces, roots) {
  for (const id of trace?.keep || []) {
    const dot = fullMesh.dots.get(id);
    const face = panels ? panels.byLayer.get(dot.area)?.get(dot.entry) : nodes.get(dot.area);
    if (face) visitedFaces.add(face);
    if (dot.root) roots.add(dot.entry);
  }
}
