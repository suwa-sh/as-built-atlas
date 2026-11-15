// 汎用部品: 階層パスの値をリンクにする (行き先はここ 1 か所で決める)

import { el, fmt, short, isPathLike } from "../lib/dom.js";
import { segs, joinPath } from "../lib/path.js";
import { enc, hEntry, hData } from "../lib/hash.js";
import { model } from "../model/catalog.js";

// 階層パスの値をリンクに (入口のパスなら入口へ、データのパスならデータへ)
// 階層パスの値をリンクに。m と col を渡すと、宣言でパスと分かる列 (path / members / row / col / from / to / group) だけ入口へリンクする
// (外部 API のパス /api/… のような文字列を入口と取り違えない)。データのパス (/種類/…) は列によらずデータへ
export function linkValue(v, m, col) {
  if (!isPathLike(v)) return fmt(v);
  const k = m ? m.keys : null;
  const entryOk = !m || !col || [k.path, k.members, k.row, k.col, k.from, k.to, k.group].includes(col);
  const parts = v.split(", ");
  if (parts.length > 1 && parts.every(isPathLike)) return el("span", null, parts.flatMap((p, i) => [i ? ", " : null, linkOne(p, entryOk)]));
  return linkOne(v, entryOk);
}
// パスの行き先 (1 か所で決める): 外部 API → 外部接続の詳細、データの種類 → データ、それ以外 → 入口。無ければ null
export function hrefFor(p, entryOk = true) {
  const first = segs(p)[0];
  if (first === "external_api") {
    const ext = (model.subj.external || []).find((m) => m.declaration.view === "table" && m.keys.id);
    const host = segs(p)[1];
    return ext && host ? `#/external/${enc(ext.name)}/${enc(host)}` : null;
  }
  if (model.meta.resource_kinds && model.meta.resource_kinds[first]) return model.dataMart ? hData(first, joinPath(segs(p).slice(1))) : null;
  return model.entryMart && entryOk ? hEntry(p) : null;
}
export function linkOne(p, entryOk = true) {
  const href = hrefFor(p, entryOk);
  const isData = !!(model.meta.resource_kinds || {})[segs(p)[0]];
  return href ? el("a", { href, title: p }, isData ? short(p, 48) : p) : el("span", { title: p }, isData ? short(p, 48) : p);
}
