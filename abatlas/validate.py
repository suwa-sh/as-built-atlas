"""機械チェック。schema 検証に加えて、意味の検査 (層・参照・根拠の実在) を行う。

結果は findings の list。空なら合格。各 finding は "<種別>: <場所>: <内容>" の 1 行。
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re

from . import ANALYSIS_DIR, file_name_collisions, scope_of
from .schemas import load_yaml, schema_errors, vocab, profile_term_problems


def _resolve_scope(work_or_target: dict, base: Path) -> Path | None:
    """target.clone_path + scope を実パスにする。clone_path が無ければ None。

    環境変数 ABATLAS_TARGET_ROOT があれば clone_path の代わりにそれを使う (コンテナでは対象の clone が
    別の場所 /ws/target にマウントされ、ホスト側の clone_path はそのままでは指せないため)。
    """
    root = os.environ.get("ABATLAS_TARGET_ROOT")
    clone = root or work_or_target.get("clone_path")
    if not clone:
        return None
    p = Path(clone)
    if not p.is_absolute():
        # 分析リポジトリでは作業定義も結果も analysis/ の下にある。相対 clone_path の基準はリポジトリのルート (.env の ABATLAS_TARGET と同じ)
        parts = base.resolve().parts
        if ANALYSIS_DIR in parts:
            base = Path(*parts[: len(parts) - 1 - parts[::-1].index(ANALYSIS_DIR)])
        p = (base / p).resolve()
    p = p.resolve()
    scope = (p / work_or_target.get("scope", ".")).resolve()
    try:
        scope.relative_to(p)
    except ValueError:
        raise SystemExit(
            f"target.scope '{work_or_target.get('scope')}' が clone_path の外を指している"
        )
    return scope


def tests_flag_problems(result: dict, frame: dict) -> list[str]:
    """テスト (tests) は、analyzer.tests が true の結果だけが持てる。ETL も同じ検査をする (印が無いと、テストの表から黙って消えるため)。"""
    if frame.get("tests") and not result["analyzer"].get("tests"):
        return [
            "tests: analyzer.tests が true でないのに、テストが書かれている (作業定義の analysis.tests が true のときだけ分析する)"
        ]
    return []


def field_problems(io: dict) -> list[str]:
    """I/O の列 (fields) の検査: 同じ列を 2 回書かない。set_to は、use に write があるときだけ。ETL も同じ検査をする (列の表の行が重ならないように)。"""
    out = []
    names = [fl["name"] for fl in io.get("fields", [])]
    for n in sorted({n for n in names if names.count(n) > 1}):
        out.append(f"fields: 列 '{n}' が 2 回書かれている (使い方は use にまとめる)")
    for fl in io.get("fields", []):
        if "set_to" in fl and "write" not in fl["use"]:
            out.append(
                f"fields/{fl['name']}: set_to は、use に write があるときだけ書ける"
            )
    return out


def kind_ops(kinds: dict, kind: str) -> list[str]:
    """種類ごとに使える操作の id (語彙の並び順)。"""
    return [o["id"] for o in kinds.get(kind, {}).get("ops", [])]


def hierarchy_label_problems(labels: list) -> list[str]:
    """プロファイルの階層ラベルの検査。`名前+` (繰り返す段) は 1 つまで。"""
    problems = []
    if not isinstance(labels, list) or not all(
        isinstance(x, str) and x.strip("+") for x in labels
    ):
        return ["hierarchy.level_labels は空でない文字列の並び"]
    pluses = [i for i, x in enumerate(labels) if x.endswith("+")]
    if len(pluses) > 1:
        problems.append("hierarchy.level_labels: 繰り返す段 (末尾が +) は 1 つまで")
    elif pluses and len(labels) - pluses[0] - 1 > 1:
        problems.append(
            "hierarchy.level_labels: 繰り返す段の後ろに置ける段は 1 つまで (深さが決まらない節に段の名前を付けられないため)"
        )
    return problems


def _check_split_layers(layers, findings):
    for t in layers:
        if "split_from" not in t:
            continue
        if t.get("role") != "entry":
            findings.append(
                f"profile: layers/{t['id']}/split_from: role: entry の層にだけ書ける"
            )
        for s in t["split_from"]:
            src = next((x for x in layers if x["id"] == s), None)
            if src is None:
                findings.append(f"profile: layers/{t['id']}/split_from: 未知の層 '{s}'")
            elif src.get("role", "intermediate") != "intermediate":
                findings.append(
                    f"profile: layers/{t['id']}/split_from: '{s}' は role: {src['role']} の層 (分けられるのは、入口でも boundary でもない層)"
                )


def _check_profile_references(profile, layers, ids, findings):
    kinds = set(vocab("resource-kinds")["kinds"])
    for t in layers:
        for k in t.get("io", []):
            if k not in kinds:
                findings.append(
                    f"profile: layers/{t['id']}/io: 未知のデータの種類 '{k}' (schema/vocab/resource-kinds.yaml)"
                )
    for ex in profile["extractors"]:
        if ex.get("layer") and ex["layer"] not in ids:
            findings.append(
                f"profile: extractors/{ex['name']}: layer '{ex['layer']}' が layers に無い"
            )


def _check_within_layers(profile, layers, findings):
    entry_layers = {t["id"] for t in layers if t.get("role") == "entry"}
    seen_within = set()
    for i, w in enumerate(profile.get("within", [])):
        if w["layer"] not in entry_layers:
            findings.append(
                f"profile: within/{i}: layer '{w['layer']}' は role: entry の層ではない ({sorted(entry_layers)})"
            )
        if w["layer"] in seen_within:
            findings.append(
                f"profile: within/{i}: layer '{w['layer']}' の宣言が重複している"
            )
        seen_within.add(w["layer"])


def _check_review_locations(review, result, findings):
    frame_ids = {f["id"] for f in result["callstack"]}
    for i, f in enumerate(review["findings"]):
        w = f["where"]
        if w.startswith("callstack/"):
            fid = w.split("/")[1]
            # 直した指摘 (resolved) は、指す先のフレームが無くてもよい (「このフレームは要らない」という指摘に従って消すと、指す先が無くなる)
            if (
                fid not in frame_ids
                and f["kind"] != "missing_frame"
                and not f.get("resolved")
            ):
                findings.append(
                    f"review: findings/{i}: where '{w}' のフレーム '{fid}' が結果に無い"
                )


def _check_entry_profile(entry_list, profile, findings):
    layer_ids = {t["id"] for t in profile["layers"]}
    entry_layers = {t["id"] for t in profile["layers"] if t.get("role") == "entry"}
    for ex in entry_list["extractors"]:
        if ex["layer"] not in entry_layers:
            findings.append(
                f"entry-list: extractors/{ex['name']}: layer '{ex['layer']}' は role: entry の層ではない ({sorted(entry_layers)})"
            )
    for e in entry_list["entries"]:
        if e["layer"] not in layer_ids:
            findings.append(
                f"entry-list: entries/{e['id']}: layer '{e['layer']}' がプロファイルに無い"
            )
        elif e["layer"] not in entry_layers:
            findings.append(
                f"entry-list: entries/{e['id']}: layer '{e['layer']}' は role: entry の層ではない"
            )
    if entry_list["profile"]["id"] != profile["id"]:
        findings.append(
            f"entry-list: profile.id '{entry_list['profile']['id']}' がプロファイル '{profile['id']}' と違う"
        )


def _find_roots(frames, findings):
    for f in frames:
        if "caller" not in f:
            findings.append(
                f"callstack/{f['id']}: caller が無い (入口なら caller: null と明示する)"
            )
    roots = [f for f in frames if "caller" in f and f["caller"] is None]
    if len(roots) != 1:
        findings.append(
            f"callstack: caller が null のフレーム (入口) は 1 つであるべきだが {len(roots)} 個"
        )
    return roots


def _check_caller_references(frames, by_id, findings):
    for f in frames:
        c = f.get("caller")
        if c is not None and c not in by_id:
            findings.append(f"callstack/{f['id']}: caller '{c}' が存在しない")
        if c is not None and "call" not in f:
            findings.append(
                f"callstack/{f['id']}: caller があるのに call (呼び出しの主張) が無い"
            )
        if c == f["id"]:
            findings.append(f"callstack/{f['id']}: caller が自分自身")


def _check_reachable_frames(roots, frames, frame_ids, by_id, result, findings):
    root = roots[0]
    if root["layer"] != result["entry"]["layer"]:
        findings.append(
            f"callstack/{root['id']}: 入口フレームの layer '{root['layer']}' が entry.layer '{result['entry']['layer']}' と違う"
        )
    children: dict[str, list[str]] = {fid: [] for fid in by_id}
    for f in frames:
        c = f.get("caller")
        if c in children:
            children[c].append(f["id"])
    reached, stack = set(), [root["id"]]
    while stack:
        cur = stack.pop()
        if cur in reached:
            continue
        reached.add(cur)
        stack.extend(children[cur])
    for fid in frame_ids:
        if fid not in reached:
            findings.append(
                f"callstack/{fid}: 入口から caller を辿って到達できない (循環か、切れた参照)"
            )


def _check_claim(where, claim, reasons, files, findings):
    if claim.get("status") == "unknown":
        r = claim.get("reason")
        if r not in reasons:
            findings.append(
                f"{where}: unknown の reason '{r}' が語彙に無い (schema/vocab/unknown-reasons.yaml)"
            )
    if files is not None:
        for ev in claim.get("evidence", []) or []:
            problem, n = files.check(ev["file"])
            if problem:
                findings.append(f"{where}: 根拠のファイル '{ev['file']}' が{problem}")
            elif n is not None and ev["line"] > n:
                findings.append(
                    f"{where}: 根拠の行 {ev['line']} が '{ev['file']}' の行数 {n} を超えている"
                )


def _check_entry_source(result, files, findings):
    if files is not None:
        problem, n = files.check(result["entry"]["source"]["file"])
        if problem:
            findings.append(
                f"entry/source: ファイル '{result['entry']['source']['file']}' が{problem}"
            )
        elif n is not None and result["entry"]["source"]["line"] > n:
            findings.append(
                f"entry/source: 行 {result['entry']['source']['line']} が行数 {n} を超えている"
            )


def _check_frame_source(f, w, files, findings):
    if files is not None:
        problem, n = files.check(f["source"]["file"])
        if problem:
            findings.append(f"{w}/source: ファイル '{f['source']['file']}' が{problem}")
        elif n is not None and f["source"]["line"] > n:
            findings.append(
                f"{w}/source: 行 {f['source']['line']} が行数 {n} を超えている"
            )


def _check_frame_claims(f, w, check_claim):
    if "call" in f:
        check_claim(f"{w}/call", f["call"])
    if "summary" in f:
        check_claim(f"{w}/summary", f["summary"])
    for i, p in enumerate(f.get("parameters", [])):
        check_claim(f"{w}/parameters/{i}", p)
    for name in ("links", "guards", "settings", "rules", "tests"):
        for i, c in enumerate(f.get(name, [])):
            check_claim(f"{w}/{name}/{i}", c)


def _check_frame_links(f, w, result, entry_ids, findings):
    for i, ln in enumerate(f.get("links", [])):
        if ln.get("kind") == "embed":
            _check_embed_target(ln, w, i, result, findings)
        if (
            entry_ids is not None
            and ln.get("entry_id")
            and ln["entry_id"] not in entry_ids
        ):
            findings.append(
                f"{w}/links/{i}: entry_id '{ln['entry_id']}' が、入口の一覧に無い (rejected の入口も、行き先にできない)"
            )


def _check_embed_target(ln, w, i, result, findings):
    if not ln.get("entry_id"):
        findings.append(
            f"{w}/links/{i}: embed には entry_id が要る (この入口の中に描く部品が、どの入口か。入口になっていない部品は、embed に書かない)"
        )
    # 自分自身への遷移 (保存の後に同じ画面を開き直す) や、自分を起動し直す処理は、ある。自分の中に自分を描くことだけは、無い
    if ln.get("entry_id") and ln["entry_id"] == (result.get("entry") or {}).get("id"):
        findings.append(
            f"{w}/links/{i}: embed の entry_id が、この入口自身を指している (embed は、この入口の中に描く、ほかの入口を書く)"
        )


def _check_resource_vocabulary(kinds, kind, io, iw, findings):
    allowed = set(kinds[kind]["levels"])
    for lv in io["resource"].get("levels", {}):
        if lv not in allowed:
            findings.append(f"{iw}: 段 '{lv}' は {kind} の段 {sorted(allowed)} に無い")
    ops = kind_ops(kinds, kind)
    if io["op"] not in ops:
        findings.append(
            f"{iw}: 操作 '{io['op']}' は {kind} では使えない (使えるのは {ops})"
        )


def _check_within_cycles(entries, by_id, problems):
    for e in entries:
        seen, stack = set(), list(e.get("within", []))
        while stack:
            cur = stack.pop()
            if cur == e["id"]:
                problems.append(
                    f"entry-list: entries/{e['id']}: within を辿ると自分に戻る (循環)"
                )
                break
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(by_id[cur].get("within", []))


def _check_frame_io(f, w, layers, kinds, check_claim, findings):
    layer_io = layers.get(f["layer"], {}).get("io") if layers else None
    for i, io in enumerate(f.get("io", [])):
        iw = f"{w}/io/{i}"
        check_claim(iw, io)
        kind = io["resource"]["kind"]
        if kind not in kinds:
            findings.append(
                f"{iw}: データの種類 '{kind}' が語彙に無い (schema/vocab/resource-kinds.yaml)"
            )
        else:
            _check_resource_vocabulary(kinds, kind, io, iw, findings)
        findings.extend(f"{iw}/{p}" for p in field_problems(io))
        if layer_io is not None and kind not in layer_io:
            findings.append(
                f"{iw}: 層 '{f['layer']}' は io に '{kind}' を宣言していない (プロファイルの layers[].io: {layer_io})"
            )


def _check_frame_layers(result, layers, frames, findings):
    if result["entry"]["layer"] not in layers:
        findings.append(
            f"entry/layer: '{result['entry']['layer']}' がプロファイルに無い"
        )
    elif layers[result["entry"]["layer"]].get("role") != "entry":
        findings.append(
            f"entry/layer: '{result['entry']['layer']}' は role: entry ではない"
        )
    for f in frames:
        if f["layer"] not in layers:
            findings.append(
                f"callstack/{f['id']}/layer: '{f['layer']}' がプロファイルに無い"
            )


def _continues_in_entry(f, result, entry_ids):
    return entry_ids is not None and any(
        ln.get("kind") in ("embed", "trigger")
        and ln.get("entry_id") in entry_ids
        and ln["entry_id"] != result["entry"]["id"]
        and ln.get("status") != "unknown"
        for ln in f.get("links", [])
    )


def _unknown_leaf(f):
    return any(
        (f.get(k) or {}).get("status") == "unknown" for k in ("call", "summary")
    ) or any(p.get("status") == "unknown" for p in f.get("parameters", []))


def _check_leaf_frames(result, frames, layers, entry_ids, findings):
    callers = {f.get("caller") for f in frames}
    for f in frames:
        if f["id"] in callers:
            continue
        layer = layers.get(f["layer"], {})
        if layer.get("role") == "boundary" or any(
            f.get(key) for key in ("io", "rules", "guards")
        ):
            continue  # 業務のルールか、権限の確認を持つフレームは、読み書きも外部の呼び出しも無くても終端になれる (純粋な判定や計算の関数、確認だけをする middleware)
        if _continues_in_entry(f, result, entry_ids):
            continue  # 続きが、別の入口の結果にあるフレーム (別の入口にした部品を描く、別の入口を起動する)。行き先が、入口の一覧にあるものだけ (一覧を渡されない検査では、終端の根拠にしない)
        if not _unknown_leaf(f):
            findings.append(
                f"callstack/{f['id']}: 終端なのに boundary 層でなく、I/O も業務のルールも権限の確認も、行き先が入口の一覧にあるつながり (embed / trigger と entry_id。--work で作業定義を渡すと、隣の入口の一覧と照合する) も、unknown の主張も無い (辿り切れていないなら unknown + reason を書く)"
            )


def _check_work_target(work, result, findings, reused=False):
    wt, rt = work["target"], result["target"]
    for k in ("repo", "commit"):
        if wt.get(k) != rt.get(k) and not (k == "commit" and reused):
            findings.append(
                f"target/{k}: 結果の '{rt.get(k)}' が作業定義の '{wt.get(k)}' と違う"
            )
    if scope_of(wt) != scope_of(rt):
        findings.append(
            f"target/scope: 結果の '{rt.get('scope', '.')}' が作業定義の '{wt.get('scope', '.')}' と違う"
        )


def validate_profile(profile: dict) -> list[str]:
    findings = [f"schema: {e}" for e in schema_errors("profile", profile)]
    if findings:
        return findings
    labels = (profile.get("hierarchy") or {}).get("level_labels")
    if labels is not None:
        findings.extend(f"profile: {p}" for p in hierarchy_label_problems(labels))
    layers = profile["layers"]
    ids = [t["id"] for t in layers]
    if len(ids) != len(set(ids)):
        findings.append("profile: layers: id が重複している")
    roles = [t.get("role", "intermediate") for t in layers]
    if "entry" not in roles:
        findings.append("profile: layers: role: entry の層が無い")
    if "boundary" not in roles:
        findings.append("profile: layers: role: boundary の層が無い")
    _check_split_layers(layers, findings)
    findings.extend(profile_term_problems(profile))
    _check_profile_references(profile, layers, ids, findings)
    _check_within_layers(profile, layers, findings)
    return findings


def within_of(entries: list[dict], profile: dict | None) -> dict[str, list[str]]:
    """プロファイルの within の宣言から、入口ごとの「包む入口の id (外側から)」を決める。決定論 (入口の一覧だけを見る)。

    source_dir: 包む側のソースのファイルと同じフォルダか、その配下にソースのファイルがある入口を包む。
    外側 = フォルダが浅い方。同じ深さなら id 順。
    包む側どうしは、フォルダが深い方だけが浅い方に包まれる。同じフォルダの包む入口は互いを包まない (包み合って循環しないように)。
    """
    rules = {w["layer"]: w["rule"] for w in (profile or {}).get("within", [])}
    wrappers = []
    for e in entries:
        if rules.get(e["layer"]) == "source_dir":
            wrappers.append((tuple(e["source"]["file"].split("/")[:-1]), e["id"]))
    wrappers.sort(key=lambda w: (len(w[0]), w[1]))
    wrapper_ids = {wid for _, wid in wrappers}
    out: dict[str, list[str]] = {}
    for e in entries:
        d = tuple(e["source"]["file"].split("/")[:-1])
        is_wrapper = e["id"] in wrapper_ids
        chain = [
            wid
            for wdir, wid in wrappers
            if wid != e["id"]
            and d[: len(wdir)] == wdir
            and not (is_wrapper and wdir == d)
        ]
        if chain:
            out[e["id"]] = chain
    return out


def within_problems(entries: list[dict], profile: dict | None = None) -> list[str]:
    """entries[].within の検査: 指す入口が実在し、自分を指さず、辿って自分に戻らない。

    profile を渡すと、宣言から決まる値と一致することも見る。within は列挙ツールが埋めるので、
    手で直した・古い一覧のままだと、分析の範囲 (包まれる側は包む側を辿らない) と合わなくなる。
    入口の id は重複していない前提 (呼ぶ側が先に確かめる)。
    """
    problems = _within_ref_problems(entries)
    if problems or profile is None:
        return problems
    expected = within_of(entries, profile)
    for e in entries:
        if e.get("within", []) != expected.get(e["id"], []):
            problems.append(
                f"entry-list: entries/{e['id']}: within {e.get('within', [])} がプロファイルの宣言から決まる {expected.get(e['id'], [])} と違う (enumerate をやり直す)"
            )
    return problems


def rejected_wrappers(entries: list[dict]) -> dict[str, int]:
    """rejected の入口が包んでいる、rejected でない入口の数 (0 は除く)。包む入口を外すと、その処理はどの入口の結果にも現れなくなる。"""
    status = {e["id"]: e["status"] for e in entries}
    out: dict[str, int] = {}
    for e in entries:
        if e["status"] == "rejected":
            continue
        for w in e.get("within", []):
            if status.get(w) == "rejected":
                out[w] = out.get(w, 0) + 1
    return dict(sorted(out.items()))


def _within_ref_problems(entries: list[dict]) -> list[str]:
    problems = []
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        for w in e.get("within", []):
            if w == e["id"]:
                problems.append(
                    f"entry-list: entries/{e['id']}: within が自分自身を指している"
                )
            elif w not in by_id:
                problems.append(
                    f"entry-list: entries/{e['id']}: within の '{w}' が entries に無い"
                )
    if problems:
        return problems
    _check_within_cycles(entries, by_id, problems)
    return problems


def validate_work_definition(work: dict) -> list[str]:
    findings = [f"schema: {e}" for e in schema_errors("work-definition", work)]
    if findings:
        return findings
    for pattern in work.get("analysis", {}).get("entry_file_patterns", []):
        try:
            re.compile(pattern)
        except (re.error, OverflowError) as ex:
            findings.append(
                f"analysis.entry_file_patterns: {pattern!r} を正規表現として読めません。式を直してください ({ex})"
            )
    return findings


def validate_review(review: dict, result: dict | None = None) -> list[str]:
    """レビュー結果の機械チェック。result を渡すと entry_id の一致、結果に記録した「直っていない指摘の数」との一致、where の場所の実在を見る (直した指摘と、フレームの漏れの指摘は、指す先が無くてよい)。"""
    findings = [f"schema: {e}" for e in schema_errors("review", review)]
    if findings or result is None:
        return findings
    if review["entry_id"] != result["entry"]["id"]:
        findings.append(
            f"review: entry_id '{review['entry_id']}' が結果の '{result['entry']['id']}' と違う"
        )
    open_count = sum(1 for f in review["findings"] if not f.get("resolved"))
    recorded = (result["analyzer"].get("reviewed") or {}).get("findings_open")
    if recorded is not None and recorded != open_count:
        findings.append(
            f"review: 結果の analyzer.reviewed.findings_open ({recorded}) が、レビューの直っていない指摘の数 ({open_count}) と違う (直した指摘に resolved: true を書くか、結果の数を直す)"
        )
    _check_review_locations(review, result, findings)
    return findings


def approval_errors(approval):
    from .reuse import digest

    try:
        sealed = digest({k: v for k, v in approval.items() if k != "seal"})
    except TypeError:
        # 項目名に文字列と文字列でないもの (true など) が混ざると、封の計算で項目名を並べられない。
        # 承認の記録は道具が書き、そういう項目名を書かない。手で変えた記録として扱う
        sealed = None
    if sealed != approval["seal"]:
        return [
            "entry-list: approval の確定後に内容が変わりました。承認時の版を復元してください"
        ]
    findings = []
    jobs = [j["entry_id"] for j in approval["jobs"]]
    if len(set(jobs)) != len(jobs) or set(jobs).intersection(approval["reuse"]):
        findings.append(
            "entry-list: approval の実行作業と再利用に同じ入口を重ねないでください"
        )
    for eid, record in approval["reuse"].items():
        if (
            record["entry_id"] != eid
            or record["effective_commit"] != approval["target_commit"]
            or record["confirmed_by"] != approval["by"]
            or record["baseline"] != approval["baseline"]
        ):
            findings.append(
                f"entry-list: approval.reuse の {eid} は全体承認と一致しません"
            )
    return findings


def validate_entry_list(entry_list: dict, profile: dict | None = None) -> list[str]:
    findings = [f"schema: {e}" for e in schema_errors("entry-list", entry_list)]
    if findings:
        return findings
    ids = [e["id"] for e in entry_list["entries"]]
    dup = {i for i in ids if ids.count(i) > 1}
    for d in sorted(dup):
        findings.append(
            f"entry-list: entries: id '{d}' が重複している (抽出器の id が安定していない)"
        )
    for name, group in sorted(file_name_collisions(set(ids)).items()):
        findings.append(
            f"entry-list: entries: id {group} は同じ結果ファイル名 '{name}' になる (`/` は `__` に置き換えるため)。抽出器の id の付け方を変える"
        )
    if approval := entry_list.get("approval"):
        findings.extend(approval_errors(approval))
    if not dup:
        findings.extend(within_problems(entry_list["entries"], profile))
    if profile:
        _check_entry_profile(entry_list, profile, findings)
    return findings


class _ScopeFiles:
    """scope 内のファイルの実在と行数を、scope の外へ出ないように調べる。"""

    def __init__(self, scope_dir: Path):
        self.scope = scope_dir.resolve()

    def check(self, rel: str) -> tuple[str | None, int | None]:
        """(問題, 行数)。問題が無ければ (None, 行数)。"""
        p = (self.scope / rel).resolve()
        try:
            p.relative_to(self.scope)
        except ValueError:
            return ("scope の外を指している", None)
        if not p.is_file():
            return ("scope に無い", None)
        return (None, self._line_count(p))

    @lru_cache(maxsize=4096)
    def _line_count(self, p: Path) -> int:
        with p.open("rb") as fh:
            return sum(1 for _ in fh)


def _check_call_graph(result, frames, findings):
    frame_ids = [f["id"] for f in frames]
    dup = {i for i in frame_ids if frame_ids.count(i) > 1}
    for d in sorted(dup):
        findings.append(f"callstack: frame id '{d}' が重複している")
    by_id = {f["id"]: f for f in frames}

    # --- 呼び出しグラフ: 入口 1 つ、参照の解決、到達可能性、循環
    roots = _find_roots(frames, findings)
    _check_caller_references(frames, by_id, findings)
    if len(roots) == 1 and not dup:
        _check_reachable_frames(roots, frames, frame_ids, by_id, result, findings)


def validate_analysis_result(
    result: dict,
    profile: dict | None = None,
    scope_dir: Path | None = None,
    entry_ids: set[str] | None = None,
) -> list[str]:
    """分析結果 YAML の機械チェック。

    - schema (claim の status と evidence / reason の組み合わせを含む)
    - 入口フレーム (caller: null) がちょうど 1 つで、entry.layer と同じ層、かつ role: entry
    - caller の参照が解決し、全フレームが入口から到達でき、循環が無い
    - 葉のフレームは boundary 層か、I/O か業務のルールを持つか、unknown の主張を持つ
    - unknown の reason が語彙にあるか。データの種類・段の名前・操作 (op) が語彙にあり、層が io を宣言していればその種類に含まれるか
    - つながり・権限の確認・設定・業務のルール・テスト (フレームの links / guards / settings / rules / tests) の主張も、同じ検査を通す
    - I/O の列 (fields) は、同じ名前を 2 回書かない。set_to は、use に write があるときだけ
    - テスト (tests) は、analyzer.tests が true の結果だけが持てる
    - 根拠のファイルが scope 内に実在し、行番号が行数を超えないか (scope_dir を渡したときだけ)

    層の順序 (連鎖の向き) は検査しない: program → shell のような逆向きの呼び出しは実在する。
    """
    findings = [f"schema: {e}" for e in schema_errors("analysis-result", result)]
    if findings:
        return findings

    reasons = set(vocab("unknown-reasons")["reasons"])
    kinds = vocab("resource-kinds")["kinds"]
    files = _ScopeFiles(scope_dir) if scope_dir is not None else None
    frames = result["callstack"]
    _check_call_graph(result, frames, findings)

    def check_claim(where: str, claim: dict):
        _check_claim(where, claim, reasons, files, findings)

    layers = {t["id"]: t for t in profile["layers"]} if profile else {}
    check_claim("summary", result["summary"])
    _check_entry_source(result, files, findings)
    for f in frames:
        w = f"callstack/{f['id']}"
        _check_frame_source(f, w, files, findings)
        _check_frame_claims(f, w, check_claim)
        _check_frame_links(f, w, result, entry_ids, findings)
        if f.get("caller") is None and (f.get("call") or {}).get("when"):
            findings.append(
                f"{w}/call: 入口のフレームは呼び出し元が無いので、when を書けない"
            )
        findings.extend(f"{w}/{p}" for p in tests_flag_problems(result, f))
        _check_frame_io(f, w, layers, kinds, check_claim, findings)

    if profile:
        _check_frame_layers(result, layers, frames, findings)
        # 葉 (誰からも呼ばれないフレーム) は、boundary 層か、I/O を持つか、unknown の主張を持つべき。
        _check_leaf_frames(result, frames, layers, entry_ids, findings)
    return findings


def entry_ids_of(entry_list: dict | None) -> set[str] | None:
    """つながりの行き先にできる入口の id (rejected を除く)。一覧が無ければ None。"""
    if not isinstance(entry_list, dict):
        return None
    return {
        e["id"]
        for e in entry_list.get("entries", [])
        if isinstance(e, dict) and e.get("id") and e.get("status") != "rejected"
    }


def _entry_ids(path: Path) -> set[str] | None:
    return entry_ids_of(load_yaml(path)) if path.is_file() else None


def _check_result_version(work_path, work, result, profile_path, findings):
    reused = False
    if not findings and work["target"]["commit"] != result["target"]["commit"]:
        from .reuse import verified_result

        reused = verified_result(work_path.parent, work, result, profile_path)
        if reused:
            import sys

            print(
                f"{result['entry']['id']}: 再利用を確認 ({work['target']['commit']})",
                file=sys.stderr,
            )
    _check_work_target(work, result, findings, reused)


def validate_result_file(
    path: Path, profile_path: Path | None = None, work_path: Path | None = None
) -> list[str]:
    return validate_result_at(load_yaml(path), path, profile_path, work_path)


def validate_result_at(result, path, profile_path, work_path):
    profile = load_yaml(profile_path) if profile_path else None
    has_target = isinstance(result, dict) and isinstance(result.get("target"), dict)
    scope_dir = None
    if work_path:
        work = load_yaml(work_path)
        scope_dir = _resolve_scope(work["target"], work_path.parent)
    elif has_target:
        scope_dir = _resolve_scope(result["target"], path.parent)
    findings = validate_analysis_result(
        result,
        profile,
        scope_dir,
        _entry_ids(work_path.parent / "entry-list.yaml") if work_path else None,
    )
    if work_path and has_target:
        _check_result_version(work_path, work, result, profile_path, findings)
    if scope_dir is None:
        findings.append(
            "scope: target.clone_path が無く、根拠の実在を検査していない (--work で作業定義を渡す)"
        )
    elif not scope_dir.is_dir():
        findings.append(f"scope: '{scope_dir}' が無く、根拠の実在を検査できない")
    return findings
