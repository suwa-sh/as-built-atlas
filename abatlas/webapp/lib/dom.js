// 道具: DOM / SVG の要素を作る小道具と、値の表示

import { segs } from "./path.js";

export function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k === "style") e.style.cssText = v; // CSP (default-src 'self') はインラインの style 属性を許さないので CSSOM で付ける
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}
const SVG_NS = "http://www.w3.org/2000/svg";
export function svg(tag, attrs, ...children) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) e.setAttribute(k, v);
  for (const c of children.flat(Infinity)) if (c != null) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
export const isPathLike = (v) => typeof v === "string" && v.startsWith("/");
export const isNum = (v) => typeof v === "number" || typeof v === "bigint";
export function fmt(v) {
  if (v == null || v === "") return "—";
  if (typeof v === "boolean") return v ? "はい" : "いいえ"; // 記号にしない (白抜きの丸は「まだ」に、塗った丸は「現在地」に読める)。値が無い「—」と、いいえを分ける
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  return String(v);
}
export function short(id, max = 34) {
  const s = String(id);
  if (s.length <= max) return s;
  const parts = segs(s);
  if (parts.length > 2) {
    const tail = parts.slice(-2).join("/");
    return "…/" + (tail.length > max - 2 ? tail.slice(-(max - 3)) : tail);
  }
  return "…" + s.slice(-(max - 1));
}
