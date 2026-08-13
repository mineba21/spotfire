"""
stoploss_ai/models.py

테이블:
  TABLE_STOPLOSS_REPORT  = "report_stoploss"
  TABLE_EQP_LOSS         = "tpm_eqp_loss"   ← 단일 정지 이벤트 로그 테이블

LOSS_COLUMNS: 집계 가능한 손실 시간 컬럼 목록
  - stoploss, pm, qual, bm, eng, etc, stepchg, std_time, rd

StoplossReport (managed=False):
  id, yyyy, flag, flagdate,
  line(db_column="area"),                  # 앱에서는 line 으로 통일, DB 컬럼명은 area 유지
  sdwt_prod,
  eqp_id(db_column="station"),
  eqp_model(db_column="machine_id"),
  prc_group, plan_time, stoploss,
  pm, qual, bm, eng, etc, stepchg, std_time, rd, rank

TpmEqpLoss (managed=False):
  id, yyyymmdd, eqp_id, station, area,
  start_time, end_time, state, kind, param_type, param_name, loss_time_min

  · loss_time_min 은 적재 시 (end_time - start_time) 분으로 채워지는 DB 컬럼이다.
    (파싱실패 0 / 음수 0 / 소수 1자리 규칙은 적재측에서 적용)
    detail_service · ratio_service · lossraw_service 모두 이 컬럼을 읽는다.
  · station(설비) 과 eqp_id 는 각각 별도 DB 컬럼이다.
    현재는 값이 같지만 추후 서로 다른 값을 갖게 될 예정이라 필드를 분리해 둔다.
    (StoplossReport.eqp_id 는 report_stoploss.station 컬럼 매핑 — 별개 테이블)
"""
import os
from django.db import models

TABLE_STOPLOSS_REPORT = os.environ.get("TABLE_STOPLOSS_REPORT", "report_stoploss")
TABLE_EQP_LOSS        = os.environ.get("TABLE_EQP_LOSS",        "tpm_eqp_loss")

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
    line       = models.CharField(max_length=50,  default="", db_column="area")        # DB 컬럼명 area, 앱에서는 line 으로 사용
    sdwt_prod  = models.CharField(max_length=100, default="")
    eqp_id     = models.CharField(max_length=100, default="", db_column="station")     # DB 컬럼명 station
    eqp_model  = models.CharField(max_length=100, default="", db_column="machine_id")  # DB 컬럼명 machine_id
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
    - Stoploss 페이지: Bar 클릭 시에만 조회 (초기 로딩 없음)
    - Loss Raw 페이지: kind → param_type → param_name 드릴다운 집계
    - loss_time_min 은 적재 시 채워지는 DB 컬럼 (분 단위)
    - station(설비) 과 eqp_id 는 별도 컬럼 — 추후 값이 서로 달라질 예정
    """
    yyyymmdd      = models.CharField(max_length=10,  default="")   # 숫자형 문자열
    eqp_id        = models.CharField(max_length=100, default="")   # DB: eqp_id
    station       = models.CharField(max_length=100, default="")   # DB: station (설비)
    area          = models.CharField(max_length=100, default="")   # 라인
    start_time    = models.CharField(max_length=30,  default="")   # 문자열 datetime
    end_time      = models.CharField(max_length=30,  default="")   # 문자열 datetime
    state         = models.CharField(max_length=100, default="")
    kind          = models.CharField(max_length=100, default="")
    param_type    = models.CharField(max_length=100, default="")
    param_name    = models.CharField(max_length=100, default="")
    loss_time_min = models.FloatField(default=0.0)

    class Meta:
        managed  = False
        db_table = TABLE_EQP_LOSS
