from django.db import connections
from django.test import TransactionTestCase

from interlock_ai.models import SpotfireRaw, SpotfireReport, TABLE_RAW
from interlock_ai.services.filter_service import build_filter_q
from interlock_ai.services.query_builder import execute_query
from interlock_ai.views import _get_distinct


class InterlockLinePrefixTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._created_models = []
        connection = connections["default"]
        existing_tables = set(connection.introspection.table_names())
        with connection.schema_editor() as schema:
            for model in (SpotfireReport, SpotfireRaw):
                if model._meta.db_table not in existing_tables:
                    schema.create_model(model)
                    cls._created_models.append(model)

    @classmethod
    def tearDownClass(cls):
        connection = connections["default"]
        with connection.schema_editor() as schema:
            for model in reversed(cls._created_models):
                schema.delete_model(model)
        super().tearDownClass()

    def setUp(self):
        SpotfireReport.objects.all().delete()
        SpotfireRaw.objects.all().delete()

        for line in ("AB1234", "AB5678", "CD_LINE_01"):
            SpotfireReport.objects.create(
                yyyy="2026",
                flag="D",
                flagdate="01/01",
                line=line,
                sdwt_prod="PROD-A",
                eqp_id=f"EQP-{line[:2]}",
                eqp_model="MODEL-X",
                param_type="ERD",
                cnt=1,
                ratio=1.0,
                rank=1,
            )
            SpotfireRaw.objects.create(
                yyyymmdd="20260101",
                act_time="2026-01-01 10:00:00",
                line=line,
                sdwt_prod="PROD-A",
                eqp_id=f"EQP-{line[:2]}",
                unit_id="UNIT-1",
                eqp_model="MODEL-X",
                param_type="ERD",
                param_name="EMG_STOP",
                ppid="PPID-1",
                ch_step="STEP-1",
                lot_id="LOT-1",
                slot_no="1",
            )

    def test_distinct_line_options_are_prefix_deduped(self):
        self.assertEqual(_get_distinct("line"), ["AB", "CD"])

    def test_line_filter_uses_prefix_startswith(self):
        q = build_filter_q({"line": ["AB"]})
        self.assertEqual(SpotfireRaw.objects.filter(q).count(), 2)

    def test_ai_query_group_by_line_coalesces_prefix_groups(self):
        rows = execute_query({
            "table": TABLE_RAW,
            "filters": {},
            "group_by": ["line"],
            "aggregations": [{"func": "count", "field": "pk", "alias": "cnt"}],
            "order_by": [{"field": "cnt", "direction": "desc"}],
            "limit": 10,
        })

        self.assertEqual(rows, [
            {"line": "AB", "cnt": 2},
            {"line": "CD", "cnt": 1},
        ])
