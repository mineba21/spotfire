from django.db import connections
from django.test import TransactionTestCase

from stoploss_ai.models import EqpLossTpm, StoplossReport, TpmEqpLoss
from stoploss_ai.services.detail_service import get_loss_event_detail
from stoploss_ai.services.ratio_service import get_ratio_analysis


class StoplossDetailTests(TransactionTestCase):
    databases = {"default", "tpm"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._created_models = []
        connection = connections["tpm"]
        existing_tables = set(connection.introspection.table_names())
        with connection.schema_editor() as schema:
            for model in (StoplossReport, EqpLossTpm, TpmEqpLoss):
                if model._meta.db_table not in existing_tables:
                    schema.create_model(model)
                    cls._created_models.append(model)

    @classmethod
    def tearDownClass(cls):
        connection = connections["tpm"]
        with connection.schema_editor() as schema:
            for model in reversed(cls._created_models):
                schema.delete_model(model)
        super().tearDownClass()

    def setUp(self):
        StoplossReport.all_objects.using("tpm").all().delete()
        EqpLossTpm.objects.using("tpm").all().delete()
        TpmEqpLoss.objects.using("tpm").all().delete()

        StoplossReport.all_objects.using("tpm").create(
            yyyy="2026", flag="D", flagdate="01/01",
            area="A1", sdwt_prod="PROD-A", eqp_id="EQP-1",
            eqp_model="MODEL-X", prc_group="ETCH",
            plan_time=100, stoploss=10, rank=1,
        )
        StoplossReport.all_objects.using("tpm").create(
            yyyy="2026", flag="D", flagdate="01/03",
            area="A1", sdwt_prod="PROD-A", eqp_id="EQP-1",
            eqp_model="MODEL-X", prc_group="ETCH",
            plan_time=100, stoploss=20, rank=1,
        )
        StoplossReport.all_objects.using("tpm").create(
            yyyy="2026", flag="D", flagdate="01/01",
            area="A1", sdwt_prod="None", eqp_id="EQP-X",
            eqp_model="MODEL-X", prc_group="ETCH",
            plan_time=100, stoploss=99, rank=2,
        )

        for yyyymmdd, loss_time, lot_id in (
            ("20260101", 5.5, "LOT-1"),
            ("20260102", 7.0, "LOT-2"),
            ("20260103", 9.5, "LOT-3"),
        ):
            EqpLossTpm.objects.using("tpm").create(
                yyyymmdd=yyyymmdd,
                act_time=f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]} 10:00:00",
                line="A1",
                sdwt_prod="PROD-A",
                eqp_id="EQP-1",
                eqp_model="MODEL-X",
                param_type="ERD",
                param_name="EMG_STOP",
                loss_time=loss_time,
                lot_id=lot_id,
            )

    def test_stoploss_report_default_manager_excludes_string_none(self):
        self.assertEqual(StoplossReport.all_objects.using("tpm").count(), 3)
        self.assertEqual(StoplossReport.objects.using("tpm").count(), 2)

    def test_loss_event_detail_uses_selected_date_ranges_not_min_max_span(self):
        rows = get_loss_event_detail("D", "2026", ["01/01", "01/03"], {})
        self.assertEqual([row["yyyymmdd"] for row in rows], ["20260101", "20260103"])
        self.assertEqual([row["loss_time_min"] for row in rows], [5.5, 9.5])

    def test_click_detail_splits_event_rows_and_report_rows(self):
        response = self.client.get(
            "/stoploss-ai/api/click-detail/",
            {"flag": "D", "yyyy": "2026", "flagdate": "01/01"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]

        self.assertIn("param_type", payload["columns"])
        self.assertIn("param_name", payload["columns"])
        self.assertEqual(payload["rows"][0]["loss_time_min"], 5.5)

        self.assertIn("report_rows", payload)
        self.assertEqual(payload["report_rows"][0]["eqp_id"], "EQP-1")
        self.assertEqual(payload["report_columns"], ["flag", "flagdate", "eqp_id", "stoploss", "plan_time"])

    def test_ratio_allocates_raw_duration_to_report_stoploss_scope(self):
        TpmEqpLoss.objects.using("tpm").bulk_create([
            TpmEqpLoss(
                yyyymmdd="20260101",
                eqp_id="EQP-1",
                start_time="2026-01-01 00:00:00",
                end_time="2026-01-01 10:00:00",
                state="A",
            ),
            TpmEqpLoss(
                yyyymmdd="20260101",
                eqp_id="EQP-1",
                start_time="2026-01-01 10:00:00",
                end_time="2026-01-02 00:00:00",
                state="B",
            ),
            TpmEqpLoss(
                yyyymmdd="20260101",
                eqp_id="EQP-MISSING",
                start_time="2026-01-01 00:00:00",
                end_time="2026-01-02 00:00:00",
                state="A",
            ),
        ])

        rows = get_ratio_analysis("D", "2026", ["01/01"], {}, "eqp_id")

        self.assertEqual(rows, [{
            "eqp_id": "EQP-1",
            "loss_time_min": 10.0,
            "pct_vs_eqp": 100.0,
            "pct_vs_model": 100.0,
            "pct_vs_sdwt": 100.0,
            "pct_vs_area": 100.0,
            "pct_vs_total": 100.0,
        }])

    def test_ratio_state_total_pct_sums_to_report_stoploss_after_allocation(self):
        TpmEqpLoss.objects.using("tpm").bulk_create([
            TpmEqpLoss(
                yyyymmdd="20260101",
                eqp_id="EQP-1",
                start_time="2026-01-01 00:00:00",
                end_time="2026-01-01 01:00:00",
                state="A",
            ),
            TpmEqpLoss(
                yyyymmdd="20260101",
                eqp_id="EQP-1",
                start_time="2026-01-01 01:00:00",
                end_time="2026-01-01 04:00:00",
                state="B",
            ),
        ])

        rows = get_ratio_analysis("D", "2026", ["01/01"], {}, "state")

        self.assertEqual(
            [(row["state"], row["loss_time_min"], row["pct_vs_total"]) for row in rows],
            [("B", 7.5, 75.0), ("A", 2.5, 25.0)],
        )
        self.assertEqual(round(sum(row["pct_vs_total"] for row in rows), 2), 100.0)

    def test_ratio_denominator_respects_prc_group_filter(self):
        StoplossReport.all_objects.using("tpm").create(
            yyyy="2026", flag="D", flagdate="01/01",
            area="A2", sdwt_prod="PROD-B", eqp_id="EQP-2",
            eqp_model="MODEL-Y", prc_group="CVD",
            plan_time=100, stoploss=40, rank=3,
        )
        TpmEqpLoss.objects.using("tpm").bulk_create([
            TpmEqpLoss(
                yyyymmdd="20260101",
                eqp_id="EQP-1",
                start_time="2026-01-01 00:00:00",
                end_time="2026-01-01 01:00:00",
                state="A",
            ),
            TpmEqpLoss(
                yyyymmdd="20260101",
                eqp_id="EQP-2",
                start_time="2026-01-01 00:00:00",
                end_time="2026-01-01 01:00:00",
                state="A",
            ),
        ])

        rows = get_ratio_analysis("D", "2026", ["01/01"], {"prc_group": ["ETCH"]}, "eqp_id")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["eqp_id"], "EQP-1")
        self.assertEqual(rows[0]["loss_time_min"], 10.0)
        self.assertEqual(rows[0]["pct_vs_total"], 100.0)
