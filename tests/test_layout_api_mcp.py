"""配布形態 (Docker だけ): init / upgrade / build / API + MCP を、見本の分析結果で端から端まで通す。"""

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteClient

from abatlas import ANALYSIS_DIR, OSS_DIR, dbt_workdir, duckdb_path
from abatlas.api import create_app, create_server
from abatlas.build import build_repo, render_dbt_project
from abatlas.layout import HOOK_SCRIPT, OSS_SKILLS, init_repo, owned_paths, upgrade_repo
from abatlas.mcp_server import build_server, in_process_client

FIX = Path(__file__).resolve().parent / "fixtures"
LOCAL = "http://127.0.0.1:8765"  # API は Host がループバック名でない要求を拒む。TestClient の既定 (testserver) では通らない


def client(repo: Path) -> TestClient:
    return TestClient(create_app(repo), base_url=LOCAL)


def _entry_list(target: dict) -> dict:
    return {
        "format_version": 1,
        "target": target,
        "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [
            {
                "name": "kestra-flows",
                "run": "abatlas-extract structured-query",
                "layer": "scheduler",
                "params": {},
                "rationale": "test",
            }
        ],
        "enumerated_at": "2026-11-04T00:00:00+09:00",
        "entries": [
            {
                "id": "daily.housekeeping",
                "path": "/daily/housekeeping",
                "name": "housekeeping",
                "layer": "scheduler",
                "status": "approved",
                "source": {"file": "flows/daily/housekeeping.yaml", "line": 1},
                "extractor": "kestra-flows",
            },
            {
                "id": "daily.other",
                "path": "/daily/other",
                "name": "other",
                "layer": "scheduler",
                "status": "approved",
                "source": {"file": "flows/daily/other.yaml", "line": 1},
                "extractor": "kestra-flows",
            },
        ],
    }


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    """init した分析リポジトリに見本の結果を置き、build まで済ませる (module で 1 回)。"""
    repo = tmp_path_factory.mktemp("analysis-repo")
    made = init_repo(repo, "batch-kestra", targets="claude-code")
    assert any(m.startswith(OSS_DIR) for m in made)
    an = repo / ANALYSIS_DIR
    result = yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )
    result["analyzer"]["run"] = {
        "cost_usd": 8.36,
        "duration_s": 656,
        "by": "test-runner",
    }
    (an / "results" / "daily.housekeeping.yaml").write_text(
        yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (an / "entry-list.yaml").write_text(
        yaml.safe_dump(
            _entry_list(result["target"]), allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    # リポ所有の mart を 1 本置く (upgrade で消えないことを後で確かめる)
    (an / "dbt" / "models" / "repo" / "mart_repo_example.sql").write_text(
        "select count(*) as n from {{ ref('stg_entries') }}\n", encoding="utf-8"
    )
    (an / "dbt" / "models" / "repo" / "schema.yml").write_text(
        "version: 2\nmodels:\n  - name: mart_repo_example\n    description: repo 独自\n    meta:\n      abatlas: { origin: repo, view: stat, level: path, attach: any, keys: { value: n } }\n",
        encoding="utf-8",
    )
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"], rep
    return repo


# ---------------------------------------------------------------- 配置


def test_init_layout(repo: Path):
    oss = repo / OSS_DIR
    for item in (
        "schema/analysis-result.schema.json",
        "profiles/batch-kestra/profile.yaml",
        "profiles/batch-kestra/context.md",
        "tests/fixtures/result-housekeeping.yaml",
        "docs/architecture/README.md",
        "docs/guide/README.md",
        "docs/reference/README.md",
        "docs/reference/profiles/ui-nextjs.md",
        "OWNED.md",
    ):
        assert (oss / item).exists(), item
    # init と upgrade の完了表示が案内する手引きが、その場所にある
    from abatlas.cli import GUIDE_PATH

    assert (repo / GUIDE_PATH).exists(), GUIDE_PATH
    # 実行環境と dbt テンプレートは分析リポジトリに置かない (Docker だけで動く)
    assert not (oss / "abatlas").exists() and not (oss / "pyproject.toml").exists()
    assert (
        not (oss / "profiles" / "batch-kestra" / "dbt-template").exists()
        and not (repo / "dbt-template").exists()
    )
    assert not list(repo.rglob("__pycache__"))
    # skill は OSS 所有の実ディレクトリ (symlink ではない)
    for sk in OSS_SKILLS:
        d = repo / ".agents" / "skills" / sk
        assert d.is_dir() and not d.is_symlink() and (d / "SKILL.md").exists(), sk
    assert (repo / HOOK_SCRIPT).exists() and (repo / "compose.yaml").exists()
    # 中ハーネスと対象層
    assert (
        (repo / "AGENTS.md").exists()
        and (repo / "CLAUDE.md").exists()
        and (repo / ".agents" / "harness.yaml").exists()
    )
    assert (
        repo / ".agents" / "memory" / "desired-state" / "analysis-conventions.md"
    ).exists()
    assert "analysis-conventions.md" in (
        repo / ".agents" / "memory" / "index.md"
    ).read_text(encoding="utf-8")
    assert (repo / ".env").exists() and (
        repo / ANALYSIS_DIR / "work-definition.yaml"
    ).exists()
    assert (repo / ANALYSIS_DIR / "dbt" / "models" / "repo" / "README.md").exists()
    # 製品別 adapter が生成されている (skill は .agents/skills への symlink)
    link = repo / ".claude" / "skills" / "abatlas-analyze-entry"
    assert (
        link.exists()
        and (link / "SKILL.md").resolve()
        == (repo / ".agents/skills/abatlas-analyze-entry/SKILL.md").resolve()
    )
    assert "analysis/data/" in (repo / ".gitignore").read_text(encoding="utf-8")


def test_init_is_idempotent_for_target_layer(repo: Path):
    wd = repo / ANALYSIS_DIR / "work-definition.yaml"
    wd.write_text(wd.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    env = repo / ".env"
    env.write_text(env.read_text(encoding="utf-8") + "# mine\n", encoding="utf-8")
    init_repo(repo, "batch-kestra", targets="claude-code")
    assert "# edited" in wd.read_text(encoding="utf-8") and "# mine" in env.read_text(
        encoding="utf-8"
    )


def test_upgrade_replaces_owned_paths_only(repo: Path):
    junk = repo / OSS_DIR / "junk.txt"
    junk.write_text("x", encoding="utf-8")
    hook = repo / HOOK_SCRIPT
    hook.write_text("# broken\n", encoding="utf-8")
    skill_junk = repo / ".agents" / "skills" / "abatlas-analyze-entry" / "junk.md"
    skill_junk.write_text("x", encoding="utf-8")
    conv = repo / ".agents" / "memory" / "desired-state" / "analysis-conventions.md"
    conv.write_text(conv.read_text(encoding="utf-8") + "\n## 追記\n", encoding="utf-8")
    placed = upgrade_repo(repo)
    assert set(placed) == set(owned_paths())
    assert not junk.exists() and not skill_junk.exists()
    assert "pre-tool-policy" in hook.read_text(
        encoding="utf-8"
    )  # hook 本体は配布物の版で置き換わる (修正が届く)
    assert "## 追記" in conv.read_text(encoding="utf-8")  # memory は保持
    assert (
        repo / ANALYSIS_DIR / "dbt" / "models" / "repo" / "mart_repo_example.sql"
    ).exists()
    assert (repo / ANALYSIS_DIR / "results" / "daily.housekeeping.yaml").exists()


def test_upgrade_requires_initialized_repo(tmp_path: Path):
    with pytest.raises(SystemExit, match="初期化されていない"):
        upgrade_repo(tmp_path / "empty")


def test_init_fails_loudly_when_distribution_incomplete(tmp_path: Path):
    broken = tmp_path / "broken-oss"
    (broken / "schema").mkdir(parents=True)
    with pytest.raises(SystemExit, match="必要なものが無い"):
        init_repo(tmp_path / "r", "batch-kestra", targets="claude-code", src=broken)
    assert not (tmp_path / "r" / OSS_DIR).exists()


def test_init_generates_adapters_for_all_six_products(tmp_path_factory):
    from abatlas.layout import DEFAULT_TARGETS

    repo = tmp_path_factory.mktemp("six")
    init_repo(repo, "batch-kestra", targets=DEFAULT_TARGETS)
    for p in (
        ".claude/settings.json",
        ".codex/hooks.json",
        ".cursor/hooks.json",
        ".grok/hooks/mid-harness.json",
        ".github/hooks/mid-harness.json",
        ".agents/hooks.json",
    ):
        assert (repo / p).exists(), p


# ---------------------------------------------------------------- build (dbt の合成)


def test_build_renders_dbt_from_distribution_and_repo_models(repo: Path):
    work = dbt_workdir(repo)
    assert (work / "dbt_project.yml").exists() and (
        work / "models" / "core" / "mart_entry_overview.sql"
    ).exists()
    assert (work / "models" / "profile" / "mart_namespace_summary.sql").exists()
    assert (work / "models" / "repo" / "mart_repo_example.sql").exists()
    # 作業ディレクトリを汚しても次の合成で戻る (派生物)
    (work / "models" / "core" / "junk.sql").write_text("select 1", encoding="utf-8")
    render_dbt_project(repo)
    assert not (work / "models" / "core" / "junk.sql").exists()
    assert (work / "models" / "repo" / "mart_repo_example.sql").exists()
    assert duckdb_path(repo) == repo / ANALYSIS_DIR / "data" / "abatlas.duckdb"


def test_render_fails_when_profile_missing(repo: Path):
    with pytest.raises(SystemExit, match="プロファイル nope"):
        render_dbt_project(repo, "nope")
    assert (
        dbt_workdir(repo) / "models" / "profile" / "mart_namespace_summary.sql"
    ).exists()  # 失敗時に消していない


def test_scope_can_be_overridden_for_container(tmp_path: Path, monkeypatch):
    """コンテナでは対象の clone が /ws/target に見える。clone_path の代わりに ABATLAS_TARGET_ROOT を使う。"""
    from abatlas.validate import _resolve_scope

    (tmp_path / "mounted" / "sub").mkdir(parents=True)
    monkeypatch.setenv("ABATLAS_TARGET_ROOT", str(tmp_path / "mounted"))
    assert (
        _resolve_scope(
            {"clone_path": "/nonexistent/host/path", "scope": "sub"}, tmp_path
        )
        == tmp_path / "mounted" / "sub"
    )
    monkeypatch.delenv("ABATLAS_TARGET_ROOT")
    assert (
        _resolve_scope(
            {"clone_path": str(tmp_path / "mounted"), "scope": "sub"}, tmp_path
        )
        == tmp_path / "mounted" / "sub"
    )


# ---------------------------------------------------------------- API


def test_api_declaration_driven(repo: Path):
    c = client(repo)
    assert c.get("/health").json()["duckdb_exists"]
    marts = {m["name"]: m for m in c.get("/marts").json()}
    assert {
        "mart_entry_overview",
        "mart_progress",
        "mart_namespace_summary",
        "mart_repo_example",
    } <= set(marts)
    assert marts["mart_namespace_summary"]["declaration"]["origin"] == "profile"
    assert marts["mart_repo_example"]["declaration"]["origin"] == "repo"
    assert not any(
        n.startswith("stg_") for n in marts
    )  # staging は宣言が無いので出ない
    d = c.get("/marts/mart_entry_overview").json()
    assert d["total"] == 2 and {"entry_id", "run_cost_usd"} <= {
        col["name"] for col in d["columns"]
    }
    rows = c.get(
        "/marts/mart_entry_overview/rows", params={"entry_id": "daily.housekeeping"}
    ).json()
    assert (
        rows["total"] == 1
        and rows["rows"][0]["analyzed"] is True
        and rows["rows"][0]["run_cost_usd"] == pytest.approx(8.36)
    )
    prog = c.get("/marts/mart_progress/rows").json()["rows"][0]
    assert prog["approved"] == 2 and prog["analyzed"] == 1
    # 一方は旧版の結果、もう一方は未分析。今回の作業は 2 入口分。
    assert rows["rows"][0]["update_status"] == "stale"
    assert prog["current_results"] == prog["reused_results"] == 0
    assert prog["estimated_remaining_cost_usd"] == pytest.approx(2 * 8.36)
    assert (
        c.get("/marts/mart_entry_overview/rows", params={"nope": "1"}).status_code
        == 400
    )
    assert c.get("/marts/stg_entries").status_code == 404
    assert c.get("/marts/x;drop/rows").status_code == 404


@pytest.mark.parametrize("exit_code", [1, "dbt failed", None])
def test_recompute_keeps_serving_after_build_exit(repo, monkeypatch, exit_code):
    def fail_build(_repo):
        raise SystemExit(exit_code)

    monkeypatch.setattr("abatlas.api.build_repo", fail_build)
    with client(repo) as api:
        assert api.post("/recompute").status_code == 500
        assert api.post("/recompute").status_code == 500
        assert api.get("/health").status_code == 200


def test_recompute_rebuilds(repo: Path):
    c = client(repo)
    r = c.post("/recompute")
    assert (
        r.status_code == 200
        and r.json()["ok"]
        and r.json()["dbt_ok"] == r.json()["dbt_nodes"]
    )


def test_profile_mart_does_not_double_count(repo: Path):
    c = client(repo)
    ns = c.get("/marts/mart_namespace_summary/rows").json()["rows"][0]
    ov = c.get(
        "/marts/mart_entry_overview/rows", params={"entry_id": "daily.housekeeping"}
    ).json()["rows"][0]
    assert ns["namespace"] == "daily" and ns["flows"] == 2 and ns["analyzed_flows"] == 1
    assert ns["rdb_io"] + ns["filesystem_io"] + ns["external_api_io"] == ov["io_count"]


def test_recompute_rejects_cross_site(repo: Path):
    c = client(repo)
    assert (
        c.post("/recompute", headers={"Origin": "http://evil.example"}).status_code
        == 403
    )
    assert c.post("/recompute", headers={"Host": "evil.example"}).status_code == 403
    assert (
        c.post(
            "/recompute",
            headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"},
        ).status_code
        == 200
    )
    assert (
        c.get("/marts", headers={"Host": "evil.example"}).status_code == 403
    )  # 読む経路も Host を見る (DNS rebinding 対策は MCP 側と同じ基準)
    assert (
        TestClient(create_app(repo)).get("/health").status_code == 403
    )  # 既定 Host (testserver) は通らない


def test_api_quotes_identifiers(repo: Path):
    import duckdb

    from abatlas.api import _q

    with duckdb.connect(str(duckdb_path(repo))) as con:
        con.execute(
            'create or replace table mart.mart_odd as select 1 as "run-cost", \'x\' as "a""b"'
        )
    c = client(repo)
    assert (
        c.get("/marts/mart_odd").status_code == 404
    )  # manifest に無いので宣言としては出ない
    assert _q('a"b') == '"a""b"' and _q("run-cost") == '"run-cost"'
    assert (
        c.get(
            "/marts/mart_entry_overview/rows", params={"entry_id": "daily.housekeeping"}
        ).json()["total"]
        == 1
    )


# ---------------------------------------------------------------- MCP


def test_mcp_is_thin_wrapper(repo: Path):
    api = in_process_client(create_app(repo))
    names = {m["name"] for m in asyncio.run(api.list_marts())}
    assert "mart_data_access" in names
    q = asyncio.run(
        api.query_mart(
            "mart_entry_overview", {"entry_id": "daily.housekeeping"}, limit=5
        )
    )
    assert q["total"] == 1
    assert asyncio.run(api.describe_mart("missing"))["status"] == 404
    server = build_server(api)
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == {
        "list_marts",
        "describe_mart",
        "query_mart",
        "group_mart",
        "recompute",
        "describe_atlas",
    }


def test_serve_combines_api_and_mcp_over_http(repo: Path):
    """1 つのプロセスで API (/marts) と MCP (/mcp, streamable HTTP) を出す。"""
    with StarletteClient(create_server(repo), base_url="http://127.0.0.1:8765") as c:
        assert c.get("/health").json()["ok"]
        assert "mart_entry_overview" in {m["name"] for m in c.get("/marts").json()}
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
        r = c.post(
            "/mcp",
            json=init,
            headers={
                "Accept": "application/json, text/event-stream",
                "Host": "127.0.0.1:8765",
            },
        )
        assert r.status_code == 200, r.text
        assert "as-built-atlas" in r.text and r.headers.get("mcp-session-id")
        # Host がループバック名でなければ MCP も拒む (DNS rebinding 対策は SDK の既定)
        assert c.post(
            "/mcp",
            json=init,
            headers={
                "Accept": "application/json, text/event-stream",
                "Host": "evil.example",
            },
        ).status_code in (400, 403, 421)


def test_etl_rejects_duplicate_entry_ids(tmp_path: Path):
    from abatlas.etl import run_etl

    src = FIX / "result-housekeeping.yaml"
    r = tmp_path / "r"
    (r / "results").mkdir(parents=True)
    result = yaml.safe_load(src.read_text(encoding="utf-8"))
    (r / "results" / "daily.housekeeping.yaml").write_text(
        yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (r / "results" / "daily.housekeeping.copy.yaml").write_text(
        yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (r / "entry-list.yaml").write_text(
        yaml.safe_dump(
            _entry_list(result["target"]), allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        run_etl(r, tmp_path / "seeds")


def test_install_owned_rolls_back_when_swap_fails(repo: Path, monkeypatch):
    """置き換えの途中で失敗しても、OSS 所有のパスは旧版か新版のどちらかが揃っている (消えない)。"""
    from abatlas import layout

    hook = repo / HOOK_SCRIPT
    hook.write_text("# old hook\n", encoding="utf-8")
    compose_before = (repo / "compose.yaml").read_text(encoding="utf-8")
    real_rename = Path.rename

    def flaky(self, target):  # compose.yaml (最後) の入れ替えで失敗させる
        if (
            self.name == "compose.yaml"
            and str(target).endswith("compose.yaml")
            and ".abatlas.stage." in str(self)
            and "/old/" not in str(self)
        ):
            raise OSError("disk full")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    with pytest.raises(OSError):
        layout.install_owned(repo)
    monkeypatch.setattr(Path, "rename", real_rename)
    assert hook.read_text(encoding="utf-8") == "# old hook\n"  # 戻っている
    assert (repo / "compose.yaml").read_text(encoding="utf-8") == compose_before
    for sk in OSS_SKILLS:
        assert (repo / ".agents" / "skills" / sk / "SKILL.md").exists(), sk
    assert (repo / OSS_DIR / "OWNED.md").exists() and not list(
        repo.glob(".abatlas.stage.*")
    )
    layout.install_owned(repo)  # やり直せる
    assert "pre-tool-policy" in hook.read_text(encoding="utf-8")


def test_upgrade_refuses_old_layout(tmp_path: Path):
    """段階 3 までの配置 (分析資産がルート直下) は upgrade で黙って見失わず、移行手順を出して止まる。"""
    repo = tmp_path / "old"
    (repo / ".agents").mkdir(parents=True)
    (repo / ".agents" / "harness.yaml").write_text(
        "targets: [claude-code]\n", encoding="utf-8"
    )
    (repo / "work-definition.yaml").write_text("format_version: 1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="旧配置"):
        upgrade_repo(repo)
    assert not (repo / "compose.yaml").exists()


def test_relative_clone_path_is_resolved_from_repo_root(tmp_path: Path):
    """analysis/work-definition.yaml の相対 clone_path は分析リポジトリのルートから解決する (.env の ABATLAS_TARGET と同じ基準)。"""
    from abatlas.validate import _resolve_scope

    (tmp_path / "target" / "sub").mkdir(parents=True)
    (tmp_path / "my-analysis" / ANALYSIS_DIR).mkdir(parents=True)
    got = _resolve_scope(
        {"clone_path": "../target", "scope": "sub"},
        tmp_path / "my-analysis" / ANALYSIS_DIR,
    )
    assert got == tmp_path / "target" / "sub"
    # analysis/ の下でなければ従来どおりファイルの場所から
    (tmp_path / "elsewhere").mkdir()
    assert (
        _resolve_scope(
            {"clone_path": "../target", "scope": "sub"}, tmp_path / "elsewhere"
        )
        == tmp_path / "target" / "sub"
    )


def test_interrupted_install_is_recovered_on_next_run(repo: Path):
    """強制終了で stage が残り配置先が欠けていても、次の install_owned が退避した旧版を戻してから進む。"""
    from abatlas import layout

    stage = repo / ".abatlas.stage.leftover"
    old = stage / "old" / HOOK_SCRIPT
    old.parent.mkdir(parents=True)
    (repo / HOOK_SCRIPT).rename(
        old
    )  # 旧版は退避済み、新版は未配置 = 2 つの rename の間で止まった状態
    assert not (repo / HOOK_SCRIPT).exists()
    assert layout.recover_interrupted_install(repo) == [HOOK_SCRIPT]
    assert (repo / HOOK_SCRIPT).exists() and not stage.exists()
    layout.install_owned(repo)
    assert "pre-tool-policy" in (repo / HOOK_SCRIPT).read_text(encoding="utf-8")


def test_old_layout_detection_catches_partial_migration(tmp_path: Path):
    from abatlas.layout import detect_old_layout

    repo = tmp_path / "half"
    (repo / ANALYSIS_DIR).mkdir(parents=True)
    (repo / ANALYSIS_DIR / "work-definition.yaml").write_text(
        "x", encoding="utf-8"
    )  # 作業定義だけ移した
    (repo / "results").mkdir()
    assert "results" in (detect_old_layout(repo) or "")
    (repo / "results").rmdir()
    assert detect_old_layout(repo) is None


def test_relative_clone_path_from_results_dir_uses_repo_root(tmp_path: Path):
    """--work なしで analysis/results/<file> を検査するときも、相対 clone_path の基準は分析リポジトリのルート。"""
    from abatlas.validate import _resolve_scope

    (tmp_path / "target" / "sub").mkdir(parents=True)
    results = tmp_path / "my-analysis" / ANALYSIS_DIR / "results"
    results.mkdir(parents=True)
    assert (
        _resolve_scope({"clone_path": "../target", "scope": "sub"}, results)
        == tmp_path / "target" / "sub"
    )


def test_allowed_hosts_apply_to_api_and_mcp_alike(repo: Path, monkeypatch):
    monkeypatch.setenv("ABATLAS_ALLOWED_HOSTS", "atlas.internal")
    with StarletteClient(
        create_server(repo), base_url="http://atlas.internal:8765"
    ) as c:
        assert c.get("/marts").status_code == 200
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
        assert (
            c.post(
                "/mcp",
                json=init,
                headers={"Accept": "application/json, text/event-stream"},
            ).status_code
            == 200
        )
        assert c.get("/marts", headers={"Host": "evil.example"}).status_code == 403
        assert c.post(
            "/mcp",
            json=init,
            headers={
                "Accept": "application/json, text/event-stream",
                "Host": "evil.example",
            },
        ).status_code in (400, 403, 421)


def test_mcp_accepts_host_without_port(repo: Path):
    """既定ポートやリバースプロキシ経由で Host にポートが無くても、API と同様に MCP も通す。"""
    with StarletteClient(create_server(repo), base_url="http://localhost") as c:
        assert c.get("/health").status_code == 200
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
        r = c.post(
            "/mcp",
            json=init,
            headers={
                "Accept": "application/json, text/event-stream",
                "Origin": "http://localhost",
            },
        )
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------- プロファイルの読み先 (作業定義の profile.dir)


def _repo_with_result(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    init_repo(repo, "batch-kestra", targets="claude-code")
    an = repo / ANALYSIS_DIR
    result = yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )
    (an / "results" / "daily.housekeeping.yaml").write_text(
        yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (an / "entry-list.yaml").write_text(
        yaml.safe_dump(
            _entry_list(result["target"]), allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return repo


def _set_profile_dir(repo: Path, value: str | None) -> None:
    wd = repo / ANALYSIS_DIR / "work-definition.yaml"
    work = yaml.safe_load(wd.read_text(encoding="utf-8"))
    if value is None:
        work["profile"].pop("dir", None)
    else:
        work["profile"]["dir"] = value
    wd.write_text(
        yaml.safe_dump(work, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_build_reads_profile_from_work_definition_dir(tmp_path: Path):
    """集計は、作業定義の profile.dir のプロファイルを読む (検査や列挙に渡すのと同じファイル)。自分用に写して layer を減らすと、画面の層の並びも変わる。"""
    import shutil

    from abatlas.build import profile_dir

    repo = _repo_with_result(tmp_path)
    assert (
        profile_dir(repo) == (repo / OSS_DIR / "profiles" / "batch-kestra").resolve()
    ), "init の既定は分析リポジトリの中のコピー"
    own = repo / ANALYSIS_DIR / "profiles" / "batch-kestra"
    shutil.copytree(repo / OSS_DIR / "profiles" / "batch-kestra", own)
    prof = yaml.safe_load((own / "profile.yaml").read_text(encoding="utf-8"))
    prof["layers"] = [t for t in prof["layers"] if t["id"] != "agent_skill"]
    (own / "profile.yaml").write_text(
        yaml.safe_dump(prof, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    _set_profile_dir(repo, "analysis/profiles/batch-kestra")
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"], rep
    layers = [t["id"] for t in client(repo).get("/meta").json()["profile"]["layers"]]
    assert layers == ["scheduler", "shell", "program", "external"], (
        "写したプロファイルの層の並びが出る"
    )
    assert any(
        m["declaration"]["origin"] == "profile"
        for m in client(repo).get("/marts").json()
    ), (
        "プロファイル固有の mart は、写した場所に dbt-template が無ければ配布物のものを使う"
    )
    # 未記入なら配布物のプロファイル
    _set_profile_dir(repo, None)
    build_repo(repo)
    assert "agent_skill" in [
        t["id"] for t in client(repo).get("/meta").json()["profile"]["layers"]
    ]


def test_validate_and_enumerate_read_the_same_profile_as_build(tmp_path: Path, capsys):
    """検査と列挙は、--profile を省くと、作業定義の profile.dir (集計と同じ) からプロファイルを読む。違うものを渡すと警告する。"""
    from abatlas.cli import _profile_path, main

    repo = _repo_with_result(tmp_path)
    el = repo / ANALYSIS_DIR / "entry-list.yaml"
    want = (repo / OSS_DIR / "profiles" / "batch-kestra" / "profile.yaml").resolve()
    assert _profile_path(None, el).resolve() == want
    assert (
        _profile_path(
            None, repo / ANALYSIS_DIR / "results" / "daily.housekeeping.yaml"
        ).resolve()
        == want
    )
    assert "集計と同じ" in capsys.readouterr().err
    # 別のプロファイルを渡すと、使いはするが警告する
    other = tmp_path / "other.yaml"
    other.write_text(want.read_text(encoding="utf-8"), encoding="utf-8")
    assert _profile_path(str(other), el) == other and "違う" in capsys.readouterr().err
    # 分析リポジトリの外のファイルは、カレントが分析リポジトリでも、読めない旨を出して突き合わせを省く (関係の無いプロファイルを当てない)
    import os

    lone = tmp_path / "lone" / "entry-list.yaml"
    lone.parent.mkdir()
    lone.write_text(el.read_text(encoding="utf-8"), encoding="utf-8")
    old = os.getcwd()
    os.chdir(repo)
    try:
        assert _profile_path(None, lone) is None and "省く" in capsys.readouterr().err
    finally:
        os.chdir(old)
    # コマンドとしても通る (--profile なし)
    assert main(["validate", "entries", str(el)]) == 0
    assert "OK" in capsys.readouterr().out
    # 入れ子: 内側の analysis/ に作業定義が無ければ、外側の分析リポジトリのプロファイルを当てない
    inner = repo / "sub" / ANALYSIS_DIR / "entry-list.yaml"
    inner.parent.mkdir(parents=True)
    inner.write_text(el.read_text(encoding="utf-8"), encoding="utf-8")
    assert _profile_path(None, inner) is None and "省く" in capsys.readouterr().err
    # 配布物の外の分析リポジトリで、配布物のコピーが無いときは、配布物へ切り替えず、読めないとして扱う (集計も止まる)
    import shutil

    shutil.move(str(repo / OSS_DIR), str(tmp_path / "oss-away"))
    assert (
        _profile_path(None, el) is None
        and "profile.yaml が無い" in capsys.readouterr().err
    )
    shutil.move(str(tmp_path / "oss-away"), str(repo / OSS_DIR))


def test_enumerate_reads_profile_from_work_definition(
    tmp_path: Path, capsys, monkeypatch
):
    """列挙は、--profile なしで、作業定義のプロファイルを読んで最後まで動く (対象の clone がある見本で、終了コード 0)。"""
    import shutil

    from abatlas import REPO_ROOT, cli

    shutil.copytree(REPO_ROOT / "examples" / "kotori-books", tmp_path / "kotori-books")
    atlas = tmp_path / "kotori-books-atlas"
    shutil.copytree(REPO_ROOT / "examples" / "kotori-books-atlas", atlas)
    init_repo(atlas, "batch-kestra", targets="claude-code")
    monkeypatch.delenv("ABATLAS_TARGET_ROOT", raising=False)
    got: list = []
    real = cli.enumerate_entries
    monkeypatch.setattr(
        cli,
        "enumerate_entries",
        lambda el, prof, write=True: got.append(prof) or real(el, prof, write=write),
    )
    el = atlas / ANALYSIS_DIR / "entry-list.yaml"
    before = el.read_text(encoding="utf-8")
    assert cli.main(["enumerate", str(el), "--dry-run"]) == 0
    assert got == [
        (atlas / OSS_DIR / "profiles" / "batch-kestra" / "profile.yaml").resolve()
    ], got
    assert (
        "集計と同じ" in capsys.readouterr().err
        and el.read_text(encoding="utf-8") == before
    )


def test_validate_result_resolves_profile_per_file(tmp_path: Path, capsys, monkeypatch):
    """複数の分析結果を 1 回で検査するとき、読み先は、ファイルごとに、その分析リポジトリから決める (最初のファイルのものを使い回さない)。"""
    from abatlas import cli

    a = _repo_with_result(tmp_path / "a")
    b = _repo_with_result(tmp_path / "b")
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli,
        "validate_result_file",
        lambda path, prof, work: seen.append((str(path), str(prof))) or [],
    )
    cli._said.clear()
    ra, rb = (r / ANALYSIS_DIR / "results" / "daily.housekeeping.yaml" for r in (a, b))
    assert cli.main(["validate", "result", str(ra), str(rb), str(ra)]) == 0
    assert [
        Path(p).resolve().is_relative_to(Path(f).resolve().parents[2]) for f, p in seen
    ] == [True, True, True], seen
    assert seen[0][1] != seen[1][1] and seen[0][1] == seen[2][1]
    assert capsys.readouterr().err.count("profile: ") == 2, (
        "同じ読み先の知らせは 1 回だけ"
    )


def test_uninitialized_sample_uses_bundled_profile(capsys):
    """この checkout の見本 (分析リポジトリとして初期化していない。.abatlas/ が無い) は、突き合わせを省かず、配布物のプロファイルで検査する。"""
    from abatlas import REPO_ROOT, cli

    cli._said.clear()
    el = REPO_ROOT / "examples" / "kotori-books-atlas" / "analysis" / "entry-list.yaml"
    assert (
        cli._profile_path(None, el)
        == REPO_ROOT / "profiles" / "batch-kestra" / "profile.yaml"
    )
    assert "初期化していない" in capsys.readouterr().err


def test_bundled_profile_fallback_is_limited_to_examples(
    tmp_path: Path, capsys, monkeypatch
):
    """配布物のプロファイルへの切り替えは、配布物の examples/ の見本だけ。checkout の中でも、ほかの場所 (spike/ など) の分析リポジトリでは、読めないとして扱う。"""
    import shutil

    import abatlas
    from abatlas import cli

    root = tmp_path / "checkout"
    shutil.copytree(
        abatlas.REPO_ROOT / "profiles" / "batch-kestra",
        root / "profiles" / "batch-kestra",
    )
    monkeypatch.setattr(abatlas, "REPO_ROOT", root)
    src = abatlas.REPO_ROOT.parent  # 使わない (名前の取り違え防止のためだけ)
    del src
    real_examples = (
        Path(__file__).resolve().parent.parent
        / "examples"
        / "kotori-books-atlas"
        / "analysis"
    )
    for place in ("examples/sample", "spike/mine"):
        an = root / place / ANALYSIS_DIR
        an.mkdir(parents=True)
        for name in ("work-definition.yaml", "entry-list.yaml"):
            shutil.copy(real_examples / name, an / name)
    cli._said.clear()
    assert (
        cli._profile_path(
            None, root / "examples/sample" / ANALYSIS_DIR / "entry-list.yaml"
        )
        == root / "profiles" / "batch-kestra" / "profile.yaml"
    )
    assert (
        cli._profile_path(None, root / "spike/mine" / ANALYSIS_DIR / "entry-list.yaml")
        is None
    )
    assert "profile.yaml が無い" in capsys.readouterr().err


def test_build_warns_when_oss_profile_copy_differs_from_bundle(tmp_path: Path, capsys):
    """配布物のコピーの中身が配布物と違うとき (イメージだけ新しくして upgrade を忘れた)、集計は警告する。止めはしない。自分用に写したものは対象外。"""
    import shutil

    from abatlas.build import oss_copy_outdated

    repo = _repo_with_result(tmp_path)
    assert oss_copy_outdated(repo) is None
    copy = repo / OSS_DIR / "profiles" / "batch-kestra" / "profile.yaml"
    copy.write_text(
        copy.read_text(encoding="utf-8") + "\n# 古い版のつもり\n", encoding="utf-8"
    )
    assert "upgrade" in oss_copy_outdated(repo)
    rep = build_repo(repo)
    assert (
        rep["dbt_ok"] == rep["dbt_nodes"] and "配布物と違う" in capsys.readouterr().err
    )
    own = repo / ANALYSIS_DIR / "profiles" / "batch-kestra"
    shutil.copytree(copy.parent, own)
    _set_profile_dir(repo, "analysis/profiles/batch-kestra")
    assert oss_copy_outdated(repo) is None, (
        "自分用に写したプロファイルは、配布物と違ってよい"
    )


def test_build_stops_on_bad_profile_dir(tmp_path: Path):
    """profile.dir が指す場所に無い・外を指す・id が違う・検査に通らないときは、配布物へ黙って切り替えずに止める。"""
    repo = _repo_with_result(tmp_path)
    _set_profile_dir(repo, "analysis/profiles/none")
    with pytest.raises(SystemExit, match="profile.yaml が無い"):
        build_repo(repo)
    _set_profile_dir(repo, "../outside")
    with pytest.raises(SystemExit, match="外を指している"):
        build_repo(repo)
    # 空文字は「未記入」として配布物へ切り替えない (形式の検査でも落ちる)
    from abatlas.validate import validate_work_definition

    _set_profile_dir(repo, "")
    with pytest.raises(SystemExit, match="profile.dir が空"):
        build_repo(repo)
    assert validate_work_definition(
        yaml.safe_load(
            (repo / ANALYSIS_DIR / "work-definition.yaml").read_text(encoding="utf-8")
        )
    )
    # ディレクトリは中でも、profile.yaml そのものが外を指すリンクなら止める
    outside = tmp_path / "outside.yaml"
    outside.write_text(
        (repo / OSS_DIR / "profiles" / "batch-kestra" / "profile.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    linked = repo / ANALYSIS_DIR / "profiles" / "linked"
    linked.mkdir(parents=True)
    (linked / "profile.yaml").symlink_to(outside)
    _set_profile_dir(repo, "analysis/profiles/linked")
    with pytest.raises(SystemExit, match="外を指すリンク"):
        build_repo(repo)
    own = repo / ANALYSIS_DIR / "profiles" / "mine"
    own.mkdir(parents=True)
    src = yaml.safe_load(
        (repo / OSS_DIR / "profiles" / "batch-kestra" / "profile.yaml").read_text(
            encoding="utf-8"
        )
    )
    (own / "profile.yaml").write_text(
        yaml.safe_dump({**src, "id": "other"}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _set_profile_dir(repo, "analysis/profiles/mine")
    with pytest.raises(SystemExit, match="id が"):
        build_repo(repo)
    (own / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                **src,
                "layers": [t for t in src["layers"] if t.get("role") != "boundary"],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="検査に通らない"):
        build_repo(repo)
