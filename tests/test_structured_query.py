import json
from pathlib import Path

from abatlas.extractors.structured_query import extract
from abatlas.schemas import schema_errors

FLOW_A = """id: news_curate
namespace: daily.morning
description: ニュース収集
tasks:
  - id: run
    type: io.kestra.plugin.scripts.shell.Commands
    commands:
      - 'scripts/run-skill.sh marketer news-curate-run'
  - id: notify
    type: io.kestra.plugin.core.flow.Subflow
    namespace: lib
    flowId: notify
triggers:
  - id: daily
    type: io.kestra.plugin.core.trigger.Schedule
    cron: "0 7 * * *"
"""

FLOW_B = """id: notify
namespace: lib
tasks:
  - id: send
    type: io.kestra.plugin.scripts.shell.Commands
    commands:
      - 'python3 notify.py'
"""


def _params():
    return {
        "files": ["flows/**/*.yaml"],
        "format": "yaml",
        "fields": {
            "id": "join('.', [namespace, id])",
            "name": "id",
            "namespace": "namespace",
            "flow": "id",
            "path": "/{namespace}/{flow}",
            "attributes": {
                "commands": "tasks[].commands[]",
                "subflows": "tasks[?contains(type, 'Subflow')].flowId",
                "cron": "triggers[].cron",
            },
        },
        "post": {"namespace": {"split": ".", "join": "/"}},
    }


def test_extracts_kestra_flows(tmp_path: Path, capsys):
    (tmp_path / "flows/daily/morning").mkdir(parents=True)
    (tmp_path / "flows/lib").mkdir(parents=True)
    (tmp_path / "flows/daily/morning/news_curate.yaml").write_text(FLOW_A, encoding="utf-8")
    (tmp_path / "flows/lib/notify.yaml").write_text(FLOW_B, encoding="utf-8")

    extract(tmp_path, _params(), "scheduler")
    out = capsys.readouterr().out
    recs = [json.loads(l) for l in out.splitlines() if l.strip()]
    assert len(recs) == 2
    for r in recs:
        assert schema_errors("entry-candidate", r) == []
    by_id = {r["id"]: r for r in recs}
    a = by_id["daily.morning.news_curate"]
    assert a["path"] == "/daily/morning/news_curate"
    assert a["source"] == {"file": "flows/daily/morning/news_curate.yaml", "line": 1}
    assert a["attributes"]["commands"] == ["scripts/run-skill.sh marketer news-curate-run"]
    assert a["attributes"]["subflows"] == ["notify"]
    assert a["attributes"]["cron"] == ["0 7 * * *"]
    assert by_id["lib.notify"]["path"] == "/lib/notify"


def test_is_deterministic(tmp_path: Path, capsys):
    (tmp_path / "flows").mkdir()
    (tmp_path / "flows/b.yaml").write_text(FLOW_B, encoding="utf-8")
    (tmp_path / "flows/a.yaml").write_text(FLOW_A, encoding="utf-8")
    extract(tmp_path, _params(), "scheduler")
    first = capsys.readouterr().out
    extract(tmp_path, _params(), "scheduler")
    second = capsys.readouterr().out
    assert first == second
