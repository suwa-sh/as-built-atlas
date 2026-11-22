// 表示の種類: 経路。入口から終点 (データ・外部接続・探している部品) までを、1 本の路線として縦に描く。
// 元は 2 つの表: 呼び出しの構造 (tree。駅 = 処理の段) と、処理の流れ (sequence。keys.node が、読み書きを起こした処理の id)。
// 駅 = 処理の段 / 乗換駅 = ほかの入口も通る部品 (共有処理の表に載っているもの) / 終点 = 読み書きの相手か、探している部品

import { el, fmt, isPathLike } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { hSubject } from "../lib/hash.js";
import { rows, rowsAll } from "../lib/api.js";
import { model, lineOf, opLabel, isWrite } from "../model/catalog.js";
import { loading, emptyMsg } from "../ui/card.js";
import { hrefFor } from "../ui/link.js";
import { term } from "../model/vocab.js";

const cache = new Map(); // 入口のパス → その入口の駅と読み書き (同じ入口を選び直しても読み直さない)
export function clearRouteCache() {
  cache.clear();
}
export function loadEntry(path) {
  if (!cache.has(path)) {
    const t = model.treeMart,
      s = model.seqMart;
    cache.set(
      path,
      Promise.all([
        rowsAll(t, { [t.keys.group]: path }),
        s ? rowsAll(s, { [s.keys.group]: path }) : Promise.resolve({ rows: [] }),
      ])
        .then(([a, b]) => ({ frames: a.rows, msgs: b.rows }))
        .catch((e) => {
          cache.delete(path);
          throw e;
        }),
    ); // 失敗は残さない (選び直すと読み直す)
  }
  return cache.get(path);
}
const under = (p, root) => p === root || p.startsWith(root + "/");
// 定義場所 (file:line) のファイルの部分
const fileOf = (src) => String(src || "").replace(/:\d+$/, "");

// 終点の名前は、種類の段を除いたパス (種類は操作の札と行き先のページで分かる)
function resLink(p) {
  const text = segs(p).slice(1).join("/") || p,
    href = hrefFor(p);
  return href ? el("a", { href, title: p }, text) : el("span", { title: p }, text);
}
function copyButton(text) {
  if (!navigator.clipboard) return null; // http で LAN から開いたときは使えない
  const b = el(
    "button",
    { type: "button", class: "copy", title: `${term("evidence")} をコピーする` },
    "コピー",
  );
  b.addEventListener("click", () =>
    navigator.clipboard
      .writeText(text)
      .then(() => {
        b.textContent = "コピーした";
        setTimeout(() => (b.textContent = "コピー"), 1500);
      })
      .catch(() => {}),
  );
  return b;
}

// target: { kind: "data", path, label } (データ・外部接続のパス。配下も含む) か { kind: "frame", name, label } (部品の名前)
// opts.link: 見出しの右に出すリンク ({ href, text })
export function routePanel(entryPath, target, opts) {
  const o = opts || {};
  const head = el(
    "div",
    { class: "route-head" },
    el("h2", null, term("call_path")),
    el("span", { class: "of" }, `${entryPath} から ${target.label}`),
    o.link ? el("a", { class: "right", href: o.link.href }, o.link.text) : null,
  );
  const body = el("div", null, loading());
  const status = el("p", { class: "sr", role: "status" }); // 読み上げには短い 1 行だけ知らせる (駅を全部読み上げない)
  const box = el("section", null, head, status, body);
  if (!model.treeMart || (target.kind === "data" && !model.seqMart)) {
    body.replaceChildren(
      emptyMsg(
        `${term("call_path")} を引くための表が宣言されていない (tree の表と、keys.node を持つ sequence の表が要る)`,
      ),
    );
    return box;
  }
  loadEntry(entryPath)
    .then((d) => {
      const r = draw(entryPath, target, d);
      body.replaceChildren(...r.nodes);
      status.textContent = r.stations
        ? `${entryPath} から ${target.label} までの ${term("call_path")}。${term("hop")} ${r.stations} つ`
        : `${entryPath} から ${target.label} までの ${term("call_path")} は無い`;
    })
    .catch((e) => body.replaceChildren(el("p", { class: "err" }, e.message)));
  return box;
}

function draw(entryPath, target, d) {
  return new RouteDiagram().mount(entryPath, target, d);
}

class RouteDiagram {
  mount(entryPath, target, d) {
    this.target = target;

    this.tk = model.treeMart.keys;

    const sk = model.seqMart ? model.seqMart.keys : {};

    if (!d.frames.length) return { stations: 0, nodes: [pendingRoute(entryPath)] };

    this.byId = new Map(d.frames.map((r) => [String(r[this.tk.id]), r]));

    // 終点: 処理の id → その処理が終点に対して行うこと
    const { addEnd, ends } = endpointCollector();
    this.ends = ends;

    if (this.target.kind === "data") {
      collectDataEndpoints(d, sk, this.target, this.byId, addEnd);
    } else {
      // 同じ名前でも定義場所が違えば別の処理。定義場所が分かるとき (target.sources) は、それも合うものだけを終点にする
      collectFrameEndpoints(this.target, this.tk, d, this.ends);
    }

    if (!this.ends.size)
      return {
        stations: 0,
        nodes: [
          emptyMsg(`この ${term("entry")} の分析結果には、ここへ着く ${term("call_path")} が無い`),
        ],
      };

    // 終点から入口へ遡り、通る駅だけを残す
    const keep = ancestorStations(this.ends, this.byId, this.tk);

    const { roots, kids } = routeBranches(d, this.tk, keep);
    this.kids = kids;

    // 通る駅はあるのに起点 (親が無いか、親が経路に入らない駅) が無いのは、親子関係が循環しているとき。線を引けないので、そう伝える
    if (!roots.length)
      return {
        stations: 0,
        nodes: [
          el(
            "p",
            { class: "err" },
            `この ${term("entry")} の ${term("frame")} の親子関係が循環していて、${term("call_path")} を引けない。「${term("call_tree")}」のタブで、循環している ${term("frame")} を確かめる`,
          ),
        ],
      };

    this.xferSlots = new Map();

    const out = el(
      "div",
      { class: `route ${lineOf(entryPath)}` },
      roots.map((id) => this.line(id, true)),
    );

    markTransfers(entryPath, this.xferSlots);

    // 終点の要約 (経路の上に置く): どの操作を、どの場所 (根拠の file:line) で行うか。経路を下まで読まなくても根拠の場所が分かる
    const { all, grouped } = groupEndpoints(this.ends);

    const summary = endpointSummary(this.target, all, grouped);

    return {
      stations: keep.size,
      nodes: [
        summary,
        out,
        el(
          "ul",
          { class: `route-keys ${lineOf(entryPath)}` },
          el("li", null, el("i"), term("hop")),
          el(
            "li",
            null,
            el("i", { class: "x" }),
            `ほかの ${term("entry")} も通る ${term("shared_frame")}`,
          ),
          el("li", null, el("i", { class: "end" }), term("target")),
        ),
      ].filter(Boolean),
    };
  }
  // 部品の名前 → 乗換の注記を入れる場所 (後から共有処理の表を引いて埋める)
  station(id, isRoot) {
    const r = this.byId.get(id);
    const full = fmt(r[this.tk.label]);
    const isEnd = this.target.kind === "frame" && this.ends.has(id);
    const src = this.tk.source && r[this.tk.source] ? String(r[this.tk.source]) : "";
    // 名前の末尾の括弧が定義場所と同じファイルなら落とす (すぐ下に場所を出すので重複する)。乗換駅の判定は元の名前で引く
    const { name, slot } = stationSlot(full, src, isRoot, this.xferSlots);
    const li = el(
      "li",
      { class: `st${isEnd ? " end" : ""}` },
      el("i", { class: "dot" }),
      el(
        "div",
        { class: "body" },
        el("span", { class: "name", title: full }, name),
        this.tk.tag && r[this.tk.tag] ? el("span", { class: "tag" }, r[this.tk.tag]) : null,
        src ? el("span", { class: "src" }, src, copyButton(src)) : null,
        slot,
        this.tk.detail && r[this.tk.detail]
          ? el(
              "details",
              { class: "det" },
              el("summary", null, term("summary")),
              el("p", null, r[this.tk.detail]),
            )
          : null,
      ),
    );
    slot.li = li;
    return li;
  }

  terminal(items) {
    return el(
      "li",
      { class: `st end${items.some((x) => x.unknown) ? " miss" : ""}` },
      el("i", { class: "dot" }),
      el(
        "div",
        { class: "body" },
        items.map((x) =>
          el(
            "div",
            { class: "term" },
            x.op ? el("span", { class: `op${x.write ? " w" : ""}` }, x.op) : null,
            el("span", { class: "res" }, resLink(x.to)),
            x.unknown ? el("span", { class: "tag dash" }, term("unknown")) : null,
            x.ev ? el("span", { class: "ev" }, x.ev, copyButton(x.ev)) : null,
          ),
        ),
      ),
    );
  }

  // 1 本の線 (ol) に駅を並べる。行き先が 2 つ以上に分かれる駅では、枝を字下げして並べる
  line(id, isRoot, cls) {
    const ol = el("ol", { class: cls || null });
    let cur = id,
      first = isRoot;
    while (cur) {
      const li = this.station(cur, first);
      first = false;
      ol.append(li);
      const next = nextStops(this.kids, cur, this.ends);
      if (next.length === 1 && next[0].frame) {
        cur = next[0].frame;
        continue;
      }
      if (next.length === 1) {
        ol.append(this.terminal(next[0].items));
        break;
      }
      if (next.length > 1) {
        li.classList.add("fork");
        for (const n of next)
          li.append(
            n.frame
              ? this.line(n.frame, false, "branch")
              : el("ol", { class: "branch" }, this.terminal(n.items)),
          );
      }
      break;
    }
    return ol;
  }
}

function endpointCollector() {
  const ends = new Map();
  const addEnd = (id, item) => {
    if (!ends.has(id)) ends.set(id, []);
    const list = ends.get(id);
    if (!list.some((x) => x.key === item.key)) list.push(item);
  };
  return { addEnd, ends };
}

function collectDataEndpoints(d, sk, target, byId, addEnd) {
  for (const m of d.msgs) {
    const to = m[sk.to],
      id = String(m[sk.node]);
    if (!isPathLike(to) || !under(to, target.path) || !byId.has(id)) continue;
    recordDataEndpoint(sk, m, to, addEnd, id);
  }
}

function recordDataEndpoint(sk, m, to, addEnd, id) {
  const op = sk.label && m[sk.label] != null ? opLabel(to, String(m[sk.label])) : "",
    ev = sk.evidence && m[sk.evidence] ? String(m[sk.evidence]) : "";
  addEnd(id, {
    key: `${op}|${to}|${ev}`,
    op,
    to,
    ev,
    write: isWrite(to, String(m[sk.label] ?? "")),
    unknown: !!(sk.status && m[sk.status] === "unknown"),
  });
}

function collectFrameEndpoints(target, tk, d, ends) {
  const srcOk = (r) =>
    !target.sources ||
    !target.sources.size ||
    !tk.source ||
    target.sources.has(fileOf(r[tk.source]));
  for (const r of d.frames)
    if (String(r[tk.label]) === target.name && srcOk(r)) ends.set(String(r[tk.id]), []);
}

function ancestorStations(ends, byId, tk) {
  const keep = new Set();
  for (const id of ends.keys()) {
    let cur = id;
    while (cur && byId.has(cur) && !keep.has(cur)) {
      keep.add(cur);
      const p = byId.get(cur)[tk.parent];
      cur = p == null || p === "" ? null : String(p);
    }
  }
  return keep;
}

function routeBranches(d, tk, keep) {
  const kids = new Map();
  const roots = [];
  for (const r of d.frames) {
    // frames の並び (callstack の順) を保つ
    const id = String(r[tk.id]);
    if (!keep.has(id)) continue;
    const p = r[tk.parent] == null || r[tk.parent] === "" ? null : String(r[tk.parent]);
    if (p && keep.has(p)) {
      if (!kids.has(p)) kids.set(p, []);
      kids.get(p).push(id);
    } else roots.push(id);
  }
  return { roots, kids };
}

function stationSlot(full, src, isRoot, xferSlots) {
  const paren = /^(.*?\S) \((.+)\)$/.exec(full);
  const name = paren && src.startsWith(paren[2]) ? paren[1] : full;
  const slot = el("span");
  slot.file = fileOf(src);
  if (!isRoot) {
    if (!xferSlots.has(full)) xferSlots.set(full, []);
    xferSlots.get(full).push(slot);
  }
  return { name, slot };
}

function nextStops(kids, cur, ends) {
  return [
    ...(kids.get(cur) || []).map((k) => ({ frame: k })),
    ...((ends.get(cur) || []).length ? [{ items: ends.get(cur) }] : []),
  ];
}

function groupEndpoints(ends) {
  const all = [...ends.values()].flat();
  // 同じ操作・同じ根拠の箇所は 1 行にまとめ、数を添える
  const grouped = [];
  for (const x of all) {
    const hit = grouped.find((g) => g.op === x.op && g.ev === x.ev && g.unknown === x.unknown);
    if (hit) hit.n += 1;
    else grouped.push({ ...x, n: 1 });
  }
  return { all, grouped };
}

function endpointRow(x) {
  return el(
    "li",
    null,
    x.op ? el("span", { class: `op${x.write ? " w" : ""}` }, x.op) : el("span"),
    el(
      "span",
      { class: "ev", title: x.ev || null },
      x.unknown ? el("span", { class: "tag dash" }, term("unknown")) : null,
      x.ev || `${term("evidence")} の記録が無い`,
      x.n > 1 ? el("span", { class: "muted" }, ` (同じ場所で ${x.n} 回)`) : null,
    ),
    x.ev ? copyButton(x.ev) : el("span"),
  );
}

function endpointSummary(target, all, grouped) {
  const TOP = 4; // 先頭に出す数。残りは押して開く (経路の線を最初の画面に入れるため)
  const summary =
    target.kind === "data" && all.length
      ? el(
          "div",
          { class: "ends" },
          el("h3", null, `${term("data_access")} と ${term("evidence")} (${all.length})`),
          el("ul", null, grouped.slice(0, TOP).map(endpointRow)),
          grouped.length > TOP
            ? el(
                "details",
                null,
                el("summary", null, `ほか ${grouped.length - TOP} 行`),
                el("ul", null, grouped.slice(TOP).map(endpointRow)),
              )
            : null,
        )
      : null;
  return summary;
}

// まだ分析していない入口: 線が引かれていないことを、破線の路線で示す
export function pendingRoute(entryPath) {
  return el(
    "div",
    { class: `route pending ${lineOf(entryPath)}` },
    el(
      "ol",
      null,
      el(
        "li",
        { class: "st" },
        el("i", { class: "dot" }),
        el("div", { class: "body" }, el("span", { class: "name" }, entryPath)),
      ),
      el(
        "li",
        { class: "st end" },
        el("i", { class: "dot" }),
        el(
          "div",
          { class: "body" },
          el(
            "span",
            { class: "muted" },
            `ここから先は、まだ引かれていない。この ${term("entry")} を分析すると、${term("hop")} と ${term("target")} が入る`,
          ),
        ),
      ),
    ),
  );
}

// 共有処理の表に載っている部品 (ほかの入口からも呼ばれる) を乗換駅にする
function markTransfers(entryPath, slots) {
  const m = model.frameMart;
  if (!m || !m.keys.id) return;
  const jobs = groupTransferSlots(slots, m);
  for (const { name, file, list } of jobs.values()) {
    rows(m, { [m.keys.id]: name, ...(file ? { [m.keys.source]: file } : {}) }, 200)
      .then((d) => {
        for (const slot of list) {
          // 同じ名前で定義場所の違う処理は別の行。表が定義場所の列 (keys.source) を持つなら、この駅の定義場所と合う行だけを見る
          const others = otherEntries(d, m, entryPath);
          if (!others.size) continue;
          slot.li.classList.add("x");
          slot.replaceChildren(
            el(
              "a",
              {
                class: "xfer",
                href: hSubject("#/frames", m.name, name),
                title: [...others].sort().join("\n"),
              },
              `ほか ${others.size} 件の ${term("entry")} もここを通る`,
            ),
          );
        }
      })
      .catch(() => {
        for (const slot of list)
          slot.replaceChildren(
            el("span", { class: "xfer muted" }, `ほかの ${term("entry")} も通るかは、読めなかった`),
          );
      });
  }
}

function groupTransferSlots(slots, m) {
  const jobs = new Map(); // 名前 + 定義場所 → その駅たち (同じ問い合わせは 1 回)
  for (const [name, list] of slots)
    for (const slot of list) {
      const file = m.keys.source ? slot.file : "";
      const key = name + "\n" + file;
      if (!jobs.has(key)) jobs.set(key, { name, file, list: [] });
      jobs.get(key).list.push(slot);
    }
  return jobs;
}

function otherEntries(d, m, entryPath) {
  const others = new Set();
  for (const r of d.rows) {
    const members = String(r[m.keys.members] || "").split(", ");
    if (members.includes(entryPath))
      for (const p of members) if (p && p !== entryPath) others.add(p);
  }
  return others;
}
