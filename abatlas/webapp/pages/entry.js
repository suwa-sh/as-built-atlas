// 画面: 入口の詳細 (#/entry/<path>)。この入口が触るデータ・外部接続を並べ、選んだ相手までの経路を右に描く

import { el, fmt, isNum } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { hEntries, hEntry } from "../lib/hash.js";
import { rows, rowsAll, countOf } from "../lib/api.js";
import { model, titleOf, labelOf, showCols, physLink, entryLabel, hierarchyNotes, scopeFilter, attaches, kindOf, lineOf, opLabel } from "../model/catalog.js";
import { pathCrumbs } from "../ui/crumbs.js";
import { cardFor, loading, emptyMsg } from "../ui/card.js";
import { hrefFor } from "../ui/link.js";
import { pickTable } from "../ui/table.js";
import { panelBody, byView } from "../views/index.js";
import { routePanel, pendingRoute } from "../views/route.js";
import { nodeInfo, pageEntries } from "./entries.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");

// データの流れの辺 (読む = データ → 入口、書く = 入口 → データ) を、相手ごとにまとめる
function partners(ins, outs, gk) {
  const m = new Map();
  const add = (p, side, e) => {
    if (!m.has(p)) m.set(p, { path: p, read: new Set(), write: new Set(), unknown: false });
    const x = m.get(p);
    if (gk.label && e[gk.label]) for (const op of String(e[gk.label]).split(", ")) x[side].add(opLabel(p, op));
    if (gk.status && e[gk.status] === "unknown") x.unknown = true;
  };
  for (const e of ins.rows) add(String(e[gk.from]), "read", e);
  for (const e of outs.rows) add(String(e[gk.to]), "write", e);
  return [...m.values()].sort((a, b) => b.write.size - a.write.size || a.path.localeCompare(b.path));
}

export async function pageEntry(path) {
  if (!model.entryMart) { pageEntries("/"); return; }
  $main.replaceChildren(loading());
  const node = await nodeInfo(path);
  if (!node.isEntry) { pageEntries(path); return; }
  const r = node.row;
  const k = model.entryMart.keys;
  const cols = (model.entryMart.columns || []).map((c) => c.name);
  const show = showCols(model.entryMart, cols).filter((c) => c !== k.path && c !== k.label && c !== k.summary && c !== k.id);
  const name = k.label && r[k.label] ? r[k.label] : node.name;
  // 見出しの下の 1 行: 真の値は見出しの名前だけ (例: 分析済み)、偽の値は出さない、文字の値は「名前: 値」
  const facts = show.filter((c) => r[c] === true || (typeof r[c] === "string" && r[c] !== "")).map((c) => (r[c] === true ? labelOf(model.entryMart, c) : `${labelOf(model.entryMart, c)}: ${fmt(r[c])}`));
  const pre = segs(path).slice(0, -1);
  const nums = cols.filter((c) => isNum(r[c]) && !/^level\d$/.test(c) && c !== "depth");
  const self = { ...node, isLeaf: true }; // 図はこの入口そのものに絞る (子を持つ入口でも配下を混ぜない)
  const kindName = entryLabel(path, node.depth);
  const ln = lineOf(path);
  const parts = [pathCrumbs(path, hEntries, term("entry"), "#/entries"),
    el("div", { class: `head ${ln}` }, kindName ? el("span", { class: "badge" }, kindName) : null,
      el("div", null, el("h1", null, pre.length ? el("span", { class: "pre" }, "/" + pre.join("/") + "/") : null, name), el("p", { class: "sub" }, facts.join(" · "))))];
  // 入口が別の入口の中で動く関係 (例: 画面と、それを包む共通の枠)。包む側と包まれる側は別々に分析してあるので、行き来できるようにする
  let innerPaths = [];
  if (model.withinMart) {
    const m = model.withinMart;
    const [pc, mc] = [m.keys.path, m.keys.members];
    const ordered = m.keys.order && m.cols.has(m.keys.order) ? { order: m.keys.order } : {}; // 外側からの順 (宣言に無ければ mart の順)
    // 1 行 = 包まれる入口 × 包む入口。パスは 1 行に 1 つずつ持つ (文字列を区切って戻さない)
    const [mine, inner] = await Promise.all([rowsAll(m, { [pc]: path, ...ordered }), rowsAll(m, { [mc]: path })]).catch(() => [{ rows: [] }, { rows: [] }]);
    const outerPaths = mine.rows.map((row) => String(row[mc]));
    innerPaths = [...new Set(inner.rows.map((row) => String(row[pc])))].sort();
    if (outerPaths.length) {
      parts.push(el("ul", { class: "through", "aria-label": `${term("enclosing")} (外側から)` },
        outerPaths.map((p) => el("li", { class: lineOf(p) }, el("a", { href: hEntry(p) }, p))), el("li", { class: `here ${ln}` }, `この ${term("entry")}`)),
        el("p", { class: "note" }, `左が外側。${term("enclosing")} の ${term("frame")} と ${term("data_access")} は、この ${term("entry")} には含めていない。それぞれのページで見る`));
    }
  }
  // 要約
  // 未分析かどうかは、処理の行 (呼び出しの構造) があるかで決める。要約だけ確かめられなかった分析済みの入口は、分析済みとして扱う
  const t = model.treeMart;
  let analyzed = true; // 判定に使える表も列も宣言されていなければ、分析済みとして全部を出す
  try {
    if (t) analyzed = (await countOf(t, { [t.keys.group]: path })) > 0;
    else if (k.summary) analyzed = !!r[k.summary];
  } catch (e) {
    $main.replaceChildren(...parts, el("p", { class: "err" }, `この ${term("entry")} の分析結果を読めなかった: ${e.message}`), el("p", { class: "note" }, "ページを読み込み直す"));
    return;
  }
  if (!analyzed) {
    // まだ分析していない入口: 空の表や図を並べず、分かっていること (包む入口・中で動く入口) だけを出す
    parts.push(el("p", { class: "caveat" }, el("b", null, "まだ分析していない。"), `分析すると、ここに何をする ${term("frame")} かが入り、${term("dependencies")} と ${term("call_path")} が出る`),
      pendingRoute(path),
      el("p", { class: "note" }, `分析は、エージェントに ${term("entry")} の id を渡して頼む: `, el("code", null, String(r[k.id]))),
      ...(model.withinMart && parts.some((x) => x.classList && x.classList.contains("through")) ? [el("p", { class: "note" }, `${term("enclosing")} (上の並び) が ${term("analyzed")} なら、そこで行う ${term("frame")} と ${term("data_access")} は、そのページで見られる`)] : []));
      if (innerPaths.length) parts.push(el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", null, `${term("nested")} (${innerPaths.length})`)),
      el("ul", { class: "plain" }, innerPaths.map((p) => el("li", null, el("a", { href: hEntry(p) }, p))))));
    $main.replaceChildren(...parts);
    return;
  }
  if (k.summary && !r[k.summary]) parts.push(el("p", { class: "caveat" }, `この ${term("entry")} の ${term("summary")} は、分析で確かめられていない。${term("frame")} と ${term("data_access")} は下に出す`));
  if (k.summary && r[k.summary]) {
    // 要約は 4 行まで見せ、続きは押して開く (下の表と経路を最初の画面に入れるため)
    const sum = el("p", { class: "summary clamp" }, r[k.summary]);
    const more = el("button", { type: "button", class: "link", "aria-expanded": "false", onclick: () => { const open = sum.classList.toggle("clamp") === false; more.textContent = open ? `${term("summary")} を畳む` : `${term("summary")} の続きを読む`; more.setAttribute("aria-expanded", String(open)); } }, `${term("summary")} の続きを読む`);
    const moreP = el("p", { class: "note", hidden: true }, more);
    parts.push(sum, moreP);
    // 4 行で切れているかは描いてから測る (幅で変わるので、大きさが変わるたびに測り直す)。開いている間はボタンを残す
    const measure = () => { if (sum.classList.contains("clamp")) moreP.hidden = !(sum.scrollHeight > sum.clientHeight + 1); };
    if (typeof ResizeObserver === "function") new ResizeObserver(measure).observe(sum); else requestAnimationFrame(measure);
  }
  // 触るデータ・外部接続 (左) と、選んだ相手までの経路 (右)
  if (model.graphMart) {
    const gk = model.graphMart.keys;
    const [ins, outs] = await Promise.all([rowsAll(model.graphMart, { [gk.to]: path }), rowsAll(model.graphMart, { [gk.from]: path })]);
    const list = partners(ins, outs, gk);
    const title = el("div", { class: "card-head" }, el("h2", null, term("dependencies")), el("span", { class: "hint" }, `行を選ぶと、そこまでの ${term("call_path")} が出る`), physLink(model.graphMart, { [gk.path || gk.to]: path }));
    if (!list.length) parts.push(el("section", { class: "card" }, title, emptyMsg(`この ${term("entry")} は、${term("datastore")} も ${term("external")} も使わない`)));
    else {
      const pane = el("div", { class: "pane" });
      const opTags = (set, w) => set.size ? el("span", { class: "ops" }, [...set].map((t) => el("span", { class: `op${w ? " w" : ""}` }, t))) : "";
      const t = pickTable({
        label: term("dependencies"), rows: list,
        onPick: (x) => { const href = hrefFor(x.path); pane.replaceChildren(routePanel(path, { kind: "data", path: x.path, label: segs(x.path).slice(-1)[0] }, href ? { link: { href, text: `その ${term("referenced_by")} を見る` } } : {})); },
        cols: [
          { label: term("kind"), cls: "kind", cell: (x) => kindOf(segs(x.path)[0]).label },
          { label: term("target"), cls: "path", cell: (x) => { const href = hrefFor(x.path); const text = segs(x.path).slice(1).join("/"); return href ? el("a", { href, title: x.path }, text) : text; } },
          { label: term("read"), cell: (x) => opTags(x.read, false) },
          { label: term("write"), cell: (x) => opTags(x.write, true) },
          { label: "", cell: (x) => (x.unknown ? el("span", { class: "tag dash" }, term("has_unknown")) : "") },
        ],
      });
      parts.push(el("div", { class: "split" }, el("section", null, title, t.el), pane));
      t.pick(0);
    }
  }
  // タブ: 入口についての図 (subject entry、level entry、表以外) + 不明な点
  const tabs = [];
  for (const m of (model.subj.entry || []).filter((x) => x !== model.entryMart && x.declaration.level === "entry" && x.declaration.view !== "table" && attaches(x, node)).sort(byView)) {
    const f = scopeFilter(m, self);
    if (f === null) continue;
    tabs.push({ label: titleOf(m), make: () => cardFor(m, panelBody(m, f, { here: path }), f) });
  }
  for (const m of (model.subj.analysis || []).filter((x) => x.declaration.view === "table" && x.keys.path && x.cols.has(x.keys.path))) {
    const n = await countOf(m, { [m.keys.path]: path }).catch(() => null);
    tabs.push({ label: titleOf(m), n, make: () => cardFor(m, panelBody(m, { [m.keys.path]: path }, {}), { [m.keys.path]: path }) });
  }
  if (tabs.length) {
    const tabBar = el("div", { class: "tabs", role: "tablist" });
    const tabBody = el("div");
    let cur = 0;
    // ボタンは作り直さない (選んだあともフォーカスが残る)。左右の矢印キーで隣のタブへ移る
    const btns = tabs.map((t, i) => el("button", { type: "button", role: "tab", onclick: () => select(i),
      onkeydown: (ev) => { const d = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0; if (d) { ev.preventDefault(); select((i + d + tabs.length) % tabs.length, true); } } },
      t.label, t.n != null ? el("span", { class: "n" }, `(${t.n})`) : null));
    const select = (i, focus) => {
      cur = i;
      btns.forEach((b, j) => { b.classList.toggle("on", j === i); b.setAttribute("aria-selected", String(j === i)); b.tabIndex = j === i ? 0 : -1; });
      tabBody.replaceChildren(tabs[i].make());
      if (focus) btns[i].focus();
    };
    tabBar.append(...btns);
    tabBody.setAttribute("role", "tabpanel");
    select(0);
    parts.push(tabBar, tabBody);
  }
  // 下の段: 中で動く入口 / 同じ部品を使う入口 / 数字
  const trio = el("div", { class: "trio" });
  if (innerPaths.length) {
    const CAP = 12;
    trio.append(el("section", { class: "card" }, ...[el("div", { class: "card-head" }, el("h2", null, `${term("nested")} (${innerPaths.length})`)),
      el("ul", { class: "plain" }, innerPaths.slice(0, CAP).map((p) => el("li", null, el("a", { href: hEntry(p) }, p)))),
      innerPaths.length > CAP ? el("p", { class: "note" }, `ほか ${innerPaths.length - CAP} 件。`, physLink(model.withinMart, { [model.withinMart.keys.members]: path })) : null,
      el("p", { class: "note" }, `この ${term("entry")} の ${term("frame")} と ${term("data_access")} は、${term("nested")} のページには含めていない`)].filter(Boolean)));
  }
  if (model.frameMart) {
    const m = model.frameMart;
    const box = el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", null, `同じ ${term("shared_frame")} を使う ${term("entry")}`)), loading());
    trio.append(box);
    const CAP = 200; // 読む部品の行の上限 (この入口が使う部品の数で頭打ちになるが、念のため)
    rows(m, { [`${m.keys.members}__contains`]: path }, CAP).then((d) => {
      const others = new Set();
      for (const row of d.rows) {
        const members = String(row[m.keys.members] || "").split(", ");
        if (!members.includes(path)) continue; // 部分一致で拾った行のうち、この入口を実際に含む行だけ (/daily/a と /daily/ab を混ぜない)
        for (const p of members) if (p && p !== path) others.add(p);
      }
      // replaceChildren は null を文字 "null" にして描くので、無い部品は配列から除いて渡す
      box.replaceChildren(...[box.firstChild, others.size ? el("ul", { class: "plain" }, [...others].sort().map((p) => el("li", null, el("a", { href: hEntry(p) }, p)))) : emptyMsg("無し"),
      d.total > d.rows.length ? el("p", { class: "note" }, `${term("shared_frame")} の行が ${d.total} 件あり、先頭 ${d.rows.length} 件から集めた`) : null,
        el("p", { class: "note" }, el("a", { href: "#/frames" }, `${term("shared_frame")} の一覧`))].filter(Boolean));
    }).catch((e) => box.replaceChildren(el("p", { class: "err" }, e.message)));
  }
  if (nums.length) trio.append(el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", null, `この ${term("entry")} の数字`)), el("div", { class: "nums" }, nums.flatMap((c) => [el("span", { class: "k" }, labelOf(model.entryMart, c)), el("span", { class: "v" }, fmt(r[c]))]))));
  if (trio.children.length) parts.push(trio);
  parts.push(...hierarchyNotes(path).map((t) => el("p", { class: "note" }, t)));
  $main.replaceChildren(...parts.filter(Boolean));
}
