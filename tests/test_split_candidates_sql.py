"""集計表「別の入口に分ける候補」の数え方を、小さな表で直接確かめる (dbt を通さず、モデルの SQL をそのまま動かす)。"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SQL = (ROOT / "dbt-template/models/core/mart_split_candidates.sql").read_text(
    encoding="utf-8"
)


def _frames(entry: str, reverse: bool) -> list[tuple]:
    """入口 1 つの木。部品 Panel を、2 つの呼び出し元 (a、b) の下に書き、それぞれ違う枝 (7 段ずつ) を持たせる。サーバー側の関数 check も、同じ大きさで書く。"""
    rows = [(entry, "root", "page", "Page", "p.tsx", 1, "", "false")]
    for side in ("a", "b"):
        rows.append(
            (
                entry,
                f"caller_{side}",
                "component",
                f"Caller{side}",
                "c.tsx",
                1 if side == "a" else 2,
                "root",
                "true",
            )
        )
        rows.append(
            (
                entry,
                f"panel_{side}",
                "component",
                "Panel",
                "panel.tsx",
                10,
                f"caller_{side}",
                "true",
            )
        )
        rows.append(
            (
                entry,
                f"check_{side}",
                "query",
                "check",
                "check.ts",
                5,
                f"caller_{side}",
                "false",
            )
        )
        for i in range(7):
            rows.append(
                (
                    entry,
                    f"leaf_{side}{i}",
                    "component",
                    f"Leaf{side}{i}",
                    "leaf.tsx",
                    (100 if side == "a" else 200) + i,
                    f"panel_{side}",
                    "true",
                )
            )
            rows.append(
                (
                    entry,
                    f"q_{side}{i}",
                    "query",
                    f"q{side}{i}",
                    "q.ts",
                    (100 if side == "a" else 200) + i,
                    f"check_{side}",
                    "false",
                )
            )
    return rows[::-1] if reverse else rows


def _candidates(reverse: bool) -> list[tuple]:
    con = duckdb.connect()
    con.execute(
        "create table stg_frames (entry_id varchar, frame_id varchar, layer varchar, name varchar, source_file varchar, source_line int, caller_id varchar, splittable varchar)"
    )
    con.execute("create table stg_entries (entry_id varchar, path varchar)")
    for n in range(3):
        con.execute("insert into stg_entries values (?, ?)", [f"e{n}", f"/e{n}"])
        con.executemany(
            "insert into stg_frames values (?, ?, ?, ?, ?, ?, ?, ?)",
            _frames(f"e{n}", reverse),
        )
    sql = SQL.replace("{{ ref('stg_frames') }}", "stg_frames").replace(
        "{{ ref('stg_entries') }}", "stg_entries"
    )
    return con.execute(
        f"select name, layer, entry_count, frames_each, repeated_frames from ({sql}) order by name"  # nosec B608 - project SQL fixture
    ).fetchall()


def test_branches_written_under_different_callers_are_counted_together():
    rows = _candidates(reverse=False)
    # Panel は、呼び出し元ごとに 8 段 (自分 + 7)。合わせると 15 段で、10 段の条件を満たす。3 つの入口で、繰り返しは 30 段
    assert ("Panel", "component", 3, 15, 30) in rows, rows
    # 呼び出し元 (Callera、Callerb) は、下が 9 段 (自分 + Panel + 7。サーバー側の関数も数えると 17 段) で、別々の処理
    assert {r[0] for r in rows} == {"Callera", "Callerb", "Panel"}, rows
    assert all(r[1] == "component" for r in rows), (
        "分けられない層の処理 (check) は、同じ大きさでも出ない"
    )


def test_the_result_does_not_depend_on_the_order_of_frames():
    assert _candidates(reverse=False) == _candidates(reverse=True)
