/* as-built-atlas webapp (起動: カタログ読込 → ナビ → 経路)。
 * mart の宣言 (meta.abatlas: subject / title / hint / view / keys / show / labels / filters) と meta (プロファイルの階層ラベル、データの種類の語彙)
 * だけを読んで画面を組む。mart の名前は知らない。読む API は MCP と同じ:
 *   GET /meta, GET /marts, GET /marts/{name}/rows, GET /marts/{name}/tree, POST /marts/{name}/pivot, POST /recompute
 * 区分 (ナビ): 構成 / 入口 / データ / 外部接続 / 共有処理 / 分析の状態 / 集計表。区分は subject を持つ mart がある場合だけ出る。
 * 自己完結 (外部の script / style / font を読まない)。
 * 層 (上から): app.js (起動) > pages/ (画面) > views/ (表示の種類) > ui/ (汎用部品) > model/ (宣言の読み方) > lib/ (道具)。
 *   上の層は下の層 (と同じ層) だけを import できる。向きは tests/test_webapp.py が検査する。足し方は docs/architecture/README.md の webapp の節。
 */

import { el } from "./lib/dom.js";
import { enc, decPath } from "./lib/hash.js";
import { tree, countOf } from "./lib/api.js";
import { model, loadCatalog, progressOf } from "./model/catalog.js";
import { term } from "./model/vocab.js";
import { loading } from "./ui/card.js";
import { hideCtxGlobal } from "./views/matrix.js";
import { clearRouteCache } from "./views/route.js";
import { pageOverview } from "./pages/overview.js";
import { pageEntries } from "./pages/entries.js";
import { pageEntry } from "./pages/entry.js";
import { pageDataKind } from "./pages/data.js";
import { pageAccess } from "./pages/access.js";
import { pageSubjectList } from "./pages/subject.js";
import { pageStatus } from "./pages/status.js";
import { pageAspects } from "./pages/aspects.js";
import { pageMarts, pageMart } from "./pages/marts.js";

const $main = document.getElementById("main");
const $nav = document.getElementById("nav");

// ------------------------------------------------------------ ナビ
async function buildNav() {
  const items = [];
  const sec = (hash, label, n, extra) => el("a", { class: `item${extra && extra.dim ? " dim" : ""}`, href: hash, "data-sec": hash }, label, n != null ? el("span", { class: "n" }, n) : null);
  const [prog, ext, frm] = await Promise.all([progressOf(), ...["external", "frame"].map((s) => { const m = (model.subj[s] || []).find((x) => x.declaration.view === "table"); return m ? countOf(m, {}).catch(() => null) : null; })]);
  // ナビは区分だけ (件数つき)。区分の中の段は、それぞれのページで降りる
  if (hasLayers()) items.push(sec("#/overview", term("architecture")));
  if (model.subj.entry) items.push(sec("#/entries", term("entry"), model.entryMart ? await countOf(model.entryMart, {}).catch(() => null) : null));
  if (model.subj.data) {
    const kinds = model.dataMart ? await tree(model.dataMart, model.dataMart.keys.col, "/").catch(() => []) : [];
    items.push(sec("#/data", term("datastore"), kinds.reduce((x, c) => x + c.leaves, 0) || null));
  }
  if (model.subj.external) items.push(sec("#/external", term("external"), ext));
  if (model.subj.frame) items.push(sec("#/frames", term("shared_frame"), frm));
  if (model.subj.aspect) items.push(sec("#/aspects", term("aspects"), model.subj.aspect.length));
  if (model.subj.analysis) items.push(sec("#/status", term("analysis_status"), prog ? `${prog.done} / ${prog.total}` : null));
  items.push(el("hr"));
  items.push(sec("#/marts", `${term("mart")} (API / MCP)`, null, { dim: true }));
  $nav.replaceChildren(...items);
  markNav();
}
// 最初に開くページ: 層の並びがあれば構成、無ければ入口
const hasLayers = () => Array.isArray((model.meta.profile || {}).layers) && model.meta.profile.layers.length > 0;
const home = () => (hasLayers() ? "#/overview" : "#/entries");
function markNav() {
  const h = !location.hash || location.hash === "#/" ? home() : location.hash;
  let best = null;
  for (const a of $nav.querySelectorAll("[data-sec]")) {
    const s = a.dataset.sec;
    const match = h === s || h.startsWith(s + "/") || h.startsWith(s + "?") ||
      (s === "#/entries" && h.startsWith("#/entry")) || (s === "#/data" && h.startsWith("#/access")) ||
      (s === "#/marts" && h.startsWith("#/mart/")) || (s.startsWith("#/data/") && h.startsWith("#/access/" + s.slice(7)));
    a.classList.remove("active");
    if (match && (!best || s.length > best.dataset.sec.length)) best = a;
  }
  if (best) best.classList.add("active");
}

// ------------------------------------------------------------ 経路と起動
function route() {
  hideCtxGlobal();
  const raw = !location.hash || location.hash === "#/" ? home() : location.hash;
  const qi = raw.indexOf("?");
  const path = qi < 0 ? raw : raw.slice(0, qi);
  const query = new URLSearchParams(qi < 0 ? "" : raw.slice(qi + 1));
  markNav();
  document.getElementById("side").classList.remove("open");
  document.getElementById("menu").setAttribute("aria-expanded", "false");
  if (!model.catalog.length) return;
  window.scrollTo(0, 0);
  let mm;
  if (path === "#/overview") return pageOverview();
  if (path === "#/entries" || path === "#/entries/") return pageEntries("/");
  if ((mm = /^#\/entries(\/.*)$/.exec(path))) return pageEntries(decPath(mm[1]));
  if ((mm = /^#\/entry(\/.*)$/.exec(path))) return pageEntry(decPath(mm[1]));
  if (path === "#/data") return pageAccess(null, "/", query);
  if ((mm = /^#\/data\/([^/]+)(\/.*)?$/.exec(path))) return pageDataKind(decodeURIComponent(mm[1]), decPath(mm[2]));
  if ((mm = /^#\/access\/([^/]+)(\/.*)?$/.exec(path))) return pageAccess(decodeURIComponent(mm[1]), decPath(mm[2]), query);
  if ((mm = /^#\/external(?:\/(.+))?$/.exec(path))) return pageSubjectList("external", term("external"), `${term("host")} ごとに、それを呼ぶ ${term("entry")}。切り替えると誰が影響を受けるか`, Object.assign((m, id) => `#/external/${enc(m.name)}/${enc(id)}`, { root: "#/external" }), mm[1] || null);
  if ((mm = /^#\/frames(?:\/(.+))?$/.exec(path))) return pageSubjectList("frame", term("shared_frame"), `2 件以上の ${term("entry")} から呼ばれている ${term("frame")}。直すと全部に影響する`, Object.assign((m, id) => `#/frames/${enc(m.name)}/${enc(id)}`, { root: "#/frames" }), mm[1] || null);
  if ((mm = /^#\/aspects(?:\/(.+))?$/.exec(path))) return pageAspects(mm[1] ? decodeURIComponent(mm[1]) : null);
  if (path === "#/status" || path === "#/monitor") return pageStatus();
  if (path === "#/marts") return pageMarts();
  if ((mm = /^#\/mart\/(.+)$/.exec(path))) return pageMart(decodeURIComponent(mm[1]), query);
  if (path.startsWith("#/h")) return pageEntries(decPath(path.slice(3))); // 旧 URL
  return pageEntries("/");
}

// 分析対象の名前を、メニューの見出しとタブに出す (meta に無い古い集計では、道具の名前のまま)
function showTarget() {
  const t = model.meta.target;
  if (!t || !t.name) return;
  const commit = t.commit ? String(t.commit).slice(0, 7) : "";
  document.getElementById("brand-name").textContent = t.name;
  document.getElementById("brand").title = t.repo || t.name;
  const sub = document.getElementById("brand-sub");
  sub.textContent = commit;
  sub.hidden = !commit;
  document.title = `${t.name} — as-built-atlas`;
  const prof = model.meta.profile || {};
  document.getElementById("foot-detail").textContent = ["", t.repo, commit, prof.id ? `profile ${prof.id}` : ""].filter((x, i) => i === 0 || x).join(" · ");
}

async function boot() {
  $main.replaceChildren(loading());
  try {
    await loadCatalog();
    // 用語集の無い集計表 (古い版の build) は、呼び名を引けない。id のまま出さず、作り直しを促して止める
    // 今の画面が使う呼び名の id が欠けている集計表 (配布物を新しくして、集計し直していない) も同じ
    if (!model.meta.terms || !Object.keys(model.meta.terms).length || (Array.isArray(model.meta.missing_terms) && model.meta.missing_terms.length)) {
      $main.replaceChildren(el("div", { class: "head" }, el("div", null, el("h1", null, `${term("mart")} が古い版で作られている`))),
        el("p", { class: "note" }, "今の画面が読む情報が入っていない。build し直す (docker compose run --rm abatlas build .)"));
      return;
    }
    showTarget();
    clearRouteCache();
    await buildNav();
    route();
  } catch (e) {
    $main.replaceChildren(el("div", { class: "head" }, el("div", null, el("h1", null, `${term("mart")} を読めない`))), el("p", { class: "err" }, e.message),
      el("p", { class: "note" }, `先に build する (docker compose run --rm abatlas build .)。build 済みなら「${term("analysis_status")}」の「${term("mart")} を ${term("rebuild")}」でやり直せる`));
  }
}
window.addEventListener("hashchange", route);
document.addEventListener("click", hideCtxGlobal);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") hideCtxGlobal(); });
document.getElementById("menu").addEventListener("click", (ev) => ev.currentTarget.setAttribute("aria-expanded", String(document.getElementById("side").classList.toggle("open"))));
// メニューを畳む (広い画面)。畳んだ状態はこのブラウザに覚える (覚えられなくても動く)
const $shell = document.getElementById("shell"), $fold = document.getElementById("fold");
function setFolded(on) {
  $shell.classList.toggle("folded", on);
  $fold.textContent = on ? "›" : "‹";
  $fold.setAttribute("aria-expanded", String(!on));
  for (const a of ["aria-label", "title"]) $fold.setAttribute(a, on ? "メニューを開く" : "メニューを畳む");
}
$fold.addEventListener("click", () => {
  const on = !$shell.classList.contains("folded");
  setFolded(on);
  try { localStorage.setItem("abatlas.nav.folded", on ? "1" : "0"); } catch (e) { /* 覚えられない環境 */ }
});
try { if (localStorage.getItem("abatlas.nav.folded") === "1") setFolded(true); } catch (e) { /* 既定 (開いたまま) */ }
document.addEventListener("abatlas:reload", boot); // 下の層 (画面) からの「読み直して」。再計算の後に発火する
boot();
