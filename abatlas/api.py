"""集計表 (mart) を読む汎用 API。

宣言は build が DuckDB の中に書いた表 (meta.declarations。dbt manifest の model `meta.abatlas` を検査したもの) から読む。
データは DuckDB (`analysis/data/abatlas.duckdb`、`abatlas build` の派生物) から読む。コードは mart の名前を知らない (宣言駆動)。
`abatlas serve` は同じプロセスで MCP (streamable HTTP、`/mcp`) も出す。

  GET  /health
  GET  /marts                    一覧 (名前・説明・宣言・列)
  GET  /marts/{name}             説明 (宣言・列・件数)
  GET  /marts/{name}/rows        問い合わせ。?limit=&offset=& それ以外のクエリは「列 = 値」の絞り込み。
                                 `列__prefix=値` は前方一致、`列__contains=値` は部分一致 (大小文字を区別しない)、
                                 `列__under=パス` は「そのパス自身か、その下 (パス + '/' で始まる)」(階層の畳み込み用)、
                                 `列__min=数` / `列__max=数` は数値の範囲。`order=列` (先頭 - で降順) で並べ替え
  GET  /marts/{name}/tree        階層パスの列の、ある節の直下の子 (名前・配下の葉の数・行数・不明の有無)。?col=&under=&flag=&distinct=& + 絞り込み
  POST /marts/{name}/pivot       行の節 × 列の節 で畳んだ値 (操作の 1 文字は和集合、数値は和)。本文 JSON: row / col / value / flag / row_keys / col_keys / filters
  GET  /meta                     プロファイル (入口の階層の概念名) とデータの種類の語彙 (段・操作)
  POST /recompute                ETL → dbt build をやり直す (直列。同時実行は 409)
  GET  /                         webapp (静的ファイル。宣言から画面を組む。上の API だけを読む)
"""

from __future__ import annotations

import logging
from decimal import Decimal
import os
import threading
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any

import duckdb
from fastapi import Body, FastAPI, HTTPException, Query, Request

from . import duckdb_path
from .build import build_repo
from .declarations import read_declarations, read_meta

WEBAPP_DIR = Path(__file__).resolve().parent / "webapp"


def _q(ident: str) -> str:
    """DuckDB の識別子引用 (二重引用符で囲み、中の二重引用符は 2 つにする)。manifest 由来の名前もこれを通す。"""
    return '"' + str(ident).replace('"', '""') + '"'


def _rel(rel: dict) -> str:
    return f"{_q(rel['schema'])}.{_q(rel['alias'])}"


def _escape_like(v: str) -> str:
    return v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _where(
    mart: str, names: set[str], filters: dict[str, str]
) -> tuple[list[str], list]:
    """クエリ文字列の絞り込みを SQL の条件にする。列は実在するものだけ (名前は引用して埋め、値は常にバインド)。"""
    where, params = [], []
    for k, v in filters.items():
        col, sep, op = k.rpartition("__")
        if not sep or op not in {"prefix", "under", "contains", "min", "max", "empty"}:
            col, op = k, "eq"
        if col not in names:
            raise HTTPException(400, f"列 {col} は mart {mart} に無い")
        _append_filter(where, params, col, op, k, v)
    return where, params


def _append_filter(where, params, col, op, k, v):
    c = f"cast({_q(col)} as varchar)"
    if op in ("min", "max"):  # 数値の範囲 (以上 / 以下)
        try:
            num = float(v)
        except ValueError:
            raise HTTPException(400, f"{k} は数値で指定する")
        where.append(f"try_cast({_q(col)} as double) {'>=' if op == 'min' else '<='} ?")
        params.append(num)
    elif op == "empty":  # 値が無い行 (null か、空の文字)。値は見ない
        where.append(f"({_q(col)} is null or {c} = '')")
    elif op == "prefix":
        where.append(f"starts_with({c}, ?)")
        params.append(v)
    elif op == "contains":  # 部分一致 (大小文字を区別しない。% _ \ は文字として扱う)
        where.append(f"{c} ilike ? escape '\\'")
        params.append("%" + _escape_like(v) + "%")
    elif op == "under":  # そのパス自身か、その下
        if v == "/":
            return
        where.append(f"({c} = ? or starts_with({c}, ?))")
        params.extend([v, v.rstrip("/") + "/"])
    else:
        where.append(f"{_q(col)} = ?")
        params.append(v)


def _under_expr(col_sql: str) -> str:
    """「節の自身か配下」の条件 (節が '/' なら全部)。節はバインドする (2 回)。"""
    return f"(? = '/' or {col_sql} = ? or starts_with({col_sql}, ? || '/'))"


def _fold_letters(values, letters):
    seen = dict.fromkeys("".join(values))
    ordered = [ch for ch in letters if ch in seen]
    ordered.extend(ch for ch in seen if ch not in letters)
    return "".join(ordered)


def _numeric_value(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _operation_string(value):
    return isinstance(value, str) and value.isalpha() and value.isupper()


def _fold(values: list, letters: str | None):
    """畳んだ節の値。操作の 1 文字だけの文字列は和集合 (letters の並び順。無ければ出現順)、数値は和、それ以外は値を並べる。"""
    vs = [v for v in values if v is not None and v != ""]
    if not vs:
        return None
    if all(_operation_string(v) for v in vs):
        return _fold_letters(vs, letters or "")
    if all(_numeric_value(v) for v in vs):
        total = sum(vs)
        return (
            float(total) if isinstance(total, Decimal) else total
        )  # JSON にそのまま出せる形に
    return ", ".join(sorted({str(v) for v in vs}))


class MartCatalog:
    """DuckDB から mart の宣言と列を引く (宣言も表も同じファイルにある)。"""

    def __init__(self, repo: Path):
        self.repo = repo
        self.db = duckdb_path(repo)

    def declarations(
        self, con: duckdb.DuckDBPyConnection | None = None
    ) -> dict[str, dict[str, Any]]:
        if con is not None:
            return read_declarations(con)
        with self.connect() as c:
            return read_declarations(c)

    def connect(self) -> duckdb.DuckDBPyConnection:
        if not self.db.exists():
            raise HTTPException(503, f"DuckDB が無い ({self.db})。先に build する")
        return duckdb.connect(str(self.db), read_only=True)

    def columns(self, con: duckdb.DuckDBPyConnection, rel: dict) -> list[dict]:
        rows = con.execute(
            "select column_name, data_type from information_schema.columns where table_schema = ? and table_name = ? order by ordinal_position",
            [rel["schema"], rel["alias"]],
        ).fetchall()
        return [{"name": c, "type": t} for c, t in rows]


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _allowed_hosts() -> set[str]:
    """許可する Host 名。既定はループバックだけ (DNS rebinding 対策)。別名で出すときは ABATLAS_ALLOWED_HOSTS にカンマ区切りで足す。"""
    extra = {
        h.strip().lower()
        for h in os.environ.get("ABATLAS_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    return _LOCAL_HOSTS | extra


def _host_of(raw_host: str) -> str:
    return (urlsplit("//" + raw_host).hostname or "").lower()


class SecurityHeadersMiddleware:
    """webapp (と API) の応答に保護ヘッダを付ける。webapp は自己完結 (外部の script / style / font を読まない) なので self だけ許す。"""

    CSP = b"default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"content-security-policy", self.CSP),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-cache"),
                ]  # upgrade で webapp のファイルが変わる。毎回サーバに再検証させる (ETag で 304)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class LoopbackHostMiddleware:
    """読む経路も含めて、Host がループバック名 (または許可した名前) でない要求を 403 で拒む。MCP 側 (SDK の既定) と同じ基準。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            raw = next(
                (
                    v.decode("latin-1")
                    for k, v in scope.get("headers", [])
                    if k == b"host"
                ),
                "",
            )
            if _host_of(raw) not in _allowed_hosts():
                from starlette.responses import JSONResponse

                await JSONResponse(
                    {"detail": "Host が許可されていない"}, status_code=403
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _reject_cross_site(request: Request) -> None:
    """状態を変える要求 (再集計) をブラウザ経由の別サイトから叩かれないようにする。

    - Host が許可した名前でなければ拒む (読む経路の LoopbackHostMiddleware と同じ検査。二重でもよい)
    - Origin があり、Host と一致しなければ拒む (CSRF 対策。同一オリジンの webapp と curl / MCP は通る)
    """
    raw_host = request.headers.get("host") or ""
    host = _host_of(raw_host)
    if host not in _allowed_hosts():
        raise HTTPException(403, "Host が許可されていない")
    origin = request.headers.get("origin")
    if origin:
        o = urlsplit(origin)
        if (o.hostname or "").lower() != host or o.port != urlsplit(
            "//" + raw_host
        ).port:
            raise HTTPException(403, "Origin が許可されていない")


def _validate_columns(mart, available, columns):
    for col in columns:
        if col is not None and col not in available:
            raise HTTPException(400, f"列 {col} は mart {mart} に無い")


def _where_sql(conditions):
    return " where " + " and ".join(conditions) if conditions else ""


def _pivot_keys(body):
    row_keys = body.get("row_keys") or ["/"]
    col_keys = body.get("col_keys") or ["/"]
    if not (
        isinstance(row_keys, list)
        and isinstance(col_keys, list)
        and all(isinstance(k, str) for k in row_keys + col_keys)
    ):
        raise HTTPException(400, "row_keys / col_keys は文字列の並び")
    if len(row_keys) > 2000 or len(col_keys) > 2000:
        raise HTTPException(400, "節は 2000 個まで")
    return row_keys, col_keys


def _operation_letters(con, d, filters):
    # 操作の文字の並び順: 絞り込みにデータの種類 (keys.kind の列) があれば、その種類の語彙から
    kind_col = (d["declaration"].get("keys") or {}).get("kind")
    if kind_col and kind_col in filters:
        kinds = read_meta(con).get("resource_kinds") or {}
        return "".join(
            o["letter"] for o in kinds.get(filters[kind_col], {}).get("ops", [])
        )
    return None


def _group_records(rows):
    out = []
    for r in rows:
        chips = sorted(r[4] or [])
        out.append(
            {
                "key": r[0],
                "members": r[1],
                "flagged": r[2],
                "rows": r[3],
                "chips": chips[:12],
                "chips_more": max(0, len(chips) - 12),
            }
        )
    return out


class MartEndpoints:
    def __init__(self, repo):
        self.repo = repo.resolve()
        self.catalog = MartCatalog(self.repo)
        self.lock = threading.Lock()

    def _mart(self, name: str, con: duckdb.DuckDBPyConnection) -> dict:
        decls = self.catalog.declarations(con)
        if name not in decls:
            raise HTTPException(404, f"mart {name} は宣言されていない")
        return decls[name]

    def health(self):
        return {
            "ok": True,
            "repo": str(self.repo),
            "duckdb": str(self.catalog.db),
            "duckdb_exists": self.catalog.db.exists(),
        }

    def list_marts(self):
        with (
            self.catalog.connect() as con
        ):  # 1 接続 = 1 版 (置き換え中でも宣言と表は同じ版)
            decls = self.catalog.declarations(con)
            return [
                {**d, "columns": self.catalog.columns(con, d["relation"])}
                for d in decls.values()
            ]

    def describe_mart(self, name: str):
        with self.catalog.connect() as con:
            d = self._mart(name, con)
            cols = self.catalog.columns(con, d["relation"])
            total = con.execute(
                f"select count(*) from {_rel(d['relation'])}"  # nosec B608 - identifiers quoted, filter values bound
            ).fetchone()[0]
        return {**d, "columns": cols, "total": total}

    def query_mart(
        self,
        name: str,
        request: Request,
        limit: int = Query(200, ge=1, le=10000),
        offset: int = Query(0, ge=0),
        order: str | None = None,
    ):
        """order は並べ替えの列 (先頭に - で降順。宣言に無い列は 400)。無ければ mart の順。"""
        filters = {
            k: v
            for k, v in request.query_params.multi_items()
            if k not in ("limit", "offset", "order")
        }
        with self.catalog.connect() as con:
            d = self._mart(name, con)
            rel = d["relation"]
            cols = self.catalog.columns(con, rel)
            names = {c["name"] for c in cols}
            where, params = _where(name, names, filters)
            sql = f"select * from {_rel(rel)}"  # nosec B608 - identifiers quoted, filter values bound
            sql += _where_sql(where)
            total = con.execute(f"select count(*) from ({sql}) t", params).fetchone()[0]  # nosec B608 - identifiers quoted, filter values bound
            order_sql = ""
            if order:
                desc = order.startswith("-")
                ocol = order[1:] if desc else order
                if ocol not in names:
                    raise HTTPException(400, f"列 {ocol} は mart {name} に無い")
                order_sql = (
                    f" order by {_q(ocol)} {'desc' if desc else 'asc'} nulls last"
                )
            cur = con.execute(
                sql + order_sql + f" limit {int(limit)} offset {int(offset)}", params
            )
            out_cols = [c[0] for c in cur.description]
            rows = [dict(zip(out_cols, r)) for r in cur.fetchall()]
        return {
            "name": name,
            "declaration": d["declaration"],
            "columns": out_cols,
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def meta(self):
        """プロファイル (id / version / label / hierarchy / layers = 層の並び) とデータの種類の語彙 (段・操作の 1 文字・向き)、用語集、分析対象。build が DuckDB に書いたもの。
        missing_terms は、今の配布物の用語集にあって、この集計表に無い id (あれば、集計し直す)。"""
        with self.catalog.connect() as con:
            out = read_meta(con)
        # 配布物の用語集にあって、この集計表に入っていない id (配布物を新しくして、集計し直していない)。画面は、あれば作り直しを促す
        from .schemas import term_labels

        have = out.get("terms") if isinstance(out.get("terms"), dict) else {}
        missing = sorted(k for k in term_labels() if k not in have)
        if missing:
            out["missing_terms"] = missing
        return out

    def tree(
        self,
        name: str,
        request: Request,
        col: str,
        under: str = "/",
        flag: str | None = None,
        distinct: str | None = None,
    ):
        """階層パスの列 `col` の、節 `under` の直下の子。子ごとに 葉の数 (配下の相異なるパス)・行数・自身が葉か・不明の有無・distinct 列の相異なる数。"""
        filters = {
            k: v
            for k, v in request.query_params.multi_items()
            if k not in ("col", "under", "flag", "distinct")
        }
        with self.catalog.connect() as con:
            d = self._mart(name, con)
            rel = d["relation"]
            names = {c["name"] for c in self.catalog.columns(con, rel)}
            _validate_columns(name, names, (col, flag, distinct))
            where, params = _where(name, names, filters)
            under = "/" if not under or under == "/" else "/" + under.strip("/")
            depth = 0 if under == "/" else len(under.strip("/").split("/"))
            c = f"cast({_q(col)} as varchar)"
            seg = f"string_split({c}, '/')[{depth + 2}]"  # 先頭が '/' なので parts[1] は空。depth 段目の次が子の名前
            cond = [_under_expr(c), f"{seg} is not null", f"{seg} <> ''"] + where
            sql = f"""select {seg} as child,
                count(distinct {c}) as leaves, count(*) as "rows", bool_and(len(string_split({c}, '/')) = {depth + 2}) as is_leaf,
                {("bool_or(" + _q(flag) + ")") if flag else "false"} as has_flag,
                {("count(distinct " + _q(distinct) + ")") if distinct else "null"} as distinct_count
                from {_rel(rel)} where {" and ".join(cond)} group by child order by child"""  # nosec B608 - identifiers quoted, filter values bound
            rows = con.execute(sql, [under, under, under, *params]).fetchall()
        prefix = "" if under == "/" else under
        return {
            "name": name,
            "col": col,
            "under": under,
            "children": [
                {
                    "name": r[0],
                    "key": f"{prefix}/{r[0]}",
                    "leaves": r[1],
                    "rows": r[2],
                    "is_leaf": bool(r[3]),
                    "has_flag": bool(r[4]),
                    "distinct": r[5],
                }
                for r in rows
            ],
        }

    def groups(
        self,
        name: str,
        request: Request,
        by: str,
        member: str | None = None,
        flag: str | None = None,
        chip: str | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        order: str = "-members",
    ):
        """列 `by` の値ごとに、行をまとめる (1 つの物 = 1 件)。「同じ物が、入口の数だけ行になっている表」を、物の一覧として読むためのもの。

        件ごとに: members = 列 `member` の相異なる数 (無ければ行の数)、flagged = そのうち真偽の列 `flag` が真のもの、rows = 行の数、
        chips = 列 `chip` の相異なる値 (12 個まで。それより多いときは chips_more に残りの数)。
        q は `by` の値の部分一致。order は -members (多い順。既定) / members (少ない順) / key (名前の順)。ほかのクエリは、rows と同じ絞り込み。
        total は件の数、member_total は絞り込みの中の `member` の相異なる数 (棒の長さの基準)。
        """
        reserved = ("by", "member", "flag", "chip", "q", "limit", "offset", "order")
        filters = {
            k: v for k, v in request.query_params.multi_items() if k not in reserved
        }
        orders = {
            "-members": "2 desc, 1",
            "members": "2, 1",
            "key": "1",
        }  # 位置で指定する (元の表に key や members という列があっても、取り違えない)
        if order not in orders:
            raise HTTPException(400, f"order は {sorted(orders)} のどれか")
        with self.catalog.connect() as con:
            d = self._mart(name, con)
            rel = d["relation"]
            cols = {c["name"]: c["type"] for c in self.catalog.columns(con, rel)}
            _validate_columns(name, cols, (by, member, flag, chip))
            if flag is not None and cols[flag].upper() != "BOOLEAN":
                raise HTTPException(
                    400, f"flag の列 {flag} は真偽の列でなければならない"
                )
            where, params = _where(name, set(cols), filters)
            base = f"from {_rel(rel)}" + _where_sql(where)
            key = f"coalesce(cast({_q(by)} as varchar), '')"
            count = f"count(distinct {_q(member)})" if member else "count(*)"
            member_total = con.execute(f"select {count} {base}", params).fetchone()[0]
            if q:
                base += (" and " if where else " where ") + f"{key} ilike ? escape '\\'"
                params = [*params, "%" + _escape_like(q) + "%"]
            flagged = f"{count} filter (where {_q(flag)})" if flag else "0"
            chip_sql = (
                f"list(distinct cast({_q(chip)} as varchar)) filter (where {_q(chip)} is not null and cast({_q(chip)} as varchar) <> '')"
                if chip
                else "null"
            )
            total = con.execute(
                f"select count(distinct {key}) {base}", params
            ).fetchone()[0]
            rows = con.execute(
                f"select {key} as key, {count} as members, {flagged} as flagged, count(*) as n, {chip_sql} as chips {base} "
                f"group by 1 order by {orders[order]} limit {int(limit)} offset {int(offset)}",
                params,
            ).fetchall()
        return {
            "name": name,
            "by": by,
            "member": member,
            "groups": _group_records(rows),
            "total": total,
            "member_total": member_total,
            "limit": limit,
            "offset": offset,
        }

    def pivot(self, name: str, body: dict = Body(...)):
        """行の節 × 列の節 で値を畳む。row_keys / col_keys は階層パス (節。'/' は全部)。各組で、row が節の自身か配下 かつ col が節の自身か配下 の行を集める。

        値の畳み方: 操作の 1 文字だけの文字列は和集合 (filters に keys.kind の列があれば、その種類の語彙の並び順)、数値は和、それ以外は値を並べる。
        flag は bool_or。返す cells は値のある組だけ。
        """
        row_col, col_col, val_col = body.get("row"), body.get("col"), body.get("value")
        flag_col = body.get("flag")
        filters = body.get("filters") or {}
        if not all(isinstance(x, str) for x in (row_col, col_col, val_col)):
            raise HTTPException(400, "row / col / value (列名) が要る")
        row_keys, col_keys = _pivot_keys(body)
        with self.catalog.connect() as con:
            d = self._mart(name, con)
            rel = d["relation"]
            names = {c["name"] for c in self.catalog.columns(con, rel)}
            _validate_columns(name, names, (row_col, col_col, val_col, flag_col))
            where, params = _where(name, names, filters)
            letters = _operation_letters(con, d, filters)
            rc, cc = (
                f"cast({_q(row_col)} as varchar)",
                f"cast({_q(col_col)} as varchar)",
            )
            sql = f"""with rk(key) as (select unnest(?::varchar[])), ck(key) as (select unnest(?::varchar[]))
                select rk.key, ck.key, list({_q(val_col)}), {("bool_or(" + _q(flag_col) + ")") if flag_col else "false"}, count(*)
                from {_rel(rel)} t
                join rk on (rk.key = '/' or {rc} = rk.key or starts_with({rc}, rk.key || '/'))
                join ck on (ck.key = '/' or {cc} = ck.key or starts_with({cc}, ck.key || '/'))
                {_where_sql(where)}
                group by rk.key, ck.key"""  # nosec B608 - identifiers quoted, filter values bound
            rows = con.execute(sql, [row_keys, col_keys, *params]).fetchall()
        cells = [
            {
                "row": r[0],
                "col": r[1],
                "value": _fold(list(r[2]), letters),
                "flag": bool(r[3]),
                "rows": r[4],
            }
            for r in rows
        ]
        return {"name": name, "letters": letters, "cells": cells}

    def recompute(self, request: Request):
        _reject_cross_site(request)
        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, "再集計が実行中")
        try:
            return {"ok": True, **build_repo(self.repo)}
        except SystemExit as ex:  # NOSONAR
            # CLI の終了を HTTP エラーに変換し、サーバを動かし続ける。
            # dbt の出力はサーバ側のログに残し、応答は要点だけ (パス等を外に出さない)
            logging.getLogger("abatlas.api").error("recompute failed: %s", ex.code)
            raise HTTPException(500, "再集計が失敗した (サーバのログを見る)") from ex
        finally:
            self.lock.release()


def create_app(repo: Path) -> FastAPI:
    endpoints = MartEndpoints(repo)
    app = FastAPI(title="as-built-atlas API", description=__doc__)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(LoopbackHostMiddleware)

    app.get("/health")(endpoints.health)
    app.get("/marts")(endpoints.list_marts)
    app.get("/marts/{name}")(endpoints.describe_mart)
    app.get("/marts/{name}/rows")(endpoints.query_mart)
    app.get("/meta")(endpoints.meta)
    app.get("/marts/{name}/tree")(endpoints.tree)
    app.get("/marts/{name}/groups")(endpoints.groups)
    app.post("/marts/{name}/pivot")(endpoints.pivot)
    app.post("/recompute")(endpoints.recompute)

    # webapp: 静的ファイル (宣言から画面を組む。この API だけを読む)。API の経路より後ろに置くので、/marts 等は上が勝つ
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")
    return app


def create_server(repo: Path):
    """API と MCP を 1 つの ASGI アプリにする。

    外側は MCP SDK の Starlette アプリ (`/mcp`。セッション管理の lifespan を持つ)、その下に FastAPI を Mount する。
    MCP の DNS rebinding 対策 (Host / Origin の許可) は API 側と同じ集合 (_allowed_hosts) から、ポート有無の両方で作る。
    """
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.routing import Mount

    from .mcp_server import build_server, in_process_client

    api = create_app(repo)
    mcp = build_server(in_process_client(api))
    hosts = ["[::1]" if h == "::1" else h for h in sorted(_allowed_hosts())]
    # SDK の照合は `host:*` がポート付きだけに一致するので、ポート無し (既定ポートやリバースプロキシ経由) も並べる
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[x for h in hosts for x in (h, f"{h}:*")],
        allowed_origins=[
            x
            for h in hosts
            for x in (f"http://{h}", f"http://{h}:*", f"https://{h}", f"https://{h}:*")
        ],
    )
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp", transport_security=security
    )
    app.router.routes.append(
        Mount("/", app=api)
    )  # /mcp より後ろに置く (順に照合される)
    return app


def serve(repo: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_server(repo), host=host, port=port)
