// 汎用部品: パンくず

import { el } from "../lib/dom.js";
import { segs, joinPath } from "../lib/path.js";

export function crumbs(items) {
  const out = el("div", { class: "crumbs" });
  items.forEach((it, i) => {
    if (i) out.append(el("span", { class: "sep" }, "›"));
    out.append(it.href ? el("a", { href: it.href }, it.text) : el("span", { class: "here" }, it.text));
  });
  return out;
}
export function pathCrumbs(path, hashFor, rootText, rootHash) {
  const parts = segs(path);
  return crumbs([{ text: rootText, href: rootHash }, ...parts.map((p, i) => ({ text: p, href: i < parts.length - 1 ? hashFor(joinPath(parts.slice(0, i + 1))) : null }))]);
}
