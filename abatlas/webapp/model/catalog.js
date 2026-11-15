// 宣言の読み方: mart の宣言 (meta.abatlas) と meta (プロファイルの階層ラベル、データの種類の語彙) を読む。mart の名前は知らない

import { el } from "../lib/dom.js";
import { segs } from "../lib/path.js";
import { hMart } from "../lib/hash.js";
import { api, clearTreeCache } from "../lib/api.js";
import { term, setTerms, viewHint } from "./vocab.js";

// 読み込んだカタログと meta (共通の状態。meta.terms = 用語集は vocab.js に渡す)。書くのは loadCatalog だけ。他の層は読むだけ
export const model = {
  catalog: [],
  meta: { profile: {}, resource_kinds: {} },
  subj: {}, // subject -> marts
  entryMart: null, // 入口の表 (subject entry, view table, keys.path)
  dataMart: null, // 読み書きの表 (subject data, view matrix, keys.kind)
  graphMart: null, // データの流れ (subject entry, view graph)
  withinMart: null, // 入口を包む入口 (tags within, view table。1 行 = 包まれる入口 (keys.path) × 包む入口 (keys.members))
  treeMart: null, // 呼び出しの構造 (subject entry, view tree, keys.group)。経路の駅になる
  seqMart: null, // 処理の流れ (subject entry, view sequence, keys.node)。読み書きを、それを起こした処理 (tree の id) に結び付ける
  frameMart: null, // 共有処理 (subject frame, view table, keys.members)。乗換駅の判定に使う
  progressMart: null, // 進み具合 (subject analysis, view stat, keys.total)
  layerMart: null, // 層のつながり (view layers)。構成のページの図の線
};

export async function loadCatalog() {
  [model.catalog, model.meta] = await Promise.all([api("marts"), api("meta").catch(() => ({}))]);
  model.meta = { profile: {}, resource_kinds: {}, ...(model.meta || {}) };
  setTerms(model.meta.terms);
  model.subj = {};
  for (const m of model.catalog) {
    m.declaration = m.declaration || {};
    m.keys = m.declaration.keys || {};
    m.cols = new Set((m.columns || []).map((c) => c.name));
    m.tags = m.declaration.tags || [];
    (model.subj[m.declaration.subject || ""] = model.subj[m.declaration.subject || ""] || []).push(m);
  }
  model.entryMart = (model.subj.entry || []).find((m) => m.declaration.view === "table" && m.declaration.level === "entry" && m.keys.path && m.cols.has(m.keys.path)) || null;
  model.dataMart = (model.subj.data || []).find((m) => m.declaration.view === "matrix" && m.keys.kind) || null;
  model.graphMart = (model.subj.entry || []).find((m) => m.declaration.view === "graph" && m.keys.path) || null;
  model.withinMart = model.catalog.find((m) => m.tags.includes("within") && m.declaration.view === "table" && m.keys.path && m.cols.has(m.keys.path) && m.keys.members && m.cols.has(m.keys.members)) || null;
  model.treeMart = (model.subj.entry || []).find((m) => m.declaration.view === "tree" && m.keys.group && m.cols.has(m.keys.group)) || null;
  model.seqMart = (model.subj.entry || []).find((m) => m.declaration.view === "sequence" && m.keys.node && m.cols.has(m.keys.node)) || null;
  model.frameMart = (model.subj.frame || []).find((m) => m.declaration.view === "table" && m.keys.members && m.cols.has(m.keys.members)) || null;
  model.progressMart = (model.subj.analysis || []).find((m) => m.declaration.view === "stat" && m.keys.total && m.cols.has(m.keys.total)) || null;
  model.layerMart = model.catalog.find((m) => m.declaration.view === "layers" && m.keys.from && m.cols.has(m.keys.from) && m.keys.to && m.cols.has(m.keys.to)) || null;
  lineLabels.length = 0;
  clearTreeCache();
}

// 路線の色 (入口の種類ごとに 1 色)。種類は入口の呼び名 (entryLabel) で、色は初めて出た順に --l1〜--l6 を割り当てる。
// 並びを安定させるため、プロファイルから分かる呼び名 (末尾の段の名前 → entry_labels の順) を先に登録する
const lineLabels = [];
function seedLines() {
  if (lineLabels.length) return;
  const h = (model.meta.profile || {}).hierarchy || {};
  const last = (h.level_labels || []).slice(-1)[0];
  for (const l of [last ? last.replace(/\+$/, "") : null, ...(Array.isArray(h.entry_labels) ? h.entry_labels : []).map((x) => x && x.label)]) {
    if (l && !lineLabels.includes(String(l))) lineLabels.push(String(l));
  }
}
export function lineOf(path) {
  seedLines();
  const label = entryLabel(path, segs(path).length) || "";
  let i = lineLabels.indexOf(label);
  if (i < 0) i = lineLabels.push(label) - 1;
  return `ln${(i % 6) + 1}`;
}
export function lineLegend() {
  seedLines();
  return lineLabels.map((label, i) => ({ label, cls: `ln${(i % 6) + 1}` }));
}
// 操作の 1 文字の並び (例 "RUD") を、読む操作と書く操作に分ける。向きは語彙の direction (in = 読む)
export function splitOps(kind, letters) {
  const ops = kindOf(kind).ops || [];
  const read = [], write = [];
  for (const ch of new Set(String(letters || ""))) {
    const op = ops.find((o) => o.letter === ch);
    (op && op.direction === "in" ? read : write).push(op ? op.label : ch);
  }
  return { read, write };
}
// 操作の id (例 read) を、そのデータの種類の語彙の呼び名 (例 参照) にする。語彙に無ければそのまま
export function opLabel(resourcePath, op) {
  const hit = (kindOf(segs(resourcePath)[0]).ops || []).find((o) => o.id === op);
  return hit ? hit.label : String(op);
}
// 操作の id が書く操作か (語彙の direction が in でないもの)。語彙に無い操作は書く側に倒す (影響を小さく見せない)
export function isWrite(resourcePath, op) {
  const hit = (kindOf(segs(resourcePath)[0]).ops || []).find((o) => o.id === op);
  return !(hit && hit.direction === "in");
}
// 進み具合 (分析済み / 全体)。宣言された指標の表を足し上げる。表が無ければ null
export async function progressOf() {
  const m = model.progressMart;
  if (!m) return null;
  const d = await api(`marts/${encodeURIComponent(m.name)}/rows`, { limit: 10000 }).catch(() => null);
  if (!d) return null;
  let done = 0, total = 0;
  for (const r of d.rows) { done += Number(r[m.keys.value]) || 0; total += Number(r[m.keys.total]) || 0; }
  return { done, total, doneLabel: labelOf(m, m.keys.value), totalLabel: labelOf(m, m.keys.total) };
}

export function titleOf(m) { return m.declaration.title || m.name; }
export function hintOf(m) { return m.declaration.hint || viewHint(m.declaration.view) || ""; }
export function labelOf(m, col) { return (m.declaration.labels || {})[col] || col; }
export function showCols(m, columns) {
  const s = m.declaration.show;
  return s && s.length ? s.filter((c) => columns.includes(c)) : columns;
}
export function physLink(m, params) {
  return el("a", { class: "more", href: hMart(m.name, params), title: `${m.name} (絞り込みと API の呼び方)` }, `${term("mart")} で見る`);
}
// 入口の階層の概念名。labels の `名前+` は繰り返す段 (それより前は上から、それより後は下から当てる)
export function levelLabel(depth, isLeaf) {
  const labels = ((model.meta.profile || {}).hierarchy || {}).level_labels || [];
  if (!labels.length || depth < 1) return depth ? `${term("level")} ${depth}` : "";
  const plus = labels.findIndex((l) => l.endsWith("+"));
  if (plus < 0) return labels[depth - 1] || labels[labels.length - 1];
  const after = labels.length - plus - 1; // 繰り返しの後ろにある段の数 (プロファイルの検査で 1 つまで)
  if (isLeaf && after > 0) return labels[labels.length - 1];
  if (depth <= plus) return labels[depth - 1];
  return labels[plus].slice(0, -1);
}
// 入口の詳細のページでの、その入口の呼び名。プロファイルの hierarchy.entry_labels にパスが当たればそれ、無ければこれまでどおり、深さで決まる段の名前 (levelLabel)
export function entryLabel(path, depth) {
  const raw = ((model.meta.profile || {}).hierarchy || {}).entry_labels;
  const hit = (Array.isArray(raw) ? raw : []).find((x) => x && x.contains && x.label && String(path).includes(x.contains)); // build は profile を検査しないので、形が違っても画面を落とさない
  return hit ? String(hit.label) : levelLabel(depth, true);
}
export function levelLabelsText() {
  const labels = ((model.meta.profile || {}).hierarchy || {}).level_labels || [];
  return labels.map((l) => l.replace(/\+$/, "")).join(" › ");
}
// 段の名前の読み方の説明 (プロファイルの hierarchy.notes)。path を渡すと、contains の文字列をそのパスが含むものだけ返す
export function hierarchyNotes(path) {
  const raw = ((model.meta.profile || {}).hierarchy || {}).notes;
  const notes = Array.isArray(raw) ? raw : []; // build は profile を検査しないので、形が違っても画面を落とさない
  return notes.filter((n) => {
    if (!n || !n.text) return false;
    return path == null || !n.contains || path.includes(n.contains);
  }).map((n) => n.text);
}
export const kindsOf = () => Object.entries(model.meta.resource_kinds || {}).filter(([k]) => k !== "external_api").map(([k, v]) => ({ id: k, ...v }));
export const kindOf = (id) => (model.meta.resource_kinds || {})[id] || { label: id, levels: [], ops: [] };
// データのパス (/種類/段/段/…) の段の名前。repeat の段は何段にも広がる
// isLeaf = その節が実際のデータ (葉)。繰り返しの段 (directory など) の下では、葉だけが末尾の段 (file) の名前になる
export function dataLevelLabel(kind, idx, isLeaf) {
  const k = kindOf(kind);
  const lv = k.levels || [];
  if (idx <= 0) return term("kind");
  if (!k.repeat) return lv[Math.min(idx, lv.length) - 1] || "";
  const rIdx = lv.indexOf(k.repeat);
  if (idx <= rIdx) return lv[idx - 1];
  if (isLeaf && rIdx < lv.length - 1) return lv[lv.length - 1];
  return k.repeat;
}
export function dataLevelsText(kind) { return [term("kind"), ...(kindOf(kind).levels || [])].join(" › "); }
export const opsText = (kind) => (kindOf(kind).ops || []).map((o) => `${o.letter} ${o.label}`).join(" / ");
export const relPath = (p, root) => (root && root !== "/" && p.startsWith(root + "/")) ? p.slice(root.length + 1) : segs(p).join("/");

// 入口の画面の節に対して mart をどう絞るか (宣言の列だけ)
export function scopeFilter(m, node) {
  if (!node || node.path === "/") return {};
  const k = m.keys;
  const attach = m.declaration.attach || "any";
  const pathCols = [k.path, k.row, k.group].filter((c) => c && m.cols.has(c));
  for (const col of pathCols) {
    const lv = /^level(\d)$/.exec(col);
    if (lv) { const n = Number(lv[1]); return node.depth >= n ? { [col]: segs(node.path)[n - 1] } : {}; }
  }
  if (attach === `level${node.depth}`) {
    const col = [k.id, k.group].find((c) => c && m.cols.has(c));
    return col ? { [col]: node.name } : {};
  }
  if (pathCols.length) return node.isLeaf ? { [pathCols[0]]: node.path } : { [`${pathCols[0]}__under`]: node.path };
  return null;
}
export function attaches(m, node) {
  const a = m.declaration.attach || "any";
  if (a === "any") return true;
  if (a === "root") return node.depth === 0;
  return a === `level${node.depth}`;
}
