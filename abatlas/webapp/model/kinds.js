// 宣言の読み方: 図の参加者 (ノード) の種類と、図の絞り込みの判定

import { isPathLike } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { model } from "./catalog.js";

export function kindOfNode(p) {
  if (!isPathLike(p)) return "frame";
  const first = segs(p)[0];
  if (first === "external_api") return "external";
  return (model.meta.resource_kinds || {})[first] ? "data" : "entry";
}
export function passesFilter(state, from, to, status) {
  if (state.unknownOnly && status !== "unknown") return false;
  const a = state.kinds.has(kindOfNode(from)), b = state.kinds.has(kindOfNode(to));
  if (state.mode === "both" ? !(a && b) : !(a || b)) return false;
  return !state.q || from.toLowerCase().includes(state.q) || to.toLowerCase().includes(state.q);
}
