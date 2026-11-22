"""abatlas コマンド。

  機械チェック
    abatlas validate profile <profile.yaml>
    abatlas validate work <work-definition.yaml>
    abatlas validate entries <entry-list.yaml> [--profile <profile.yaml>]
    abatlas validate result <result.yaml>... [--profile <profile.yaml>] [--work <work-definition.yaml>]
      --profile を省くと、分析リポジトリの作業定義 (analysis/work-definition.yaml の profile.dir) から、集計と同じプロファイルを読む (enumerate も同じ)
    abatlas validate review <review.yaml>... [--result <result.yaml>]
  入口の列挙
    abatlas code-map <repo> [--check] [--json]                         固定コミットのファイルを列挙。`--check` は入口の定義ファイルを再列挙結果と照合する
    abatlas enumerate <entry-list.yaml> [--profile <profile.yaml>] [--dry-run]
      --dry-run は、一覧を書かずに、候補を 1 行 1 件 (id、階層パス、層、抽出器、状態。タブ区切り) で出す
    abatlas extractors [<名前>]                                        コア同梱の抽出器の一覧。名前を渡すと、その params の全項目
    abatlas code-search <work-definition.yaml> --language <言語> --files <glob>... (--pattern <コードの形> | --rule <JSON か @file>) [--exclude <glob>...] [--limit 200]
      対象のコードを構文で探し、一致した場所を「ファイル:行: 1 行目」で出す (入口を見つけるときに、その場で調べる用。一覧は変えない)
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
from .validate import (
    validate_entry_list,
    validate_profile,
    validate_result_file,
    validate_review,
    validate_work_definition,
)


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
        if not isinstance(ex.code, str):
            raise
        why = str(ex)
    except Exception as ex:  # 作業定義が読めない・形が違う
        return None, f"作業定義を読めない: {ex}"
    try:
        prof = load_yaml(repo / "analysis" / "work-definition.yaml")["profile"]
        rel, pid = prof.get("dir"), prof["id"]
    except Exception as ex:
        return None, f"作業定義を読めない: {ex}"
    bundled = REPO_ROOT / "profiles" / str(pid) / "profile.yaml"
    in_bundle = repo.resolve().is_relative_to(
        (REPO_ROOT / "examples").resolve()
    )  # 公開の見本の置き場だけ (checkout の中でも、spike/ などの普通の分析リポジトリは対象外)
    if (
        in_bundle
        and isinstance(rel, str)
        and Path(rel).parts[:1] == (OSS_DIR,)
        and not (repo / OSS_DIR).exists()
        and bundled.exists()
    ):
        return (
            bundled,
            f"配布物の中の見本で、分析リポジトリとして初期化していない ({OSS_DIR}/ が無い) ので、配布物のプロファイル",
        )
    return None, why


def _profile_path(given: str | None, near: Path) -> Path | None:
    """検査と列挙が読むプロファイル。集計 (build) が読むのと同じファイルに揃える。near = 検査するファイル (ファイルごとに決める)。

    --profile が無ければ、near の分析リポジトリの作業定義から読む。読めないときは、その旨を出してプロファイルとの突き合わせを省く (黙って省かない)。
    --profile があればそれを使う。集計が読むものと違うときは、警告する。
    """
    repo = _analysis_repo(near)
    resolved, why = (
        (
            None,
            "分析リポジトリの外か、そのファイルを含む analysis/ に work-definition.yaml が無い",
        )
        if repo is None
        else _resolve_profile(repo)
    )
    if given:
        path = Path(given)
        if resolved is not None and path.resolve() != resolved.resolve():
            _say(
                f"warning: --profile {given} は、{repo} の集計 (build) が読むプロファイル {resolved} と違う。作業定義の profile.dir と揃える"
            )
        return path
    if resolved is None:
        _say(
            f"note: プロファイルを自動で読めないので、プロファイルとの突き合わせを省く ({why})。--profile で渡す"
        )
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


def _validate_path(a, path):
    if a.kind == "profile":
        return validate_profile(load_yaml(path))
    if a.kind == "work":
        return validate_work_definition(load_yaml(path))
    if a.kind == "entries":
        pp = _profile_path(a.profile, path)
        return validate_entry_list(load_yaml(path), load_yaml(pp) if pp else None)
    if a.kind == "review":
        try:
            review = load_yaml(path)
        except Exception as ex:
            return [f"yaml: 読めない: {ex}"]
        res = load_yaml(Path(a.result)) if a.result else None
        return validate_review(review, res)
    return validate_result_file(
        path, _profile_path(a.profile, path), Path(a.work) if a.work else None
    )


def _run_validate(a):
    rc = 0
    for p in a.paths:
        rc |= _report(p, _validate_path(a, Path(p)))
    return rc


def _run_enumerate(a):
    out = enumerate_entries(
        Path(a.entry_list),
        _profile_path(a.profile, Path(a.entry_list)),
        write=not a.dry_run,
    )
    if a.dry_run:  # 一覧を書かないので、候補をここに出す (件数だけでは、漏れや重複を確かめられない)
        for e in out["entries"]:
            print(
                f"{e['id']}\t{e['path']}\t{e['layer']}\t{e.get('extractor', '')}\t{e['status']}"
            )
    return 0


def _run_code_map(a):
    import json

    from . import analysis_dir
    from .code_map import code_map, format_code_map, reconcile_entries
    from .impact import enumerate_at_target, read_work
    from .impact_git import TargetHistory

    repo = Path(a.repo).resolve()
    work = read_work(repo)
    history = TargetHistory(work["target"], analysis_dir(repo))
    patterns = work.get("analysis", {}).get("entry_file_patterns", [])
    report = code_map(history, patterns)
    if a.check:
        if not patterns:
            raise SystemExit(
                "code-map: 照合するには作業定義に analysis.entry_file_patterns を指定してください"
            )
        _, entries = enumerate_at_target(repo, work, history)
        report.update(reconcile_entries(report, entries["entries"]))
    print(
        json.dumps(report, ensure_ascii=False, indent=2)
        if a.json
        else format_code_map(report)
    )
    return int(bool(report.get("missing_entry_files")))


def _run_extractors(a):
    import importlib

    from .enumerate import CORE_EXTRACTORS

    if a.kind is None:
        print(
            "コア同梱の抽出器: "
            + ", ".join(sorted(CORE_EXTRACTORS))
            + " (abatlas extractors <名前> で、params の全項目を出す)"
        )
    elif a.kind not in CORE_EXTRACTORS:
        raise SystemExit(
            f"extractors: '{a.kind}' は、コア同梱の抽出器に無い ({', '.join(sorted(CORE_EXTRACTORS))})"
        )
    else:
        print(
            (importlib.import_module(CORE_EXTRACTORS[a.kind][-1]).__doc__ or "").strip()
        )
    return 0


def _run_code_search(a):
    import json

    import yaml

    from .extractors.ast_query import search
    from .validate import _resolve_scope

    if bool(a.pattern) == bool(a.rule):
        raise SystemExit("code-search: --pattern か --rule の、どちらか 1 つを渡す")
    if a.pattern:
        rule = {"pattern": a.pattern}
    elif a.rule.startswith("@"):
        rule = yaml.safe_load(Path(a.rule[1:]).read_text(encoding="utf-8"))
    else:
        try:
            rule = json.loads(a.rule)
        except json.JSONDecodeError as ex:
            raise SystemExit(f"code-search: --rule を JSON として読めない: {ex}")
    work_path = Path(a.work)
    scope = _resolve_scope(load_yaml(work_path)["target"], work_path.parent)
    if scope is None or not scope.is_dir():
        raise SystemExit(
            f"code-search: {a.work} の target.clone_path/scope が見つからない: {scope}"
        )
    print("\n".join(search(scope, a.files, a.exclude, a.language, rule, a.limit)))
    return 0


# 分析リポジトリに配られる、使う人の手引きの入口 (layout.OSS_REFERENCE_ITEMS の docs/guide)
GUIDE_PATH = ".abatlas/docs/guide/README.md"


def _run_init(a):
    from .layout import init_repo

    for line in init_repo(Path(a.repo), a.profile, a.targets):
        print(f"  + {line}")
    print(
        f"init: {a.repo} (profile {a.profile})。次: .env の ABATLAS_TARGET と analysis/work-definition.yaml を埋めて "
        "`docker compose run --rm abatlas validate work analysis/work-definition.yaml`"
    )
    print(f"手引き (段階ごとに、人がやることと手に入るもの): {GUIDE_PATH}")
    return 0


def _run_upgrade(a):
    from .layout import upgrade_repo

    placed = upgrade_repo(Path(a.repo))
    print("upgrade: 置き換えた " + ", ".join(placed) + " / 製品別 adapter を再生成した")
    print(f"手引き (場面ごとの手順): {GUIDE_PATH}")
    return 0


def _run_migrate(a):
    from .migrate import migrate_repo

    lines, rc = migrate_repo(Path(a.repo), a.dry_run)
    print("\n".join(lines))
    return rc


def _run_dictionary(a):
    from .dictionary import update_dictionary

    rep = update_dictionary(Path(a.repo), a.dry_run)
    print("dictionary: " + ", ".join(f"{k}={v}" for k, v in rep.items()))
    return 0


def _run_impact(a):
    from .impact import confirm, format_plan, plan
    import json

    report, context = plan(Path(a.repo), a.rev)
    if a.command == "reuse":
        confirm(report, context, a.entry, a.plan_id, a.reason, a.by)
        print(f"再利用を確認: {a.entry}")
    elif a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_plan(report))
    return 0


def _run_batch(a):
    import json
    from .batch import approve, preview, queue
    from .impact import LABEL

    repo = Path(a.repo)
    if a.cmd == "queue":
        out = {"plan_id": a.plan_id, "jobs": queue(repo, a.plan_id)}
    elif a.cmd == "approve":
        receipt = approve(repo, a.rev, load_yaml(Path(a.draft)), a.plan_id, a.by)
        out = {
            "plan_id": receipt["plan_id"],
            "jobs": receipt["jobs"],
            "reused": len(receipt["reuse"]),
        }
    else:
        out, _, _ = preview(repo, a.rev, load_yaml(Path(a.draft)))
    if a.cmd == "propose" and not a.json:
        print(f"計画 ID　{out['plan_id']}\n{out['assessment']}")
        print("　".join(f"{LABEL[k]} {n} 件" for k, n in out["counts"].items()))
        print(f"要確認 {len(out['questions'])} 件")
        for q in out["questions"]:
            print(f"  {q['question']} ({', '.join(q['entries'])})")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _run_diff(a):
    from .diff import diff_repo

    print(diff_repo(Path(a.repo), a.rev))
    return 0


def _run_etl(a):
    prof_path, _ = _resolve_profile(
        Path(a.analysis_repo).resolve().parent
    )  # 集計 (build) と同じプロファイルで検査する。読めなければ、プロファイルとの突き合わせを省く
    counts = run_etl(
        Path(a.analysis_repo),
        Path(a.out),
        load_yaml(prof_path) if prof_path else None,
    )
    print("etl: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


def _run_build(a):
    from .build import build_repo

    rep = build_repo(Path(a.repo), a.select)
    print("build: " + ", ".join(f"{k}={v}" for k, v in rep.items()))
    return 0


def _run_serve(a):
    from .api import serve

    serve(Path(a.repo), a.host, a.port)
    return 0


def _run_mcp(a):
    from .mcp_server import run

    run(a.api)
    return 0


def _run_evaluate(a):
    from .evaluate import main_cli

    return main_cli(a.results, a.truth, a.json)


def _batch_parsers(sub):
    proposal = sub.add_parser("propose", help="入口と作業の全体案を確認する")
    approval = sub.add_parser("approve", help="今回の案を一度で承認する")
    queue = sub.add_parser("queue", help="承認済みの未完了作業を表示する")
    for task in (proposal, approval, queue):
        task.set_defaults(handler=_run_batch)
        task.add_argument("repo")
    for task in (proposal, approval):
        source = task.add_mutually_exclusive_group(required=True)
        source.add_argument("--from", dest="rev", help="前回の分析リポジトリの版")
        source.add_argument("--initial", action="store_true", help="初回の分析")
        task.add_argument("--draft", required=True, help="AIの下書き YAML")
    for task in (approval, queue):
        task.add_argument("--plan-id", required=True)
    approval.add_argument("--by", required=True, help="全体を承認した人")
    proposal.add_argument("--json", action="store_true")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="abatlas",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="機械チェック")
    v.set_defaults(handler=_run_validate)
    v.add_argument("kind", choices=["profile", "work", "entries", "result", "review"])
    v.add_argument("paths", nargs="+")
    v.add_argument("--profile")
    v.add_argument("--work")
    v.add_argument("--result")

    cm = sub.add_parser("code-map", help="固定コミットから対象ファイルの地図を作る")
    cm.set_defaults(handler=_run_code_map)
    cm.add_argument("repo")
    cm.add_argument(
        "--check", action="store_true", help="定義ファイルと再列挙した入口を照合する"
    )
    cm.add_argument("--json", action="store_true")

    e = sub.add_parser("enumerate", help="抽出器を実行して入口の候補を一覧に書く")
    e.set_defaults(handler=_run_enumerate)
    e.add_argument("entry_list")
    e.add_argument("--profile")
    e.add_argument("--dry-run", action="store_true")

    xs = sub.add_parser(
        "extractors", help="コア同梱の抽出器の一覧と、params の全項目を出す"
    )
    xs.set_defaults(handler=_run_extractors)
    xs.add_argument("kind", nargs="?")

    cs = sub.add_parser(
        "code-search", help="対象のコードを構文で探す (ast-grep の規則)"
    )
    cs.set_defaults(handler=_run_code_search)
    cs.add_argument(
        "work", help="作業定義 (analysis/work-definition.yaml)。対象の場所と範囲を読む"
    )
    cs.add_argument("--language", required=True)
    cs.add_argument(
        "--files", required=True, nargs="+", help="glob (対象の範囲からの相対)"
    )
    cs.add_argument("--exclude", nargs="*", default=[])
    cs.add_argument("--pattern", help="コードの形 (ast-grep の pattern。穴は $NAME)")
    cs.add_argument(
        "--rule", help="ast-grep の規則。JSON 文字列か、@path で JSON / YAML ファイル"
    )
    cs.add_argument("--limit", type=int, default=200)

    from .layout import DEFAULT_TARGETS

    i = sub.add_parser(
        "init", help="分析リポジトリを初期化する (OSS 所有の配置 + 対象層 + 中ハーネス)"
    )
    i.set_defaults(handler=_run_init)
    i.add_argument("repo")
    i.add_argument("--profile", required=True, help="プロファイル id (profiles/<id>)")
    i.add_argument(
        "--targets",
        default=DEFAULT_TARGETS,
        help=f"mid-harness の対象製品 (カンマ区切り。既定: {DEFAULT_TARGETS})",
    )

    u = sub.add_parser(
        "upgrade", help="OSS 所有のパスだけ置き換えて adapter を再生成する"
    )
    u.set_defaults(handler=_run_upgrade)
    u.add_argument("repo")

    mg = sub.add_parser(
        "migrate",
        help="分析する側の資産の項目名を、いまの形式に書き換える (値は変えない。文の中の「(tier: <id>)」だけ「(layer: <id>)」に直す)",
    )
    mg.set_defaults(handler=_run_migrate)
    mg.add_argument("repo")
    mg.add_argument(
        "--dry-run",
        action="store_true",
        help="書き換えずに、書き換わるファイルと、書き換えられないファイルを出す",
    )

    dc = sub.add_parser(
        "dictionary",
        help="分析結果に出てきた列を、データの辞書 (analysis/data-dictionary.yaml) に candidate で足す (区分は決めない)",
    )
    dc.set_defaults(handler=_run_dictionary)
    dc.add_argument("repo")
    dc.add_argument("--dry-run", action="store_true", help="書かずに、数だけ出す")

    _batch_parsers(sub)

    for name, help_text in (
        ("impact", "対象 Git の変更から理由付きの作業一覧を出す"),
        ("reuse", "確認した入口の再利用を記録する"),
    ):
        task = sub.add_parser(name, help=help_text)
        task.set_defaults(handler=_run_impact, command=name)
        task.add_argument("repo")
        task.add_argument(
            "--from", dest="rev", required=True, help="前回の分析リポジトリのコミット"
        )
        if name == "impact":
            task.add_argument("--json", action="store_true")
        else:
            task.add_argument("--entry", required=True)
            task.add_argument("--plan-id", required=True)
            task.add_argument("--reason", required=True)
            task.add_argument("--by", required=True)

    df = sub.add_parser(
        "diff",
        help="分析リポジトリの git の版にある前の分析結果と、いまの分析結果を比べる (入口ごとに、足されたものと消えたもの)",
    )
    df.set_defaults(handler=_run_diff)
    df.add_argument("repo")
    df.add_argument(
        "--from",
        dest="rev",
        required=True,
        help="比べる相手の git の版 (コミット、タグ、HEAD~1 など)",
    )

    t = sub.add_parser(
        "etl", help="entry-list と results/*.yaml を seed CSV に分解する"
    )
    t.set_defaults(handler=_run_etl)
    t.add_argument("analysis_repo")
    t.add_argument("--out", required=True)

    b = sub.add_parser("build", help="ETL → dbt build")
    b.set_defaults(handler=_run_build)
    b.add_argument("repo")
    b.add_argument("--select")

    s = sub.add_parser("serve", help="集計表 API")
    s.set_defaults(handler=_run_serve)
    s.add_argument("repo")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)

    m = sub.add_parser("mcp", help="MCP サーバを stdio で (API は別プロセス)")
    m.set_defaults(handler=_run_mcp)
    m.add_argument("--api", default="http://127.0.0.1:8765")

    ev = sub.add_parser(
        "evaluate", help="分析結果を正解と突き合わせる (ディレクトリかファイル)"
    )
    ev.set_defaults(handler=_run_evaluate)
    ev.add_argument("results")
    ev.add_argument("--truth", required=True)
    ev.add_argument("--json", action="store_true", help="表でなく JSON で出す")

    a = ap.parse_args(argv)
    _said.clear()  # 知らせをまとめるのは、1 回のコマンドの中だけ
    try:
        return a.handler(a)
    except SystemExit as ex:
        if isinstance(ex.code, str):
            print(ex.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
