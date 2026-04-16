"""
models.py

- managed = False 로 설정 → Django가 테이블을 직접 생성/수정하지 않는다
- db_table 은 환경변수(os.environ)로 바인딩 가능하게 설계
- 컬럼 추가/변경 시: 해당 모델 클래스에 필드만 추가하고 migrate 없이 사용 가능

[다중 DB 확장 시 모델 추가 위치]
  이 파일 하단에 새 모델 클래스를 추가한다.
  예) class EquipmentUtilization(models.Model): ...
      class MaintenanceRecord(models.Model): ...
  각 모델의 Meta.db_table 을 환경변수로 바인딩하면 테이블명 유연하게 관리 가능.
"""

import os
from django.db import models

# ─────────────────────────────────────────────────────────────────
# 테이블명 상수 (환경변수로 오버라이드 가능)
# ─────────────────────────────────────────────────────────────────
TABLE_REPORT = os.environ.get("TABLE_REPORT", "report_interlock")
TABLE_RAW    = os.environ.get("TABLE_RAW",    "interlock_raw")

# [다중 DB 확장] 새 테이블 추가 시 여기에 상수 선언
# TABLE_EQP_UTIL    = os.environ.get("TABLE_EQP_UTIL",    "eqp_utilization")
# TABLE_MAINTENANCE = os.environ.get("TABLE_MAINTENANCE", "maintenance_record")


# ─────────────────────────────────────────────────────────────────
# Report 집계 테이블
# ─────────────────────────────────────────────────────────────────
class SpotfireReport(models.Model):
    """집계 리포트 테이블 (M/W/D chart 용)"""

    yyyy       = models.CharField(max_length=4)
    flag       = models.CharField(max_length=1)
    flagdate   = models.CharField(max_length=20)
    line       = models.CharField(max_length=50)
    sdwt_prod  = models.CharField(max_length=50, blank=True)
    eqp_id     = models.CharField(max_length=50, blank=True)
    eqp_model  = models.CharField(max_length=50, blank=True)
    param_type = models.CharField(max_length=50, blank=True)
    cnt        = models.IntegerField(default=0)
    ratio      = models.FloatField(default=0.0)
    rank       = models.IntegerField(default=0)

    class Meta:
        managed  = False
        db_table = TABLE_REPORT


# ─────────────────────────────────────────────────────────────────
# Raw 원본 데이터 테이블
# 역할: bar 클릭 후 상세 조회 (Rawdata Show / Top Show)
#
# [변경 이력]
#   - value(float) 제거: Raw 테이블은 인터락 발생 이벤트 로그이므로
#     숫자 측정값이 아닌 발생 건수(COUNT) 기반으로 분석한다.
#   - param_name 추가: 파라미터명 단위 집계를 위해 추가
#     집계 계층: LINE → LINE+EQP_ID → LINE+EQP_ID+PARAM_TYPE
#               → LINE+EQP_ID+PARAM_TYPE+PARAM_NAME
# ─────────────────────────────────────────────────────────────────
class SpotfireRaw(models.Model):
    """
    Raw 원본 테이블 (이벤트 로그 기반, click-detail 용)

    집계 기준 계층 (LLM 쿼리 group_by 에서 활용):
        1단계: ["line"]
        2단계: ["line", "eqp_id"]
        3단계: ["line", "eqp_id", "param_type"]
        4단계: ["line", "eqp_id", "param_type", "param_name"]

    cnt 는 이 테이블의 pk 를 COUNT 하여 산출한다.
    """

    yyyymmdd   = models.CharField(max_length=10)     # "2026-01-01" 또는 "20260101"
    act_time   = models.CharField(max_length=30, blank=True)  # 발생 시각 문자열
    line       = models.CharField(max_length=50)
    sdwt_prod  = models.CharField(max_length=50, blank=True)
    eqp_id     = models.CharField(max_length=50, blank=True)
    unit_id    = models.CharField(max_length=50, blank=True)
    eqp_model  = models.CharField(max_length=50, blank=True)
    param_type = models.CharField(max_length=50, blank=True)
    param_name = models.CharField(max_length=50, blank=True)
    ppid       = models.CharField(max_length=50, blank=True)
    ch_step    = models.CharField(max_length=50, blank=True)
    lot_id     = models.CharField(max_length=50, blank=True)
    slot_no    = models.CharField(max_length=50, blank=True)

    class Meta:
        managed  = False
        db_table = TABLE_RAW


# ─────────────────────────────────────────────────────────────────
# [다중 DB 확장] 새 테이블 모델 추가 예시
# ─────────────────────────────────────────────────────────────────
# class EquipmentUtilization(models.Model):
#     """
#     설비 가동률 테이블
#     json_validator.py 의 ALLOWED_TABLES / ALLOWED_EQP_UTIL_FIELDS 에도 추가 필요
#     """
#     yyyymmdd   = models.CharField(max_length=8)
#     line       = models.CharField(max_length=50)
#     eqp_id     = models.CharField(max_length=50)
#     uptime_min = models.IntegerField(default=0)   # 가동 시간(분)
#     downtime_min = models.IntegerField(default=0) # 비가동 시간(분)
#     util_rate  = models.FloatField(default=0.0)   # 가동률(%)
#
#     class Meta:
#         managed  = False
#         db_table = TABLE_EQP_UTIL
#
#
# class MaintenanceRecord(models.Model):
#     """
#     설비 정비 기록 테이블
#     """
#     maint_date  = models.DateField()
#     line        = models.CharField(max_length=50)
#     eqp_id      = models.CharField(max_length=50)
#     maint_type  = models.CharField(max_length=50)  # PM / CM / EM
#     downtime_min = models.IntegerField(default=0)
#     engineer    = models.CharField(max_length=100, blank=True)
#     memo        = models.TextField(blank=True)
#
#     class Meta:
#         managed  = False
#         db_table = TABLE_MAINTENANCE