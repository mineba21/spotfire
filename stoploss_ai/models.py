"""
stoploss_ai/models.py

테이블:
  TABLE_STOPLOSS_REPORT  = "report_stoploss"
  TABLE_EQP_LOSS         = "tpm_eqp_loss"
  TABLE_EQP_LOSS_TPM     = "eqp_loss_tpm"

LOSS_COLUMNS: 집계 가능한 손실 시간 컬럼 목록
  - stoploss, pm, qual, bm, eng, etc, stepchg, std_time, rd

StoplossReport (managed=False):
  id, yyyy, flag, flagdate, area, sdwt_prod, eqp_id(→station), eqp_model(→machine_id)
  prc_group, plan_time, stoploss, pm, qual, bm, eng, etc, stepchg, std_time, rd, rank

TpmEqpLoss (managed=False):
  id, yyyymmdd, eqp_id(→station), start_time, end_time, state, down_comment
  loss_time_min: start_time~end_time 시간차(분) — Python 에서 계산 (DB 컬럼 없음)

EqpLossTpm (managed=False):
  id, yyyymmdd, act_time, line, sdwt_prod, eqp_id, unit_id, eqp_model
  param_type, param_name, loss_time, lot_id
"""
import os
from django.db import models

TABLE_STOPLOSS_REPORT = os.environ.get("TABLE_STOPLOSS_REPORT", "report_stoploss")
TABLE_EQP_LOSS        = os.environ.get("TABLE_EQP_LOSS",        "tpm_eqp_loss")
TABLE_EQP_LOSS_TPM    = os.environ.get("TABLE_EQP_LOSS_TPM",    "eqp_loss_tpm")

# 집계 가능한 손실 시간 컬럼 목록
LOSS_COLUMNS = ["stoploss", "pm", "qual", "bm", "eng", "etc", "stepchg", "std_time", "rd"]


class StoplossReportQuerySet(models.QuerySet):
    def with_valid_sdwt_prod(self):
        return self.exclude(sdwt_prod="None")


class StoplossReportManager(models.Manager.from_queryset(StoplossReportQuerySet)):
    def get_queryset(self):
        return super().get_queryset().with_valid_sdwt_prod()


class StoplossReport(models.Model):
    yyyy       = models.CharField(max_length=4)
    flag       = models.CharField(max_length=1)
    flagdate   = models.CharField(max_length=10)
    area       = models.CharField(max_length=50,  default="")   # 구 line
    sdwt_prod  = models.CharField(max_length=100, default="")
    eqp_id     = models.CharField(max_length=100, default="", db_column="station")  # DB 컬럼명: station, 앱에서는 eqp_id 로 사용
    eqp_model  = models.CharField(max_length=100, default="", db_column="machine_id")  # DB 컬럼명: machine_id, 앱에서는 eqp_model 로 사용
    prc_group  = models.CharField(max_length=100, default="")
    plan_time  = models.FloatField(default=0.0)
    stoploss   = models.FloatField(default=0.0)
    pm         = models.FloatField(default=0.0)
    qual       = models.FloatField(default=0.0)
    bm         = models.FloatField(default=0.0)
    eng        = models.FloatField(default=0.0)
    etc        = models.FloatField(default=0.0)
    stepchg    = models.FloatField(default=0.0)
    std_time   = models.FloatField(default=0.0)
    rd         = models.FloatField(default=0.0)
    rank       = models.IntegerField(default=0)

    objects = StoplossReportManager()
    all_objects = models.Manager()

    class Meta:
        managed  = False
        db_table = TABLE_STOPLOSS_REPORT


class TpmEqpLoss(models.Model):
    """
    설비 정지 이벤트 로그 (tpm_eqp_loss)
    - Bar 클릭 시에만 조회 (초기 로딩 없음)
    - loss_time_min 은 DB 컬럼 없음 → detail_service 에서 start_time/end_time 차이로 계산
    """
    yyyymmdd     = models.CharField(max_length=10,  default="")
    eqp_id       = models.CharField(max_length=100, default="", db_column="station")  # DB: station
    start_time   = models.CharField(max_length=30,  default="")  # 문자열 datetime
    end_time     = models.CharField(max_length=30,  default="")  # 문자열 datetime
    state        = models.CharField(max_length=100, default="")
    down_comment = models.CharField(max_length=255, default="")

    class Meta:
        managed  = False
        db_table = TABLE_EQP_LOSS


class EqpLossTpm(models.Model):
    """
    설비 정지 이벤트 로그 (eqp_loss_tpm)
    - LOSS EVENT DATA / Top Show 하단 Raw Data 조회용
    - loss_time 은 DB 컬럼이며 화면에는 loss_time_min 으로 노출한다.
    """
    yyyymmdd    = models.CharField(max_length=10,  default="")
    act_time    = models.CharField(max_length=30,  default="")
    line        = models.CharField(max_length=50,  default="")
    sdwt_prod   = models.CharField(max_length=100, default="")
    eqp_id      = models.CharField(max_length=100, default="")
    unit_id     = models.CharField(max_length=100, default="")
    eqp_model   = models.CharField(max_length=100, default="")
    param_type  = models.CharField(max_length=100, default="")
    param_name  = models.CharField(max_length=100, default="")
    loss_time   = models.FloatField(default=0.0)
    lot_id      = models.CharField(max_length=100, default="")

    class Meta:
        managed  = False
        db_table = TABLE_EQP_LOSS_TPM
