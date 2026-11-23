"""差分分析で使用する、固定コミットの読み取り。"""

from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from .diff import _git
from .validate import _resolve_scope


def commit(repo, revision):
    return _git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"
    ).strip()


class TargetHistory:
    def __init__(self, target, base):
        self.root = _resolve_scope({**target, "scope": "."}, base)
        if not self.root or not self.root.is_dir():
            raise SystemExit("impact: 対象 Git の clone_path を確認してください")
        if (
            Path(_git(self.root, "rev-parse", "--show-toplevel").strip()).resolve()
            != self.root
        ):
            raise SystemExit(
                "impact: clone_path には対象 Git のルートを指定してください"
            )
        self.scope = Path(target.get("scope", "."))
        if self.scope.is_absolute() or ".." in self.scope.parts:
            raise SystemExit(
                "impact: target.scope は clone 内の相対パスを指定してください"
            )
        self.tip = commit(self.root, target["commit"])
        self._changes = {}
        self._tree = None

    def _in_scope(self, path):
        """Git が返すパスを、範囲からの相対にする。区切りは、どの OS でも「/」(規則や根拠のパスと比べるため)。"""
        return str(PurePosixPath(path).relative_to(self.scope.as_posix()))

    def changes(self, old):
        if old not in self._changes:
            resolved = commit(self.root, old)
            paths = _git(
                self.root,
                "--literal-pathspecs",
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                resolved,
                self.tip,
                "--",
                self.scope.as_posix(),
            )
            self._changes[old] = sorted(
                self._in_scope(p) for p in paths.split("\0") if p
            )
        return self._changes[old]

    def files(self):
        """通常ファイルだけが再利用の根拠になる。リンク先・サブモジュールの中身は別管理。"""
        if self._tree is None:
            data = _git(
                self.root,
                "--literal-pathspecs",
                "ls-tree",
                "-rz",
                self.tip,
                "--",
                self.scope.as_posix(),
            )
            self._tree = set()
            for row in filter(None, data.split("\0")):
                meta, path = row.split("\t", 1)
                if meta.startswith(("100644 blob ", "100755 blob ")):
                    self._tree.add(self._in_scope(path))
        return self._tree

    def checkout_matches(self):
        scope = self.scope.as_posix()
        return commit(self.root, "HEAD") == self.tip and not _git(
            self.root,
            "--no-optional-locks",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            scope,
        )

    @contextmanager
    def snapshot(self):
        with TemporaryDirectory(prefix="abatlas-impact-") as temp:
            # ローカルオブジェクトを読む。対象の index や worktree 一覧には書かない。
            dest = Path(temp).resolve() / "target"
            _git(
                Path(temp),
                "clone",
                "--local",
                "--shared",
                "--no-checkout",
                "--",
                str(self.root),
                str(dest),
            )
            _git(dest, "read-tree", self.tip)
            _check_snapshot_inputs(dest, self.scope)
            _git(
                dest,
                "-c",
                "core.hooksPath=/dev/null",
                "checkout",
                "--force",
                "--detach",
                self.tip,
            )
            scope = dest / self.scope
            if not scope.is_dir() or scope.resolve() != scope:
                raise SystemExit("impact: 指定コミットに target.scope がありません")
            yield scope


def _check_snapshot_inputs(dest, scope):
    """対象ツリーの外部に置かれる実体を、空の入口一覧として扱わない。"""
    entries = _git(
        dest, "--literal-pathspecs", "ls-files", "--stage", "-z", "--", str(scope)
    )
    paths = []
    for entry in filter(None, entries.split("\0")):
        meta, path = entry.split("\t", 1)
        if meta.startswith("160000 "):
            raise SystemExit(
                f"impact: {path} はサブモジュールです。別の対象として分析してください"
            )
        paths.append(path)
    if paths:
        attrs = _git(
            dest,
            "check-attr",
            "--cached",
            "-z",
            "--stdin",
            "filter",
            input_text="\0".join(paths) + "\0",
        )
        if "lfs" in attrs.split("\0")[2::3]:
            raise SystemExit(
                "impact: 対象範囲に Git LFS のファイルがあります。実体を用意して全件分析してください"
            )
