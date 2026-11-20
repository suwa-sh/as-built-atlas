// 空間内の [x, 高さ, z]。tier の半径はプロファイルの順、円筒の側面は所属する layer ごとに分ける。
const TURN = Math.PI * 2;

function arc(x, h, z, rx, rz, start, end) {
  const steps = Math.max(2, Math.ceil(Math.abs(end - start) / TURN * 96));
  return Array.from({ length: steps + 1 }, (_, i) => {
    const a = start + (end - start) * i / steps;
    return [x + rx * Math.cos(a), h, z + rz * Math.sin(a)];
  });
}

export function radialLayout(layers, kinds, knownIds, labels, focusTier = "") {
  const tiers = new Map(), nodes = new Map(), discs = [];
  const groups = new Map(layers.map((l) => [l.id, l.tier || null]));
  const resources = new Map(kinds);
  for (const id of knownIds) {
    if (id.startsWith("/")) {
      const kind = id.slice(1);
      if (!resources.has(kind)) resources.set(kind, kind);
    } else if (!groups.has(id)) groups.set(id, null);
  }
  for (const [id, tier] of groups) {
    if (!tiers.has(tier)) tiers.set(tier, []);
    tiers.get(tier).push(id);
  }

  const ringWidth = 83;
  const stores = [...resources].filter(([id]) => id !== "external_api");
  const storeRadius = Math.max(88, stores.length * 16);
  const appRadius = storeRadius + tiers.size * ringWidth;
  const detail = tiers.get(focusTier);
  const detailStep = detail ? Math.min(28, 90 / detail.length) : 0;
  const radius = detail ? 90 + (detail.length - 1) * detailStep : resources.has("external_api") ? appRadius + ringWidth : appRadius;
  // 薄い円筒の間に余白を取る。既定の斜め視点でも隣の段の側面が重ならない間隔。
  const levelPitch = 72 + Math.ceil(radius * 0.43);
  function cylinder(type, tier, radius, members, bearing = -Math.PI / 2) {
    const top = -discs.length * levelPitch, bottom = top - 58;
    const faces = [];
    const panelTop = top - 5, panelBottom = bottom + 5;
    const step = TURN / members.length, gap = Math.min(0.055, step * 0.08);
    members.forEach(([id, label], i) => {
      const start = bearing + step * i + gap, end = start + step - 2 * gap;
      const mid = (start + end) / 2;
      const face = { id, label, tier: tier ?? labels.unknown, start, end, bottom: panelBottom, h: panelTop, x: 0, z: 0, rx: radius, rz: radius,
        point: [radius * Math.cos(mid), panelTop + 5, radius * Math.sin(mid)],
        topArc: arc(0, panelTop, 0, radius, radius, start, end) };
      nodes.set(id, face);
      faces.push(face);
    });
    discs.push({ type, declared: type === "app" && tier != null, tier: tier ?? labels.unknown, x: 0, z: 0, h: top, rx: radius, rz: radius, thickness: top - bottom, faces,
      rings: [bottom, top].map((h) => arc(0, h, 0, radius, radius, 0, TURN)) });
  }

  if (detail) {
    detail.forEach((id, i) => cylinder("layer", focusTier, radius - i * detailStep, [[id, id]]));
    return { nodes, discs, radius };
  }

  // 高さはアプリ、ストア、外部の順。真上では外部を最外周に置く。
  let index = 0;
  for (const [tier, ids] of tiers) {
    cylinder("app", tier, appRadius - index * ringWidth, ids.map((id) => [id, id]));
    index++;
  }
  if (stores.length) cylinder("store", labels.store, storeRadius,
    stores.map(([id, label]) => ["/" + id, label || id]), Math.PI / 4);
  if (resources.has("external_api")) cylinder("remote", labels.external, radius,
    [["/external_api", resources.get("external_api") || "external_api"]]);
  return { nodes, discs, radius };
}

// 輪郭で曲面を分けて後半分と前半分を別々に描く。入れ子の透明面も手前を選べる。
export function visibleWallParts(face, yaw) {
  const cuts = [face.start];
  for (let k = Math.floor((face.start + yaw) / Math.PI) + 1; k * Math.PI - yaw < face.end; k++) {
    cuts.push(k * Math.PI - yaw);
  }
  cuts.push(face.end);
  return cuts.slice(1).map((end, i) => {
    const start = cuts[i], front = Math.sin((start + end) / 2 + yaw) >= 0;
    const points = arc(face.x, face.h, face.z, face.rx, face.rz, start, end)
      .concat(arc(face.x, face.bottom, face.z, face.rx, face.rz, end, start));
    return { front, points };
  });
}

// 同じ入口の角度を全層で共有する。処理がある層と入口の組だけに曲面を作る。
export function pathPanels(nodes, dots) {
  const paths = [...new Set(Array.from(dots.values(), (dot) => dot.entry))];
  const slots = new Map(paths.map((path, i) => [path, i]));
  const byLayer = new Map([...nodes.keys()].map((id) => [id, new Map()]));
  const step = TURN / Math.max(1, paths.length), gap = Math.min(0.055, step * 0.08);
  for (const dot of dots.values()) {
    const panels = byLayer.get(dot.area);
    if (panels.has(dot.entry)) continue;
    const layer = nodes.get(dot.area), index = slots.get(dot.entry);
    const start = -Math.PI / 2 + step * index + gap, end = start + step - 2 * gap;
    const mid = (start + end) / 2;
    panels.set(dot.entry, { ...layer, path: dot.entry, number: index + 1, start, end,
      point: [layer.rx * Math.cos(mid), layer.h + 5, layer.rz * Math.sin(mid)],
      topArc: arc(0, layer.h, 0, layer.rx, layer.rz, start, end) });
  }
  return { paths, byLayer };
}
