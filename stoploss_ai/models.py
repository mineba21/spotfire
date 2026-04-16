"""
stoploss_ai/models.py

테이블:
  TABLE_STOPLOSS_REPORT  = "report_stoploss"
  TABLE_EQP_LOSS         = "eqp_loss_tpm"

LOSS_COLUMNS = ["stoploss", "pm", "qual", "bm"]
  - stoploss: 전체 정지로스 합 (min)
  - pm: 예방보전 (min)
  - qual: 품질 (min)
  - bm: 사후보전 (min)
  - ratio = loss / plan_time * 100 (화면에서 계산)

StoplossReport (managed=False):
  id, yyyy, flag, flagdate, line, sdwt_prod, eqp_id, eqp_model
  plan_time, stoploss, pm, qual, bm (FloatField, default=0.0)
  rank (IntegerField, default=0)

EqpLossTpm (managed=False):
  id, yyyymmdd, act_time, line, sdwt_prod, eqp_id, unit_id, eqp_model
  param_type, param_name (CharField)
  loss_time (FloatField, default=0.0)
  lot_id (CharField)
"""
import os
from django.db import models

TABLE_STOPLOSS_REPORT = os.environ.get("TABLE_STOPLOSS_REPORT", "report_stoploss")
TABLE_EQP_LOSS        = os.environ.get("TABLE_EQP_LOSS",        "eqp_loss_tpm")

LOSS_COLUMNS = ["stoploss", "pm", "qual", "bm"]


class StoplossReport(models.Model):
    yyyy       = models.CharField(max_length=4)
    flag       = models.CharField(max_length=1)
    flagdate   = models.CharField(max_length=10)
    line       = models.CharField(max_length=50, default="")
    sdwt_prod  = models.CharField(max_length=100, default="")
    eqp_id     = models.CharField(max_length=100, default="")
    eqp_model  = models.CharField(max_length=100, default="")
    plan_time  = models.FloatField(default=0.0)
    stoploss   = models.FloatField(default=0.0)
    pm         = models.FloatField(default=0.0)
    qual       = models.FloatField(default=0.0)
    bm         = models.FloatField(default=0.0)
    rank       = models.IntegerField(default=0)

    class Meta:
        managed  = False
        db_table = TABLE_STOPLOSS_REPORT


class EqpLossTpm(models.Model):
    yyyymmdd   = models.CharField(max_length=10, default="")
    act_time   = models.CharField(max_length=30, default="")
    line       = models.CharField(max_length=50, default="")
    sdwt_prod  = models.CharField(max_length=100, default="")
    eqp_id     = models.CharField(max_length=100, default="")
    unit_id    = models.CharField(max_length=100, default="")
    eqp_model  = models.CharField(max_length=100, default="")
    param_type = models.CharField(max_length=50, default="")
    param_name = models.CharField(max_length=200, default="")
    loss_time  = models.FloatField(default=0.0)
    lot_id     = models.CharField(max_length=100, default="")

    class Meta:
        managed  = False
        db_table = TABLE_EQP_LOSS
