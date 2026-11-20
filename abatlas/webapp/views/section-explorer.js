// 最初の 3 入口を重ねる。追加・個別選択はその入口の tree と sequence だけを読む。
import { el } from "../lib/dom.js";
import { hEntry } from "../lib/hash.js";
import { groups, PAGE } from "../lib/api.js";
import { model } from "../model/catalog.js";
import { term } from "../model/vocab.js";
import { loading } from "../ui/card.js";
import { loadEntry, pendingRoute } from "./route.js";
import { tierScene } from "./tier-scene.js";
import { sectionData, sectionDiagram } from "./section-diagram.js";

const BATCH = 3;
export function supportsSection() {
  return model.treeMart?.cols.has(model.treeMart.keys.tag)
    && model.seqMart?.cols.has(model.seqMart.keys.group);
}

export function sectionExplorer(layers, initial, flow, initialTier) {
  const knownIds = new Set();
  const k = model.layerMart?.keys;
  if (k) for (const r of flow?.rows || []) for (const col of [k.from, k.to]) if (r[col]) knownIds.add(String(r[col]));
  const camera = { yaw: 0, pitch: 12, zoom: 1, panX: 0, panY: 0, knownIds, drillTier: initialTier || "" };
  function updateLocation(entry, tier) {
    const query = new URLSearchParams({ view: "3d" });
    if (entry) query.set("entry", entry);
    if (tier) query.set("focusTier", tier);
    history.replaceState(null, "", "#/overview?" + query);
  }
  const filters = el("div", { class: "tier-scene-filters" });
  if (!supportsSection()) {
    const view = tierScene(layers, null, camera, (tier) => updateLocation(initial, tier), filters);
    return el("section", { class: "section-explorer" }, filters, view);
  }
  const mart = model.treeMart;
  const select = el("select", { "aria-label": term("entry") }, el("option", { value: "" }, "重ねて表示"));
  const more = el("button", { hidden: true, type: "button" }, "候補をさらに表示");
  const stack = el("button", { hidden: true, type: "button" }, `さらに ${BATCH} 件を重ねる`);
  const count = el("span", { class: "count", role: "status" });
  const body = el("div", null, loading());
  const detail = el("a", { class: "more", hidden: true }, "詳細を開く");
  const controls = el("div", { class: "section-picker" },
    el("div", { class: "toolbar tier-filters" }, el("label", null, term("entry"), select), filters),
    el("div", { class: "toolbar tier-entry-actions" }, more, stack, count, detail));
  const host = el("section", { class: "section-explorer" }, controls, body);
  const choices = [], sections = new Map();
  let total = 0, limit = BATCH, generation = 0, loadingPage = null;
  function loadChoices() {
    if (loadingPage) return loadingPage;
    more.disabled = true;
    loadingPage = groups(mart, { by: mart.keys.group, order: "key", limit: PAGE, offset: choices.length }).then((data) => {
      total = data.total;
      for (const { key } of data.groups) {
        choices.push(key);
        if (key !== initial) select.append(el("option", { value: key }, key));
      }
      more.hidden = choices.length >= total;
    }).finally(() => { more.disabled = false; loadingPage = null; });
    return loadingPage;
  }
  async function read(path) {
    if (!sections.has(path)) sections.set(path, loadEntry(path).then((data) => sectionData(layers, data))
      .catch((e) => { sections.delete(path); throw e; }));
    return { path, section: await sections.get(path) };
  }
  async function show() {
    const gen = ++generation, path = select.value;
    detail.hidden = !path; detail.href = hEntry(path);
    stack.hidden = true; count.textContent = "";
    filters.replaceChildren();
    body.replaceChildren(loading());
    try {
      if (!choices.length || (!path && choices.length < Math.min(total, limit))) await loadChoices();
      const paths = path ? [path] : choices.slice(0, limit);
      const entries = await Promise.all(paths.map(read));
      if (gen !== generation) return;
      if (path && !entries[0].section.frames.size) { body.replaceChildren(pendingRoute(path)); return; }
      const parts = [tierScene(layers, entries, camera, (tier) => updateLocation(path, tier), filters)];
      if (path) {
        const box = el("details", { class: "section-functions" }, el("summary", null, `${term("frame")} ごとの断面図`));
        box.addEventListener("toggle", () => {
          if (box.open && box.childElementCount === 1) box.append(sectionDiagram(path, entries[0].section));
        });
        parts.push(box);
      } else {
        count.textContent = `${paths.length} / ${total} ${term("entry")} を表示`;
        stack.hidden = paths.length >= total;
        stack.textContent = `さらに ${Math.min(BATCH, total - paths.length)} 件を重ねる`;
        if (paths.length) parts.push(el("details", { class: "section-functions" }, el("summary", null, `表示中の ${term("entry")}`),
          el("ul", null, paths.map((p) => el("li", null, el("a", { href: hEntry(p) }, p))))));
      }
      body.replaceChildren(...parts);
    } catch (e) {
      if (gen === generation) body.replaceChildren(el("p", { class: "err" }, e.message), el("button", { onclick: show }, "再試行"));
    }
  }
  if (initial) { select.append(el("option", { value: initial }, initial)); select.value = initial; }
  select.addEventListener("change", () => {
    updateLocation(select.value, camera.drillTier);
    show();
  });
  more.addEventListener("click", () => loadChoices().catch((e) => { count.textContent = e.message; }));
  stack.addEventListener("click", () => { limit += BATCH; show(); });
  show();
  return host;
}
