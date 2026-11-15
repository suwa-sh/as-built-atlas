"""機械チェック。schema 検証に加えて、意味の検査 (層・参照・根拠の実在) を行う。

結果は findings の list。空なら合格。各 finding は "<種別>: <場所>: <内容>" の 1 行。
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from . import ANALYSIS_DIR, file_name_collisions
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
        raise SystemExit(f"target.scope '{work_or_target.get('scope')}' が clone_path の外を指している")
    return scope


def kind_ops(kinds: dict, kind: str) -> list[str]:
    """種類ごとに使える操作の id (語彙の並び順)。"""
    return [o["id"] for o in kinds.get(kind, {}).get("ops", [])]


def hierarchy_label_problems(labels: list) -> list[str]:
    """プロファイルの階層ラベルの検査。`名前+` (繰り返す段) は 1 つまで。"""
    problems = []
    if not isinstance(labels, list) or not all(isinstance(x, str) and x.strip("+") for x in labels):
        return ["hierarchy.level_labels は空でない文字列の並び"]
    pluses = [i for i, x in enumerate(labels) if x.endswith("+")]
    if len(pluses) > 1:
        problems.append("hierarchy.level_labels: 繰り返す段 (末尾が +) は 1 つまで")
    elif pluses and len(labels) - pluses[0] - 1 > 1:
        problems.append("hierarchy.level_labels: 繰り返す段の後ろに置ける段は 1 つまで (深さが決まらない節に段の名前を付けられないため)")
    return problems


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
    findings.extend(profile_term_problems(profile))
    kinds = set(vocab("resource-kinds")["kinds"])
    for t in layers:
        for k in t.get("io", []):
            if k not in kinds:
                findings.append(f"profile: layers/{t['id']}/io: 未知のデータの種類 '{k}' (schema/vocab/resource-kinds.yaml)")
    for ex in profile["extractors"]:
        if ex.get("layer") and ex["layer"] not in ids:
            findings.append(f"profile: extractors/{ex['name']}: layer '{ex['layer']}' が layers に無い")
    entry_layers = {t["id"] for t in layers if t.get("role") == "entry"}
    seen_within = set()
    for i, w in enumerate(profile.get("within", [])):
        if w["layer"] not in entry_layers:
            findings.append(f"profile: within/{i}: layer '{w['layer']}' は role: entry の層ではない ({sorted(entry_layers)})")
        if w["layer"] in seen_within:
            findings.append(f"profile: within/{i}: layer '{w['layer']}' の宣言が重複している")
        seen_within.add(w["layer"])
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
        chain = [wid for wdir, wid in wrappers if wid != e["id"] and d[: len(wdir)] == wdir and not (is_wrapper and wdir == d)]
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
            problems.append(f"entry-list: entries/{e['id']}: within {e.get('within', [])} がプロファイルの宣言から決まる {expected.get(e['id'], [])} と違う (enumerate をやり直す)")
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
                problems.append(f"entry-list: entries/{e['id']}: within が自分自身を指している")
            elif w not in by_id:
                problems.append(f"entry-list: entries/{e['id']}: within の '{w}' が entries に無い")
    if problems:
        return problems
    for e in entries:
        seen, stack = set(), list(e.get("within", []))
        while stack:
            cur = stack.pop()
            if cur == e["id"]:
                problems.append(f"entry-list: entries/{e['id']}: within を辿ると自分に戻る (循環)")
                break
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(by_id[cur].get("within", []))
    return problems


def validate_work_definition(work: dict) -> list[str]:
    return [f"schema: {e}" for e in schema_errors("work-definition", work)]


def validate_review(review: dict, result: dict | None = None) -> list[str]:
    """レビュー結果の機械チェック。result を渡すと entry_id の一致と where の場所の実在を見る。"""
    findings = [f"schema: {e}" for e in schema_errors("review", review)]
    if findings or result is None:
        return findings
    if review["entry_id"] != result["entry"]["id"]:
        findings.append(f"review: entry_id '{review['entry_id']}' が結果の '{result['entry']['id']}' と違う")
    frame_ids = {f["id"] for f in result["callstack"]}
    for i, f in enumerate(review["findings"]):
        w = f["where"]
        if w.startswith("callstack/"):
            fid = w.split("/")[1]
            if fid not in frame_ids and f["kind"] != "missing_frame":
                findings.append(f"review: findings/{i}: where '{w}' のフレーム '{fid}' が結果に無い")
    return findings


def validate_entry_list(entry_list: dict, profile: dict | None = None) -> list[str]:
    findings = [f"schema: {e}" for e in schema_errors("entry-list", entry_list)]
    if findings:
        return findings
    ids = [e["id"] for e in entry_list["entries"]]
    dup = {i for i in ids if ids.count(i) > 1}
    for d in sorted(dup):
        findings.append(f"entry-list: entries: id '{d}' が重複している (抽出器の id が安定していない)")
    for name, group in sorted(file_name_collisions(set(ids)).items()):
        findings.append(f"entry-list: entries: id {group} は同じ結果ファイル名 '{name}' になる (`/` は `__` に置き換えるため)。抽出器の id の付け方を変える")
    if not dup:
        findings.extend(within_problems(entry_list["entries"], profile))
    if profile:
        layer_ids = {t["id"] for t in profile["layers"]}
        entry_layers = {t["id"] for t in profile["layers"] if t.get("role") == "entry"}
        for ex in entry_list["extractors"]:
            if ex["layer"] not in entry_layers:
                findings.append(f"entry-list: extractors/{ex['name']}: layer '{ex['layer']}' は role: entry の層ではない ({sorted(entry_layers)})")
        for e in entry_list["entries"]:
            if e["layer"] not in layer_ids:
                findings.append(f"entry-list: entries/{e['id']}: layer '{e['layer']}' がプロファイルに無い")
            elif e["layer"] not in entry_layers:
                findings.append(f"entry-list: entries/{e['id']}: layer '{e['layer']}' は role: entry の層ではない")
        if entry_list["profile"]["id"] != profile["id"]:
            findings.append(f"entry-list: profile.id '{entry_list['profile']['id']}' がプロファイル '{profile['id']}' と違う")
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


def validate_analysis_result(result: dict, profile: dict | None = None, scope_dir: Path | None = None) -> list[str]:
    """分析結果 YAML の機械チェック。

    - schema (claim の status と evidence / reason の組み合わせを含む)
    - 入口フレーム (caller: null) がちょうど 1 つで、entry.layer と同じ層、かつ role: entry
    - caller の参照が解決し、全フレームが入口から到達でき、循環が無い
    - 葉のフレームは boundary 層か、I/O を持つか、unknown の主張を持つ
    - unknown の reason が語彙にあるか。データの種類・段の名前・操作 (op) が語彙にあり、層が io を宣言していればその種類に含まれるか
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
    frame_ids = [f["id"] for f in frames]
    dup = {i for i in frame_ids if frame_ids.count(i) > 1}
    for d in sorted(dup):
        findings.append(f"callstack: frame id '{d}' が重複している")
    by_id = {f["id"]: f for f in frames}

    # --- 呼び出しグラフ: 入口 1 つ、参照の解決、到達可能性、循環
    for f in frames:
        if "caller" not in f:
            findings.append(f"callstack/{f['id']}: caller が無い (入口なら caller: null と明示する)")
    roots = [f for f in frames if "caller" in f and f["caller"] is None]
    if len(roots) != 1:
        findings.append(f"callstack: caller が null のフレーム (入口) は 1 つであるべきだが {len(roots)} 個")
    for f in frames:
        c = f.get("caller")
        if c is not None and c not in by_id:
            findings.append(f"callstack/{f['id']}: caller '{c}' が存在しない")
        if c is not None and "call" not in f:
            findings.append(f"callstack/{f['id']}: caller があるのに call (呼び出しの主張) が無い")
        if c == f["id"]:
            findings.append(f"callstack/{f['id']}: caller が自分自身")
    if len(roots) == 1 and not dup:
        root = roots[0]
        if root["layer"] != result["entry"]["layer"]:
            findings.append(f"callstack/{root['id']}: 入口フレームの layer '{root['layer']}' が entry.layer '{result['entry']['layer']}' と違う")
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
                findings.append(f"callstack/{fid}: 入口から caller を辿って到達できない (循環か、切れた参照)")

    def check_claim(where: str, claim: dict):
        if claim.get("status") == "unknown":
            r = claim.get("reason")
            if r not in reasons:
                findings.append(f"{where}: unknown の reason '{r}' が語彙に無い (schema/vocab/unknown-reasons.yaml)")
        if files is not None:
            for ev in claim.get("evidence", []) or []:
                problem, n = files.check(ev["file"])
                if problem:
                    findings.append(f"{where}: 根拠のファイル '{ev['file']}' が{problem}")
                elif n is not None and ev["line"] > n:
                    findings.append(f"{where}: 根拠の行 {ev['line']} が '{ev['file']}' の行数 {n} を超えている")

    layers = {t["id"]: t for t in profile["layers"]} if profile else {}
    check_claim("summary", result["summary"])
    if files is not None:
        problem, n = files.check(result["entry"]["source"]["file"])
        if problem:
            findings.append(f"entry/source: ファイル '{result['entry']['source']['file']}' が{problem}")
        elif n is not None and result["entry"]["source"]["line"] > n:
            findings.append(f"entry/source: 行 {result['entry']['source']['line']} が行数 {n} を超えている")
    for f in frames:
        w = f"callstack/{f['id']}"
        if files is not None:
            problem, n = files.check(f["source"]["file"])
            if problem:
                findings.append(f"{w}/source: ファイル '{f['source']['file']}' が{problem}")
            elif n is not None and f["source"]["line"] > n:
                findings.append(f"{w}/source: 行 {f['source']['line']} が行数 {n} を超えている")
        if "call" in f:
            check_claim(f"{w}/call", f["call"])
        if "summary" in f:
            check_claim(f"{w}/summary", f["summary"])
        for i, p in enumerate(f.get("parameters", [])):
            check_claim(f"{w}/parameters/{i}", p)
        layer_io = layers.get(f["layer"], {}).get("io") if layers else None
        for i, io in enumerate(f.get("io", [])):
            iw = f"{w}/io/{i}"
            check_claim(iw, io)
            kind = io["resource"]["kind"]
            if kind not in kinds:
                findings.append(f"{iw}: データの種類 '{kind}' が語彙に無い (schema/vocab/resource-kinds.yaml)")
            else:
                allowed = set(kinds[kind]["levels"])
                for lv in io["resource"].get("levels", {}):
                    if lv not in allowed:
                        findings.append(f"{iw}: 段 '{lv}' は {kind} の段 {sorted(allowed)} に無い")
                ops = kind_ops(kinds, kind)
                if io["op"] not in ops:
                    findings.append(f"{iw}: 操作 '{io['op']}' は {kind} では使えない (使えるのは {ops})")
            if layer_io is not None and kind not in layer_io:
                findings.append(f"{iw}: 層 '{f['layer']}' は io に '{kind}' を宣言していない (プロファイルの layers[].io: {layer_io})")

    if profile:
        if result["entry"]["layer"] not in layers:
            findings.append(f"entry/layer: '{result['entry']['layer']}' がプロファイルに無い")
        elif layers[result["entry"]["layer"]].get("role") != "entry":
            findings.append(f"entry/layer: '{result['entry']['layer']}' は role: entry ではない")
        for f in frames:
            if f["layer"] not in layers:
                findings.append(f"callstack/{f['id']}/layer: '{f['layer']}' がプロファイルに無い")
        # 葉 (誰からも呼ばれないフレーム) は、boundary 層か、I/O を持つか、unknown の主張を持つべき。
        callers = {f.get("caller") for f in frames}
        for f in frames:
            if f["id"] in callers:
                continue
            layer = layers.get(f["layer"], {})
            if layer.get("role") == "boundary" or f.get("io"):
                continue
            unknown_leaf = any((f.get(k) or {}).get("status") == "unknown" for k in ("call", "summary")) or any(
                p.get("status") == "unknown" for p in f.get("parameters", [])
            )
            if not unknown_leaf:
                findings.append(
                    f"callstack/{f['id']}: 終端なのに boundary 層でなく、I/O も unknown の主張も無い (辿り切れていないなら unknown + reason を書く)"
                )
    return findings


def validate_result_file(path: Path, profile_path: Path | None = None, work_path: Path | None = None) -> list[str]:
    result = load_yaml(path)
    profile = load_yaml(profile_path) if profile_path else None
    scope_dir = None
    if work_path:
        work = load_yaml(work_path)
        scope_dir = _resolve_scope(work["target"], work_path.parent)
    elif isinstance(result, dict) and isinstance(result.get("target"), dict):
        scope_dir = _resolve_scope(result["target"], path.parent)
    findings = validate_analysis_result(result, profile, scope_dir)
    if work_path and isinstance(result, dict) and isinstance(result.get("target"), dict):
        wt, rt = work["target"], result["target"]
        for k in ("repo", "commit"):
            if wt.get(k) != rt.get(k):
                findings.append(f"target/{k}: 結果の '{rt.get(k)}' が作業定義の '{wt.get(k)}' と違う")
        if wt.get("scope", ".") != rt.get("scope", "."):
            findings.append(f"target/scope: 結果の '{rt.get('scope', '.')}' が作業定義の '{wt.get('scope', '.')}' と違う")
    if scope_dir is None:
        findings.append("scope: target.clone_path が無く、根拠の実在を検査していない (--work で作業定義を渡す)")
    elif not scope_dir.is_dir():
        findings.append(f"scope: '{scope_dir}' が無く、根拠の実在を検査できない")
    return findings
