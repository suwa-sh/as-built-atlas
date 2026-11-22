"""api プロファイル (API だけを持つシステム) と、nested-keys 抽出器を、小さな見本で確かめる。

OpenAPI の path + method が入口になり、出典の行が、その method のキーの行になること。
"""

import json
from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.extractors.nested_keys import extract
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "api" / "profile.yaml"

# 架空の題材
OPENAPI = """openapi: 3.0.0
paths:
  /:
    get:
      operationId: getRoot
  /books:
    parameters: []
    get:
      operationId: listBooks
      tags: [books]
    post:
      operationId: createBook
  /books/{book_id}:
    get:
      summary: 1 冊を返す
  /books/book_id:
    get:
      operationId: getBookIdHelp
  /orders:
    $ref: './orders.yaml'
"""


def _target(tmp_path: Path, name: str = "openapi.yaml", text: str = OPENAPI) -> Path:
    target = tmp_path / "target"
    (target / "docs").mkdir(parents=True)
    (target / "docs" / name).write_text(text, encoding="utf-8")
    return target


def test_profile_is_valid():
    assert validate_profile(yaml.safe_load(PROFILE.read_text(encoding="utf-8"))) == []


def test_openapi_operations_become_entries(tmp_path: Path):
    target = _target(tmp_path)
    repo = tmp_path / "atlas"
    repo.mkdir()
    init_repo(repo, "api", targets="claude-code")
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    ex = {k: v for k, v in profile["extractors"][0].items() if k != "hint"}
    ex["rationale"] = "定義ファイルは docs/openapi.yaml"
    el_path = repo / "analysis" / "entry-list.yaml"
    el_path.write_text(
        yaml.safe_dump(
            {
                "format_version": 1,
                "target": {
                    "repo": "example/kotori-api",
                    "clone_path": str(target),
                    "scope": ".",
                    "commit": "0a1b2c3d4e",
                },
                "profile": {"id": "api", "version": profile["version"]},
                "extractors": [ex],
                "entries": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    enumerate_entries(el_path, PROFILE)
    el = yaml.safe_load(el_path.read_text(encoding="utf-8"))
    assert validate_entry_list(el, profile) == []
    got = {e["id"]: (e["path"], e["name"], e["source"]["line"]) for e in el["entries"]}
    assert got == {
        "root_r.get": ("/(root)/get", "getRoot", 4),
        "books.get": (
            "/books/get",
            "listBooks",
            8,
        ),  # path の下の parameters は、入口にならない
        "books.post": ("/books/post", "createBook", 11),
        "books.book__id_d.get": (
            "/books/{book_id}/get",
            "/books/{book_id} get",
            14,
        ),  # operationId が無ければ、キーをつないだ名前
        "books.book__id.get": (
            "/books/book_id/get",
            "getBookIdHelp",
            17,
        ),  # 値が入る段と、同じ名前の固定の段は、別の id
    }
    assert all(e["layer"] == "operation" for e in el["entries"])
    books = next(e for e in el["entries"] if e["id"] == "books.get")
    assert books["attributes"] == {
        "keys": ["/books", "get"],
        "operation_id": "listBooks",
        "tags": ["books"],
    }


def test_a_ref_is_reported_not_guessed(tmp_path: Path, capsys):
    """path の値が $ref だけのときは、入口にせず、読めなかった参照として知らせる。"""
    target = _target(tmp_path)
    extract(
        target,
        {
            "files": ["docs/openapi.yaml"],
            "root": "paths",
            "levels": [{"split": "/"}, {"match": "get|post"}],
            "id": {
                "replace": [
                    {"pattern": "[{}]", "with": "-"},
                    {"pattern": "[^A-Za-z0-9_-]", "with": ""},
                ]
            },
        },
        "operation",
    )
    out = capsys.readouterr()
    assert len(out.out.splitlines()) == 5
    assert (
        "読めなかった参照: docs/openapi.yaml:19: /orders: $ref ./orders.yaml" in out.err
    )


def test_json_and_a_single_level(tmp_path: Path, capsys):
    """JSON の定義も読める。段が 1 つ (AsyncAPI 3 系の operations) でも入口になる。"""
    target = _target(
        tmp_path,
        "asyncapi.json",
        json.dumps(
            {
                "operations": {
                    "order.created": {"action": "send"},
                    "stock.changed": {"action": "receive"},
                }
            },
            indent=1,
        ),
    )
    extract(
        target,
        {
            "files": ["docs/asyncapi.json"],
            "root": "operations",
            "levels": [{}],
            "attributes": {"action": "action"},
        },
        "operation",
    )
    recs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [
        (r["id"], r["path"], r["source"]["line"], r["attributes"]["action"])
        for r in recs
    ] == [
        ("ordercreated", "/order.created", 3, "send"),
        ("stockchanged", "/stock.changed", 6, "receive"),
    ]


def test_nothing_found_is_an_error(tmp_path: Path):
    target = _target(tmp_path)
    with pytest.raises(SystemExit, match="1 件も出なかった"):
        extract(
            target,
            {"files": ["docs/openapi.yaml"], "root": "channels", "levels": [{}]},
            "operation",
        )
    with pytest.raises(SystemExit, match="2 つのキーの組"):
        extract(
            target,
            {
                "files": ["docs/openapi.yaml"],
                "root": "paths",
                "levels": [{"split": "/"}, {"match": "get"}],
                "id": {"replace": [{"pattern": "[^a-z]", "with": ""}]},
            },
            "operation",
        )


def test_a_ref_at_the_root_is_reported(tmp_path: Path, capsys):
    """操作の一覧そのものが別のファイルにあるとき (root の値が $ref) も、読めなかった参照として知らせる。"""
    target = _target(tmp_path, text="openapi: 3.0.0\npaths:\n  $ref: ./paths.yaml\n")
    with pytest.raises(SystemExit, match="読めなかった参照の先"):
        extract(
            target,
            {
                "files": ["docs/openapi.yaml"],
                "root": "paths",
                "levels": [{"split": "/"}, {"match": "get"}],
            },
            "operation",
        )
    assert (
        "読めなかった参照: docs/openapi.yaml:2: paths: $ref ./paths.yaml"
        in capsys.readouterr().err
    )


# ---------------------------------------------------------------- HTTP の path でない操作 (種類の段) と、id の規則

MCP_SERVER = '''from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")


@mcp.tool()
async def query_mart(name: str, limit: int = 200) -> dict:
    """mart の行を読む。"""
    return {}


@mcp.resource("demo://x")
async def not_a_tool() -> str:
    return ""
'''


def test_mcp_tools_get_a_kind_segment_and_the_shared_id_rules(tmp_path: Path, capsys):
    """MCP のツールは、先頭に (mcp) の段を置く (HTTP の path と同じ木に入らない)。id は、定義ファイルの抽出器の規則を、そのまま写して使う。"""
    target = tmp_path / "target"
    (target / "srv").mkdir(parents=True)
    (target / "srv" / "server.py").write_text(MCP_SERVER, encoding="utf-8")
    (target / "docs").mkdir()
    (target / "docs" / "openapi.yaml").write_text(
        "openapi: 3.0.0\npaths:\n  /files/{name}.png:\n    get: {}\n  /~{user}/items:\n    get: {}\n",
        encoding="utf-8",
    )
    repo = tmp_path / "atlas"
    repo.mkdir()
    init_repo(repo, "api", targets="claude-code")
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    openapi = {k: v for k, v in profile["extractors"][0].items() if k != "hint"}
    openapi["rationale"] = "定義ファイルは docs/openapi.yaml"
    tools = {
        "name": "mcp-tools",
        "run": "abatlas-extract ast",
        "layer": "operation",
        "rationale": "MCP のツールは、@mcp.tool() を付けた関数",
        "params": {
            "files": ["srv/*.py"],
            "language": "python",
            "rule": {
                "pattern": "@mcp.tool()\nasync def $NAME($$$ARGS) -> $R:\n    $$$BODY"
            },
            "fields": {"path": "{NAME}", "name": "tool {NAME}"},
            "segments": {"prefix": ["(mcp)", "tools"]},
            "id": openapi["params"]["id"],
            "unresolved": {"any": [{"pattern": "@mcp.resource($$$A)"}]},
        },
    }
    el_path = repo / "analysis" / "entry-list.yaml"
    el_path.write_text(
        yaml.safe_dump(
            {
                "format_version": 1,
                "target": {
                    "repo": "example/kotori-api",
                    "clone_path": str(target),
                    "scope": ".",
                    "commit": "0a1b2c3d4e",
                },
                "profile": {"id": "api", "version": profile["version"]},
                "extractors": [openapi, tools],
                "entries": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    enumerate_entries(el_path, PROFILE)
    el = yaml.safe_load(el_path.read_text(encoding="utf-8"))
    assert validate_entry_list(el, profile) == []
    assert (
        {e["id"]: e["path"] for e in el["entries"]}
        == {
            "mcp_x.tools.query__mart": "/(mcp)/tools/query_mart",  # 種類の段は mcp_x。名前の中の _ は重ねる
            "files.name_d-png.get": "/files/{name}.png/get",  # 値が入る所は、段の途中にあっても _d。. は -
            "user_d.items.get": "/~{user}/items/get",
        }
    )
    assert "resource" in capsys.readouterr().err, (
        "ツールでない登録 (resource) は、読めなかった参照として知らせる"
    )
