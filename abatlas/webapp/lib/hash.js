// 道具: 経路 (location.hash) の組み立てと分解

import { segs } from "./path.js";

export const enc = (s) => encodeURIComponent(String(s));
export const encPath = (p) => (p && p !== "/" ? "/" + segs(p).map(enc).join("/") : "");
export const decPath = (h) => (h ? "/" + segs(h).map(decodeURIComponent).join("/") : "/");
export const hEntries = (p) => "#/entries" + encPath(p);
export const hEntry = (p) => "#/entry" + encPath(p);
export const hData = (kind, p) => "#/data/" + enc(kind) + encPath(p);
export const hAccess = (kind, rowRoot) => "#/access/" + enc(kind) + encPath(rowRoot);
export const hMart = (name, params) =>
  "#/mart/" +
  enc(name) +
  (params && Object.keys(params).length ? "?" + new URLSearchParams(params).toString() : "");
export const hSubject = (root, mart, id) => root + "/" + enc(mart) + "/" + enc(id);
