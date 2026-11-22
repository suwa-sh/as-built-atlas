// 表示の種類: シーケンス (view: sequence)

import { el, svg, fmt } from "../lib/dom.js";
import { titleOf, labelOf } from "../model/catalog.js";
import { kindOfNode, passesFilter } from "../model/kinds.js";
import { emptyMsg } from "../ui/card.js";
import { linkValue } from "../ui/link.js";
import { figureBox, arrowDefs, markerFor, wrapText } from "./figure-box.js";
import { edgeList } from "./graph.js";
import { term } from "../model/vocab.js";

const lifeClass = (p) => {
  const kind = kindOfNode(p);
  return `life${kind === "data" ? " ext" : kind === "external" ? " external" : ""}`;
}; // データは薄い墨の塗り、外部接続は薄いスレートの塗り + 枠
const GX = 190,
  BW = 170,
  BH = 40,
  TOP = 8,
  HEAD_H = TOP + BH + 6,
  GY = 34,
  PAD = 16,
  MSG0 = 20;

export function sequence(m, data) {
  const k = m.keys;
  if (!data.rows.length) return emptyMsg("行が無い");
  const groups = new Map();
  for (const r of data.rows) {
    const g = String(r[k.group] ?? "");
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(r);
  }
  const out = el("div");
  for (const [g, list] of groups) {
    const msgs = [...list].sort((a, b) => Number(a[k.seq]) - Number(b[k.seq]));
    if (groups.size > 1) out.append(el("div", { class: "group-title" }, linkValue(g)));
    out.append(sequenceFigure(m, g, msgs, data.columns));
  }
  return out;
}
// シーケンス図 1 枚 (入れ物は figureBox)。参加者の見出しと本文を別の SVG にして見出しを固定する
export function sequenceFigure(m, g, msgs, columns) {
  const k = m.keys;
  const allParts = participants(msgs, k);
  return figureBox({
    title: `${titleOf(m)}: ${g}`,
    nouns: ["参加者", "メッセージ"],
    totals: [allParts.length, msgs.length],
    present: new Set(allParts.map(kindOfNode)),
    hasUnknown: !!k.status && msgs.some((mm) => mm[k.status] === "unknown"),
    unknownLabel: `${term("unknown")} の矢印だけ`,
    searchLabel: "参加者の名前で絞る",
    hasHead: true,
    draw(state, marker) {
      const vis = msgs.filter((mm) =>
        passesFilter(state, String(mm[k.from]), String(mm[k.to]), k.status ? mm[k.status] : null),
      );
      if (!vis.length) return null;
      const parts = participants(vis, k);
      const x = (p) => PAD + parts.indexOf(p) * GX + BW / 2;
      const width = PAD * 2 + (parts.length - 1) * GX + BW;
      const bodyH = MSG0 + vis.length * GY + 16;
      const hs = participantHead(width, m, g, parts, x);
      const bs = svg("svg", { viewBox: `0 0 ${width} ${bodyH}`, role: "img" });
      bs.append(svg("title", null, `${titleOf(m)}: ${g}`));
      bs.append(arrowDefs(marker));
      for (const p of parts)
        bs.append(
          svg(
            "g",
            { class: lifeClass(p), "data-n": p },
            svg("line", { x1: x(p), y1: 0, x2: x(p), y2: bodyH }),
          ),
        );
      drawMessages(vis, k, x, marker, columns, m, bs);
      return {
        head: hs,
        body: bs,
        w: width,
        headH: HEAD_H,
        bodyH,
        counts: [parts.length, vis.length],
        aside: edgeList(m, vis, columns, "メッセージの一覧"),
        legend: [
          ["life", term("frame")],
          ["life ext", term("datastore")],
          ["life external", term("external")],
          ["msg", `確かめた ${term("call")}・${term("data_access")}`],
          ["msg unknown", `${term("unknown")} を含む矢印 (点線)`],
        ],
      };
    },
  });
}

function participants(vis, k) {
  const parts = [];
  for (const mm of vis)
    for (const p of [mm[k.from], mm[k.to]])
      if (p != null && !parts.includes(String(p))) parts.push(String(p));
  return parts;
}

function participantHead(width, m, g, parts, x) {
  const hs = svg("svg", { viewBox: `0 0 ${width} ${HEAD_H}`, role: "img" });
  hs.append(svg("title", null, `${titleOf(m)}: ${g} の参加者`));
  for (const p of parts) {
    const g2 = svg(
      "g",
      { class: lifeClass(p), "data-n": p },
      svg("rect", { x: x(p) - BW / 2, y: TOP, width: BW, height: BH, rx: 4 }),
      svg("title", null, p),
    );
    wrapText(p, 24).forEach((ln, i) =>
      g2.append(svg("text", { x: x(p), y: TOP + 16 + i * 13, "text-anchor": "middle" }, ln)),
    );
    hs.append(g2);
  }
  return hs;
}

function drawMessages(vis, k, x, marker, columns, m, bs) {
  vis.forEach((mm, i) => {
    const from = String(mm[k.from]),
      to = String(mm[k.to]);
    const y = MSG0 + i * GY;
    const unknown = !!(k.status && mm[k.status] === "unknown");
    const g2 = svg("g", {
      class: `msg${unknown ? " unknown" : ""}`,
      "data-e": `m${i}`,
      "data-f": from,
      "data-t": to,
    }); // 識別子は描画順 (seq は一意とは限らない)
    if (from === to) {
      g2.append(
        svg("path", {
          d: `M ${x(from)} ${y - 8} h 30 v 16 h -30`,
          "marker-end": markerFor(marker, unknown),
        }),
      );
      if (k.label) g2.append(svg("text", { x: x(from) + 36, y: y + 4 }, fmt(mm[k.label])));
    } else {
      g2.append(
        svg("line", {
          x1: x(from),
          y1: y,
          x2: x(to),
          y2: y,
          "marker-end": markerFor(marker, unknown),
        }),
      );
      const toRight = x(to) > x(from);
      if (k.label)
        g2.append(
          svg(
            "text",
            {
              x: x(from) + (toRight ? 6 : -6),
              y: y - 5,
              "text-anchor": toRight ? "start" : "end",
            },
            fmt(mm[k.label]),
          ),
        );
    }
    g2.append(svg("title", null, columns.map((c) => `${labelOf(m, c)}: ${fmt(mm[c])}`).join("\n")));
    bs.append(g2);
  });
}
