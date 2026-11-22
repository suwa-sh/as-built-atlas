"""MCP サーバ (API の薄いラッパー)。

mart の名前や SQL を知らない。すべて集計表 API に問い合わせる。
ツール: list_marts / describe_mart / query_mart / recompute / describe_atlas

2 つの出し方:
  - `abatlas serve` が API と同じプロセスで streamable HTTP (`/mcp`) として出す (既定。コンテナの api サービス)
  - `abatlas mcp --api <url>` が stdio で出す (API は別プロセス)
"""

from __future__ import annotations

from typing import Any

import httpx


class ApiClient:
    """API を呼ぶだけ。同一プロセスなら ASGITransport、別プロセスなら base_url で HTTP。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        client: httpx.AsyncClient | None = None,
    ):
        self.client = client or httpx.AsyncClient(base_url=base_url, timeout=600)

    @staticmethod
    def _json(r: httpx.Response) -> Any:
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:
                detail = r.text
            return {"error": detail, "status": r.status_code}
        return r.json()

    async def list_marts(self) -> Any:
        return self._json(await self.client.get("/marts"))

    async def describe_mart(self, name: str) -> Any:
        return self._json(await self.client.get(f"/marts/{name}"))

    async def query_mart(
        self,
        name: str,
        filters: dict[str, str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Any:
        params = {**(filters or {}), "limit": limit, "offset": offset}
        return self._json(await self.client.get(f"/marts/{name}/rows", params=params))

    async def group_mart(
        self,
        name: str,
        by: str,
        member: str | None = None,
        flag: str | None = None,
        chip: str | None = None,
        filters: dict[str, str] | None = None,
        q: str | None = None,
        order: str = "-members",
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        params = {
            **(filters or {}),
            "by": by,
            "order": order,
            "limit": limit,
            "offset": offset,
        }
        params.update(
            {
                k: v
                for k, v in (
                    ("member", member),
                    ("flag", flag),
                    ("chip", chip),
                    ("q", q),
                )
                if v
            }
        )
        return self._json(await self.client.get(f"/marts/{name}/groups", params=params))

    async def recompute(self) -> Any:
        return self._json(await self.client.post("/recompute"))

    async def meta(self) -> Any:
        return self._json(await self.client.get("/meta"))


def in_process_client(api_app) -> ApiClient:
    """同じプロセスの FastAPI に ASGI で直接つなぐ (ポートを経由しない。Host はループバック名にして recompute の検査を通す)。"""
    return ApiClient(
        client=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app),
            base_url="http://127.0.0.1",
            timeout=600,
        )
    )


def build_server(api: ApiClient):
    try:  # mcp 2.x (MCPServer) / 1.x (FastMCP) の両方で動く
        from mcp.server.mcpserver import MCPServer as _Server
    except ModuleNotFoundError:
        from mcp.server.fastmcp import FastMCP as _Server

    mcp = _Server(
        "as-built-atlas",
        instructions=(
            "対象システムの竣工図 (as-built) の集計表を読む。まず list_marts で何があるかを見て、"
            "describe_mart で列と宣言 (view の種類・階層・キー) を確かめ、query_mart で絞り込んで読む。行が多い表は、group_mart で、物ごとの数に先にまとめる。"
            "主張には fact / interpretation / unknown の区別があり、unknown は理由が付く。"
        ),
    )

    @mcp.tool()
    async def list_marts() -> Any:
        """集計表 (mart) の一覧。名前・説明・宣言 (origin / view / level / keys)・列を返す。"""
        return await api.list_marts()

    @mcp.tool()
    async def describe_mart(name: str) -> Any:
        """mart 1 つの説明。宣言・列・件数。"""
        return await api.describe_mart(name)

    @mcp.tool()
    async def query_mart(
        name: str,
        filters: dict[str, str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Any:
        """mart の行を読む。filters は {列名: 値} の等値絞り込み。limit は最大 10000。"""
        return await api.query_mart(name, filters, limit, offset)

    @mcp.tool()
    async def group_mart(
        name: str,
        by: str,
        member: str | None = None,
        flag: str | None = None,
        chip: str | None = None,
        filters: dict[str, str] | None = None,
        q: str | None = None,
        order: str = "-members",
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        """mart の行を、列 by の値ごとにまとめる (1 つの物 = 1 件)。同じ物が、入口の数だけ行になっている表を、物の一覧として読む。
        members = 列 member の相異なる数 (ふつうは入口のパスの列。無ければ行の数)、flagged = そのうち真偽の列 flag が真のもの、chips = 列 chip の相異なる値。
        宣言に rollup があれば、その by / member / flag / chip を使うとよい。q は by の値の部分一致。order は -members / members / key。"""
        return await api.group_mart(
            name, by, member, flag, chip, filters, q, order, limit, offset
        )

    @mcp.tool()
    async def recompute() -> Any:
        """分析結果 YAML から集計表を作り直す (ETL → dbt build)。数分かかることがある。"""
        return await api.recompute()

    @mcp.tool()
    async def describe_atlas() -> Any:
        """この竣工図の前提: プロファイル (id / 入口の階層の概念名) と、データの種類ごとの段・操作 (1 文字の意味)。表の値を読む前に 1 回見る。"""
        return await api.meta()

    return mcp


def run(api_url: str) -> None:
    """stdio の MCP。API は別プロセス (`abatlas serve` か compose の api サービス)。"""
    build_server(ApiClient(api_url)).run(transport="stdio")
