"""abatlas コマンド。

  機械チェック
    abatlas validate profile <profile.yaml>
    abatlas validate work <work-definition.yaml>
    abatlas validate entries <entry-list.yaml> [--profile <profile.yaml>]
    abatlas validate result <result.yaml>... [--profile <profile.yaml>] [--work <work-definition.yaml>]
      --profile を省くと、分析リポジトリの作業定義 (analysis/work-definition.yaml の profile.dir) から、集計と同じプロファイルを読む (enumerate も同じ)
    abatlas validate review <review.yaml>... [--result <result.yaml>]
  入口の列挙
    abatlas enumerate <entry-list.yaml> [--profile <profile.yaml>] [--dry-run]
  分析リポジトリ (コンテナの中で動かす。分析リポジトリは /ws/analysis、対象は /ws/target)
    abatlas init <repo> --profile <id> [--targets <製品,...>]         OSS 所有の配置 + 対象層の初期ファイル + 中ハーネス (6 製品)
    abatlas upgrade <repo>                                             OSS 所有のパスだけ置き換え、製品別 adapter を再生成
    abatlas migrate <repo> [--dry-run]                                 分析する側の資産 (入口の一覧、分析結果、独自の集計表の宣言、自分用のプロファイル) の項目名を、いまの形式に書き換える (値は変えない。文の中の「(tier: <id>)」だけ直す)
  集計
    abatlas etl <analysis-dir> --out <seed-dir>                        results → seed CSV だけ
    abatlas build <repo> [--select <dbt selector>]                     ETL → dbt build (派生物は <repo>/analysis/data/)
  提供
    abatlas serve <repo> [--host 127.0.0.1] [--port 8765]              集計表 API + MCP (streamable HTTP, /mcp) + webapp (/)
    abatlas mcp [--api http://127.0.0.1:8765]                          API の薄いラッパーを stdio で (API は別プロセス)
  突合
    abatlas evaluate <results> --truth <truth> [--json]                分析結果を正解と突き合わせ、フレーム / I/O / パラメータの適合率と再現率を出す

終了コード: 0 = 合格 / 1 = 指摘あり / 2 = 入力が読めない・前提が無い
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .enumerate import enumerate_entries
from .etl import run_etl
from .schemas import load_yaml
from .validate import validate_entry_list, validate_profile, validate_result_file, validate_review, validate_work_definition


def _analysis_repo(near: Path) -> Path | None:
    """near (入口の一覧や分析結果のファイル) が属する分析リポジトリのルート。near を含む、いちばん内側の analysis/ の親。

    その analysis/ に作業定義が無ければ None (外側の分析リポジトリへは進まない。入れ子のとき、関係の無い親のプロファイルを当てないため)。
    カレントも見ない (分析リポジトリの中から、外のファイルを検査するときのため)。
    """
    from . import ANALYSIS_DIR

    for d in near.resolve().parents:
        if d.name == ANALYSIS_DIR:
            return d.parent if (d / "work-definition.yaml").exists() else None
    return None


_said: set[str] = set()


def _say(msg: str) -> None:
    """同じ知らせは 1 回だけ出す (複数のファイルを 1 回で検査するとき)。"""
    if msg not in _said:
        _said.add(msg)
        print(msg, file=sys.stderr)


def _resolve_profile(repo: Path) -> tuple[Path | None, str]:
    """分析リポジトリの、集計 (build) が読むプロファイルの場所。読めなければ (None, 理由)。

    この配布物の examples/ に置かれた公開の見本 (checkout の examples/<name>。分析リポジトリとして初期化していないので、作業定義は配布物のコピーを指すが .abatlas/ が無い) に限り、
    配布物の profiles/<id> を返す。コピーの元と同じものなので、突き合わせを省くより確かめられる。
    それ以外の場所 (配布物の外、checkout の中の spike/ など) の分析リポジトリでコピーが無いときは、読めないとして扱う (集計も止まる。検査だけが別のファイルで通ることを避ける)。
    """
    from . import OSS_DIR, REPO_ROOT
    from .build import profile_dir

    try:
        return profile_dir(repo) / "profile.yaml", "作業定義の profile.dir。集計と同じ"
    except SystemExit as ex:
        why = str(ex)
    except Exception as ex:  # 作業定義が読めない・形が違う
        return None, f"作業定義を読めない: {ex}"
    try:
        prof = load_yaml(repo / "analysis" / "work-definition.yaml")["profile"]
        rel, pid = prof.get("dir"), prof["id"]
    except Exception as ex:
        return None, f"作業定義を読めない: {ex}"
    bundled = REPO_ROOT / "profiles" / str(pid) / "profile.yaml"
    in_bundle = repo.resolve().is_relative_to((REPO_ROOT / "examples").resolve())  # 公開の見本の置き場だけ (checkout の中でも、spike/ などの普通の分析リポジトリは対象外)
    if in_bundle and isinstance(rel, str) and Path(rel).parts[:1] == (OSS_DIR,) and not (repo / OSS_DIR).exists() and bundled.exists():
        return bundled, f"配布物の中の見本で、分析リポジトリとして初期化していない ({OSS_DIR}/ が無い) ので、配布物のプロファイル"
    return None, why


def _profile_path(given: str | None, near: Path) -> Path | None:
    """検査と列挙が読むプロファイル。集計 (build) が読むのと同じファイルに揃える。near = 検査するファイル (ファイルごとに決める)。

    --profile が無ければ、near の分析リポジトリの作業定義から読む。読めないときは、その旨を出してプロファイルとの突き合わせを省く (黙って省かない)。
    --profile があればそれを使う。集計が読むものと違うときは、警告する。
    """
    repo = _analysis_repo(near)
    resolved, why = (None, "分析リポジトリの外か、そのファイルを含む analysis/ に work-definition.yaml が無い") if repo is None else _resolve_profile(repo)
    if given:
        path = Path(given)
        if resolved is not None and path.resolve() != resolved.resolve():
            _say(f"warning: --profile {given} は、{repo} の集計 (build) が読むプロファイル {resolved} と違う。作業定義の profile.dir と揃える")
        return path
    if resolved is None:
        _say(f"note: プロファイルを自動で読めないので、プロファイルとの突き合わせを省く ({why})。--profile で渡す")
        return None
    _say(f"profile: {resolved} ({why})")
    return resolved


def _report(label: str, findings: list[str]) -> int:
    if findings:
        print(f"{label}: NG ({len(findings)})")
        for f in findings:
            print(f"  - {f}")
        return 1
    print(f"{label}: OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="abatlas", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="機械チェック")
    v.add_argument("kind", choices=["profile", "work", "entries", "result", "review"])
    v.add_argument("paths", nargs="+")
    v.add_argument("--profile")
    v.add_argument("--work")
    v.add_argument("--result")

    e = sub.add_parser("enumerate", help="抽出器を実行して入口の候補を一覧に書く")
    e.add_argument("entry_list")
    e.add_argument("--profile")
    e.add_argument("--dry-run", action="store_true")

    from .layout import DEFAULT_TARGETS

    i = sub.add_parser("init", help="分析リポジトリを初期化する (OSS 所有の配置 + 対象層 + 中ハーネス)")
    i.add_argument("repo")
    i.add_argument("--profile", required=True, help="プロファイル id (profiles/<id>)")
    i.add_argument("--targets", default=DEFAULT_TARGETS, help=f"mid-harness の対象製品 (カンマ区切り。既定: {DEFAULT_TARGETS})")

    u = sub.add_parser("upgrade", help="OSS 所有のパスだけ置き換えて adapter を再生成する")
    u.add_argument("repo")

    mg = sub.add_parser("migrate", help="分析する側の資産の項目名を、いまの形式に書き換える (値は変えない。文の中の「(tier: <id>)」だけ「(layer: <id>)」に直す)")
    mg.add_argument("repo")
    mg.add_argument("--dry-run", action="store_true", help="書き換えずに、書き換わるファイルと、書き換えられないファイルを出す")

    t = sub.add_parser("etl", help="entry-list と results/*.yaml を seed CSV に分解する")
    t.add_argument("analysis_repo")
    t.add_argument("--out", required=True)

    b = sub.add_parser("build", help="ETL → dbt build")
    b.add_argument("repo")
    b.add_argument("--select")

    s = sub.add_parser("serve", help="集計表 API")
    s.add_argument("repo")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)

    m = sub.add_parser("mcp", help="MCP サーバを stdio で (API は別プロセス)")
    m.add_argument("--api", default="http://127.0.0.1:8765")

    ev = sub.add_parser("evaluate", help="分析結果を正解と突き合わせる (ディレクトリかファイル)")
    ev.add_argument("results")
    ev.add_argument("--truth", required=True)
    ev.add_argument("--json", action="store_true", help="表でなく JSON で出す")

    a = ap.parse_args(argv)
    _said.clear()  # 知らせをまとめるのは、1 回のコマンドの中だけ
    try:
        if a.cmd == "validate":
            rc = 0
            for p in a.paths:
                path = Path(p)
                if a.kind == "profile":
                    rc |= _report(p, validate_profile(load_yaml(path)))
                elif a.kind == "work":
                    rc |= _report(p, validate_work_definition(load_yaml(path)))
                elif a.kind == "entries":
                    pp = _profile_path(a.profile, path)
                    rc |= _report(p, validate_entry_list(load_yaml(path), load_yaml(pp) if pp else None))
                elif a.kind == "review":
                    try:
                        review = load_yaml(path)
                    except Exception as ex:  # YAML として読めない (引用符の欠落など)
                        rc |= _report(p, [f"yaml: 読めない: {ex}"])
                        continue
                    res = load_yaml(Path(a.result)) if a.result else None
                    rc |= _report(p, validate_review(review, res))
                else:
                    # 読み先は、ファイルごとに決める (別の分析リポジトリの結果を、1 回で検査できる)
                    rc |= _report(p, validate_result_file(path, _profile_path(a.profile, path), Path(a.work) if a.work else None))
            return rc
        if a.cmd == "enumerate":
            enumerate_entries(Path(a.entry_list), _profile_path(a.profile, Path(a.entry_list)), write=not a.dry_run)
            return 0
        if a.cmd == "init":
            from .layout import init_repo

            for line in init_repo(Path(a.repo), a.profile, a.targets):
                print(f"  + {line}")
            print(f"init: {a.repo} (profile {a.profile})。次: .env の ABATLAS_TARGET と analysis/work-definition.yaml を埋めて "
                  "`docker compose run --rm abatlas validate work analysis/work-definition.yaml`")
            return 0
        if a.cmd == "upgrade":
            from .layout import upgrade_repo

            placed = upgrade_repo(Path(a.repo))
            print("upgrade: 置き換えた " + ", ".join(placed) + " / 製品別 adapter を再生成した")
            return 0
        if a.cmd == "migrate":
            from .migrate import migrate_repo

            lines, rc = migrate_repo(Path(a.repo), a.dry_run)
            print("\n".join(lines))
            return rc
        if a.cmd == "etl":
            counts = run_etl(Path(a.analysis_repo), Path(a.out))
            print("etl: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
            return 0
        if a.cmd == "build":
            from .build import build_repo

            rep = build_repo(Path(a.repo), a.select)
            print("build: " + ", ".join(f"{k}={v}" for k, v in rep.items()))
            return 0
        if a.cmd == "serve":
            from .api import serve

            serve(Path(a.repo), a.host, a.port)
            return 0
        if a.cmd == "mcp":
            from .mcp_server import run

            run(a.api)
            return 0
        if a.cmd == "evaluate":
            from .evaluate import main_cli

            return main_cli(a.results, a.truth, a.json)
    except SystemExit as ex:
        if isinstance(ex.code, str):
            print(ex.code, file=sys.stderr)
            return 2
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
