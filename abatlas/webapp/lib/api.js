// 道具: 集計表 API の呼び方 (MCP と同じ API)。API の呼び方を変えるときはここだけ

import { enc } from "./hash.js";

export const PAGE = 50;
export const BIG = 10000;
const treeCache = new Map();

export async function api(path, params) {
  const u = new URL(path, location.href);
  for (const [k, v] of Object.entries(params || {}))
    if (v != null && v !== "") u.searchParams.set(k, v);
  const r = await fetch(u, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${await detailOf(r)}`);
  return r.json();
}
export async function post(path, body) {
  const r = await fetch(new URL(path, location.href), {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await detailOf(r)}`);
  return r.json();
}
export async function detailOf(r) {
  try {
    return (await r.json()).detail || r.statusText;
  } catch (_) {
    return r.statusText;
  }
}
export const rows = (mart, params, limit) =>
  api(`marts/${enc(mart.name)}/rows`, { ...params, limit: limit || BIG });
export async function rowsAll(mart, params) {
  const first = await rows(mart, params, BIG);
  const all = [...first.rows];
  while (all.length < first.total) {
    const page = await rows(mart, { ...params, offset: all.length }, BIG);
    if (!page.rows.length) break;
    all.push(...page.rows);
  }
  return { ...first, rows: all, total: Math.max(first.total, all.length) };
}
export async function tree(mart, col, under, extra) {
  const params = { col, under: under || "/", ...(extra || {}) };
  const key = mart.name + "|" + JSON.stringify(params);
  if (!treeCache.has(key))
    treeCache.set(
      key,
      api(`marts/${enc(mart.name)}/tree`, params).then((r) => r.children),
    );
  return treeCache.get(key);
}
// 列 by の値ごとに、行をまとめる (物ごとの件数。サーバで数える)
export const groups = (mart, params) => api(`marts/${enc(mart.name)}/groups`, params);
export const pivot = (mart, body) => post(`marts/${enc(mart.name)}/pivot`, body);
export async function countOf(mart, params) {
  return (await rows(mart, params, 1)).total;
}
// 階層 (tree) のキャッシュを捨てる。カタログを読み直したとき (再計算の後) に古い階層を残さない
export function clearTreeCache() {
  treeCache.clear();
}
