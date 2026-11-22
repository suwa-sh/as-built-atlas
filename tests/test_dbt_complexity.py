"""Metrics refer to compiled SQL structure and direct dbt dependencies."""

from unittest import TestCase

from scripts.dbt_complexity import model_rows


class DbtComplexityTests(TestCase):
    def setUp(self):
        self.node = {
            "resource_type": "model",
            "unique_id": "model.test.items",
            "original_file_path": "models/repo/items.sql",
            "compiled_code": """
                with first as (select * from items),
                second as (select first.* from first join facts using (id))
                select 'JOIN' as label from second -- JOIN in a comment
            """,
            "depends_on": {"nodes": ["seed.test.items", "model.test.facts"]},
        }
        self.manifest = {
            "nodes": {
                "items": self.node,
                "seed": {"resource_type": "seed"},
                "python_model": {"resource_type": "model", "language": "python"},
            }
        }

    def test_counts_ast_nodes_and_manifest_edges(self):
        self.assertEqual(
            list(model_rows(self.manifest, "test")),
            [(1, 2, 2, "test", "model.test.items", "models/repo/items.sql")],
        )

    def test_partial_manifest_and_invalid_query_fail(self):
        for sql in ("", "select from", "create table t(i int)"):
            with (
                self.subTest(sql=sql),
                self.assertRaisesRegex(ValueError, "model.test.items"),
            ):
                self.node["compiled_code"] = sql
                list(model_rows(self.manifest, "test"))
