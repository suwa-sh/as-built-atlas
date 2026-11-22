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
  return (
    model.treeMart?.cols.has(model.treeMart.keys.tag) &&
    model.seqMart?.cols.has(model.seqMart.keys.group)
  );
}

export function sectionExplorer(layers, initial, flow, initialTier) {
  return new SectionExplorer().mount(layers, initial, flow, initialTier);
}

class SectionExplorer {
  constructor() {
    this.read = this.read.bind(this);
    this.show = this.show.bind(this);
  }

  mount(layers, initial, flow, initialTier) {
    this.layers = layers;
    this.initial = initial;

    const knownIds = new Set();

    const k = model.layerMart?.keys;

    if (k)
      for (const r of flow?.rows || [])
        for (const col of [k.from, k.to]) if (r[col]) knownIds.add(String(r[col]));

    this.camera = {
      yaw: 0,
      pitch: 12,
      zoom: 1,
      panX: 0,
      panY: 0,
      knownIds,
      drillTier: initialTier || "",
    };

    this.filters = el("div", { class: "tier-scene-filters" });

    if (!supportsSection()) {
      const view = tierScene(
        this.layers,
        null,
        this.camera,
        (tier) => this.updateLocation(this.initial, tier),
        this.filters,
      );
      return el("section", { class: "section-explorer" }, this.filters, view);
    }

    this.mart = model.treeMart;

    this.createEntryControls();

    this.choices = [];
    this.sections = new Map();

    this.total = 0;
    this.limit = BATCH;
    this.generation = 0;
    this.loadingPage = null;

    if (this.initial) {
      this.select.append(el("option", { value: this.initial }, this.initial));
      this.select.value = this.initial;
    }

    this.listenToEntries();

    this.show();

    return this.host;
  }
  createEntryControls() {
    this.select = el(
      "select",
      { "aria-label": term("entry") },
      el("option", { value: "" }, "重ねて表示"),
    );

    this.more = el("button", { hidden: true, type: "button" }, "候補をさらに表示");

    this.stack = el("button", { hidden: true, type: "button" }, `さらに ${BATCH} 件を重ねる`);

    this.count = el("span", { class: "count", role: "status" });

    this.body = el("div", null, loading());

    this.detail = el("a", { class: "more", hidden: true }, "詳細を開く");

    const controls = el(
      "div",
      { class: "section-picker" },
      el(
        "div",
        { class: "toolbar tier-filters" },
        el("label", null, term("entry"), this.select),
        this.filters,
      ),
      el(
        "div",
        { class: "toolbar tier-entry-actions" },
        this.more,
        this.stack,
        this.count,
        this.detail,
      ),
    );

    this.host = el("section", { class: "section-explorer" }, controls, this.body);
  }
  listenToEntries() {
    this.select.addEventListener("change", () => {
      this.updateLocation(this.select.value, this.camera.drillTier);
      this.show();
    });

    this.more.addEventListener("click", () =>
      this.loadChoices().catch((e) => {
        this.count.textContent = e.message;
      }),
    );

    this.stack.addEventListener("click", () => {
      this.limit += BATCH;
      this.show();
    });
  }

  updateLocation(entry, tier) {
    const query = new URLSearchParams({ view: "3d" });
    if (entry) query.set("entry", entry);
    if (tier) query.set("focusTier", tier);
    history.replaceState(null, "", "#/overview?" + query);
  }

  loadChoices() {
    if (this.loadingPage) return this.loadingPage;
    this.more.disabled = true;
    this.loadingPage = groups(this.mart, {
      by: this.mart.keys.group,
      order: "key",
      limit: PAGE,
      offset: this.choices.length,
    })
      .then((data) => {
        this.total = data.total;
        for (const { key } of data.groups) {
          this.choices.push(key);
          if (key !== this.initial) this.select.append(el("option", { value: key }, key));
        }
        this.more.hidden = this.choices.length >= this.total;
      })
      .finally(() => {
        this.more.disabled = false;
        this.loadingPage = null;
      });
    return this.loadingPage;
  }

  async read(path) {
    if (!this.sections.has(path))
      this.sections.set(
        path,
        loadEntry(path)
          .then((data) => sectionData(this.layers, data))
          .catch((e) => {
            this.sections.delete(path);
            throw e;
          }),
      );
    return { path, section: await this.sections.get(path) };
  }

  async show() {
    const gen = ++this.generation,
      path = this.select.value;
    this.detail.hidden = !path;
    this.detail.href = hEntry(path);
    this.stack.hidden = true;
    this.count.textContent = "";
    this.filters.replaceChildren();
    this.body.replaceChildren(loading());
    try {
      const paths = await this.visibleEntryPaths(path);
      const entries = await Promise.all(paths.map(this.read));
      if (gen !== this.generation) return;
      if (path && !entries[0].section.frames.size) {
        this.body.replaceChildren(pendingRoute(path));
        return;
      }
      this.renderEntries(entries, path, paths);
    } catch (e) {
      if (gen === this.generation)
        this.body.replaceChildren(
          el("p", { class: "err" }, e.message),
          el("button", { onclick: this.show }, "再試行"),
        );
    }
  }

  async visibleEntryPaths(path) {
    if (!this.choices.length || (!path && this.choices.length < Math.min(this.total, this.limit)))
      await this.loadChoices();
    const paths = path ? [path] : this.choices.slice(0, this.limit);
    return paths;
  }

  renderEntries(entries, path, paths) {
    const parts = [
      tierScene(
        this.layers,
        entries,
        this.camera,
        (tier) => this.updateLocation(path, tier),
        this.filters,
      ),
    ];
    if (path) {
      const box = el(
        "details",
        { class: "section-functions" },
        el("summary", null, `${term("frame")} ごとの断面図`),
      );
      box.addEventListener("toggle", () => {
        if (box.open && box.childElementCount === 1)
          box.append(sectionDiagram(path, entries[0].section));
      });
      parts.push(box);
    } else {
      this.count.textContent = `${paths.length} / ${this.total} ${term("entry")} を表示`;
      this.stack.hidden = paths.length >= this.total;
      this.stack.textContent = `さらに ${Math.min(BATCH, this.total - paths.length)} 件を重ねる`;
      if (paths.length)
        parts.push(
          el(
            "details",
            { class: "section-functions" },
            el("summary", null, `表示中の ${term("entry")}`),
            el(
              "ul",
              null,
              paths.map((p) => el("li", null, el("a", { href: hEntry(p) }, p))),
            ),
          ),
        );
    }
    this.body.replaceChildren(...parts);
  }
}
