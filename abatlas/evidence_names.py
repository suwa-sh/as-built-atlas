"""根拠の行の近くに、主張した名前が見つからない主張を並べる。合否は付けない。

機械チェック (validate result) は、根拠のファイルがあるかと、行番号が行数を超えないかだけを見る。
ここでは、根拠の行の前後を読み、主張が名指しするもの (呼び先、読み書きの相手、設定) の名前が出てくるかを見る。
正しい主張でも名前が近くに無いことはある (接続先の設定から来る名前、実行時に組み立てる名前)。
並んだ主張は、分析する側が根拠を直すか理由を説明し、レビューが先に確かめる。
"""

from __future__ import annotations

from pathlib import Path
import re

from .schemas import vocab

WINDOW = 5  # 根拠の行の前後に読む行数
MIN_WORD = 3  # これより短い語は探さない (どの行にもあるため)
# 語は ASCII の英数字と _ だけ (re.ASCII。付けないと \w が日本語にも一致し、説明の文が語になる)
_WORD = re.compile(r"\w+", re.ASCII)
_HOLE = re.compile(
    r"\{[^{}]*\}"
)  # 読み書きの相手の名前の、実行時に決まる部分 ({sku} など)


def _words(text: str) -> list[str]:
    seen = dict.fromkeys(w for w in _WORD.findall(text) if len(w) >= MIN_WORD)
    return list(seen)


def _callee_words(frame: dict) -> list[str]:
    """呼び先を名指しする語。処理の段のファイル名 (拡張子を除く) と、名前の中の語。"""
    # その OS の読み方でファイル名を取る (Windows の区切りで書かれたパスの、親フォルダの名前を語にしない)
    stem = Path(frame["source"]["file"]).stem
    return list(dict.fromkeys([*_words(stem), *_words(frame["name"])]))


def _resource_words(io: dict) -> list[str]:
    """読み書きの相手を名指しする語。書かれた段のうち、いちばん下の段の値を区切った語。"""
    levels = io["resource"].get("levels") or {}
    order = vocab("resource-kinds")["kinds"].get(io["resource"]["kind"], {})
    for level in reversed(order.get("levels", [])):
        if level in levels:
            value = str(levels[level])
            # {file} のように、値が穴だけなら、探す語が無い (穴の中は、分析する側が付けた仮の名前)。
            # 穴の外に語があれば、穴の中の語も探す (run_id のように、コードの変数の名前と同じことが多い)
            return _words(value) if _words(_outside_holes(value)) else []
    return []


def _outside_holes(value: str) -> str:
    """穴 ({…}) を除いた残り。入れ子の穴 ({number:0{width}d}) は、内側から順に除く。"""
    while True:
        rest = _HOLE.sub(" ", value)
        if rest == value:
            return rest
        value = rest


def _setting_words(name: str) -> list[str]:
    """設定を名指しする語。名前そのものと、点でつないだ名前の最後の語 (コードは、最後の語だけで読むことが多い)。"""
    last = name.rsplit(".", 1)[-1]
    if last != name and len(last) >= MIN_WORD and _WORD.fullmatch(last):
        return [name, last]
    return [name]


def _call_claims(frame: dict, where: str):
    call = frame.get("call") or {}
    if frame.get("caller") is not None and call.get("evidence"):
        yield f"{where}/call", _callee_words(frame), call["evidence"]


def _io_claims(frame: dict, where: str):
    for i, io in enumerate(frame.get("io", [])):
        # 段を書いていない読み書き (相手の名前が無い) は、探すものが無い
        if io.get("evidence") and io["resource"].get("levels"):
            yield f"{where}/io/{i}", _resource_words(io), io["evidence"]


def _setting_claims(frame: dict, where: str):
    for i, setting in enumerate(frame.get("settings", [])):
        if setting.get("evidence"):
            yield (
                f"{where}/settings/{i}",
                _setting_words(setting["name"]),
                setting["evidence"],
            )


def claims_of(result: dict):
    """照合する主張を (場所, 探す語, 根拠) で返す。根拠の無い主張 (unknown など) と、相手の段を書いていない読み書きは含めない。"""
    for frame in result["callstack"]:
        where = f"callstack/{frame['id']}"
        yield from _call_claims(frame, where)
        yield from _io_claims(frame, where)
        yield from _setting_claims(frame, where)


class _Lines:
    """scope の中のファイルの行。scope の外と、無いファイルは None。"""

    def __init__(self, scope_dir: Path):
        self.scope = scope_dir.resolve()
        self.cache: dict[str, list[str] | None] = {}

    def _read(self, rel: str) -> list[str] | None:
        try:
            path = (self.scope / rel).resolve()
            if not (path.is_relative_to(self.scope) and path.is_file()):
                return None
            data = path.read_bytes()
            # UTF-8 のテキストだけを読む。ほかの文字コードを無理に読むと、ある名前を「無い」と出す
            # (NUL は UTF-8 としては通るので、別に見る。UTF-16 とバイナリ)
            text = None if b"\0" in data else data.decode("utf-8")
        except (OSError, ValueError, RuntimeError):
            # 読めない根拠として扱い、一覧を止めない。OSError = 開けない、ValueError = パスとして扱えない値と
            # UTF-8 でない中身 (UnicodeDecodeError)、RuntimeError = 輪になったリンク (Python 3.12 まで)
            return None
        if text is None:
            return None
        # 行の数え方を validate result に揃える (改行は \n だけ。splitlines は改ページなどでも分ける)
        lines = text.split("\n")
        return lines[:-1] if lines[-1] == "" else lines

    def of(self, rel: str) -> list[str] | None:
        if rel not in self.cache:
            self.cache[rel] = self._read(rel)
        return self.cache[rel]

    def windows(self, evidence: list[dict]) -> tuple[list[str], bool]:
        """(読めた根拠ごとの前後の行をつないだもの, 読めない根拠があったか)。"""
        out: list[str] = []
        unreadable = False
        for ev in evidence:
            lines = self.of(ev["file"])
            line = int(ev["line"])  # 形式は 10.0 のような整数の値も通す
            if lines is None or line > len(lines):
                unreadable = True
            else:
                out.extend(lines[max(0, line - 1 - WINDOW) : line + WINDOW])
        return out, unreadable


def _found(word: str, lines: list[str]) -> bool:
    pattern = re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.ASCII)
    return any(pattern.search(line) for line in lines)


def _places(evidence: list[dict]) -> str:
    return ", ".join(f"{ev['file']}:{ev['line']}" for ev in evidence)


def unnamed_evidence(result: dict, scope_dir: Path) -> dict:
    """根拠の近くに名前が無い主張を数えて並べる。

    返す値: checked (照合した数)、unnamed (名前が無い主張の文の一覧)、
    skipped (照合できなかった主張の文の一覧。根拠が読めないか、探す語が無い)。
    """
    files = _Lines(scope_dir)
    report: dict = {"checked": 0, "unnamed": [], "skipped": []}
    for where, words, evidence in claims_of(result):
        kind, text = _judge(where, words, evidence, files)
        report["checked"] += kind != "skipped"
        if text:
            report[kind].append(text)
    return report


def _judge(where, words, evidence, files) -> tuple[str, str | None]:
    """主張 1 つを ("checked" | "unnamed" | "skipped", 並べる文) にする。"""
    if not words:
        return (
            "skipped",
            f"{where}: 名前に、探せる語 ({MIN_WORD} 文字以上の英数字。読み書きの相手は、{{…}} の外にあるもの) が無い",
        )
    lines, unreadable = files.windows(evidence)
    if any(_found(word, lines) for word in words):
        return "checked", None
    if unreadable:  # 読めた根拠には無く、読めない根拠が残っている
        return (
            "skipped",
            f"{where}: 根拠 ({_places(evidence)}) に、読めないものがある (ファイルが無い、行が行数を超える、UTF-8 のテキストでない。validate result の指摘があれば直す)",
        )
    return (
        "unnamed",
        f"{where}: {', '.join(repr(w) for w in words)} のどれも、根拠 ({_places(evidence)}) の前後 {WINDOW} 行に無い",
    )


def format_report(label: str, report: dict) -> str:
    head = (
        f"{label}: 根拠の近くに名前が無い主張 {len(report['unnamed'])} 件 "
        f"(照合した主張 {report['checked']} 件、照合できなかった主張 {len(report['skipped'])} 件)"
    )
    body = [f"  - {line}" for line in report["unnamed"]]
    body += [f"  - (照合できない) {line}" for line in report["skipped"]]
    return "\n".join([head, *body])
