// 道具: 階層パス (/a/b/c) の分解と結合

export const segs = (p) => String(p).split("/").filter(Boolean);
export const joinPath = (parts) => "/" + parts.join("/");
export const parentOf = (p) => {
  const s = segs(p);
  return s.length > 1 ? joinPath(s.slice(0, -1)) : "/";
};
