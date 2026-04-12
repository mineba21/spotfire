"""
models.py

- managed = False 로 설정 → Django가 테이블을 직접 생성/수정하지 않는다
- db_table 은 환경변수(os.environ)로 바인딩 가능하게 설계
  실제 운영환경에서는 settings.py 또는 .env 파일에 TABLE_REPORT / TABLE_RAW 를 지정하면 된다
- 컬럼 추가/변경 시: 해당 모델 클래스에 필드만 추가하고 migrate 없이 사용 가능
  (managed=False 이므로 DB 스키마 변경은 DBA/인프라팀과 별도 협의)
"""

import os
from django.db import models

# ─────────────────────────────────────────────────────────────────
# 테이블명 상수 (환경변수로 오버라이드 가능)
# 운영환경 .env 예시:
#   TABLE_REPORT=prod_report
#   TABLE_RAW=prod_raw
# ─────────────────────────────────────────────────────────────────
TABLE_REPORT = os.environ.get("TABLE_REPORT", "spotfire_report")
TABLE_RAW = os.environ.get("TABLE_RAW", "spotfire_raw")


# ─────────────────────────────────────────────────────────────────
# Report 집계 테이블
# 역할: M/W/D bar chart 데이터 소스
# 주의: 클릭 후 상세 조회는 이 테이블이 아닌 Raw 테이블을 사용한다
# ─────────────────────────────────────────────────────────────────
class SpotfireReport(models.Model):
    """
    집계 리포트 테이블 (chart 용)

    컬럼 추가 방법:
        1. 아래에 필드를 추가한다  예) new_col = models.CharField(max_length=50, blank=True)
        2. managed=False 이므로 makemigrations/migrate 없이 즉시 사용 가능
        3. 단, DB 쪽 테이블에 실제 컬럼이 존재해야 한다
    """

    # 연도 (예: "2024")
    yyyy = models.CharField(max_length=4)

    # 집계 플래그: "M"(월), "W"(주), "D"(일)
    flag = models.CharField(max_length=1)

    # 집계 기간 식별자 (예: "M01", "W03", "2024-01-15")
    flagdate = models.CharField(max_length=20)

    # 라인 식별자
    line = models.CharField(max_length=50)

    # 생산 품종/제품군
    sdwt_prod = models.CharField(max_length=50, blank=True)

    # 설비 ID
    eqp_id = models.CharField(max_length=50, blank=True)

    # 설비 모델명
    eqp_model = models.CharField(max_length=50, blank=True)

    # 파라미터 유형 (예: "interlock", "stoploss")
    param_type = models.CharField(max_length=50, blank=True)

    # 발생 건수
    cnt = models.IntegerField(default=0)

    # 비율 (%)
    ratio = models.FloatField(default=0.0)

    # 해당 기간 내 순위
    rank = models.IntegerField(default=0)

    class Meta:
        managed = False          # Django 마이그레이션 대상 아님
        db_table = TABLE_REPORT  # 환경변수로 테이블명 변경 가능
        # MySQL 사용 시 app_label 로 DB 라우팅:
        # app_label = "spotfire_db"


# ─────────────────────────────────────────────────────────────────
# Raw 원본 데이터 테이블
# 역할: bar 클릭 후 상세 조회 (Rawdata Show / Top Show)
# 주의: chart에는 사용하지 않는다
# ─────────────────────────────────────────────────────────────────
class SpotfireRaw(models.Model):
    """
    Raw 원본 테이블 (click-detail 용)

    컬럼 추가 방법:
        1. 아래에 필드를 추가한다
        2. managed=False 이므로 DB에 실제 컬럼이 있으면 바로 사용 가능
        3. views / services 에서 values() 또는 values_list() 로 원하는 컬럼만 선택 가능
    """

    # 실제 발생 시각 (필터 기준: act_time BETWEEN start AND end)
    act_time = models.DateTimeField()

    # 날짜 문자열 (예: "20240115")
    yyyymmdd = models.CharField(max_length=8)

    # 라인
    line = models.CharField(max_length=50)

    # 생산 품종
    sdwt_prod = models.CharField(max_length=50, blank=True)

    # 설비 ID
    eqp_id = models.CharField(max_length=50, blank=True)

    # 설비 모델명
    eqp_model = models.CharField(max_length=50, blank=True)

    # 파라미터 유형
    param_type = models.CharField(max_length=50, blank=True)

    # 아이템 ID
    item_id = models.CharField(max_length=100, blank=True)

    # 테스트 ID
    test_id = models.CharField(max_length=100, blank=True)

    # 측정값
    value = models.FloatField(null=True, blank=True)

    # ── 컬럼 추가 예시 (실제 테이블에 있을 경우 주석 해제) ──
    # recipe_id = models.CharField(max_length=100, blank=True)
    # chamber_id = models.CharField(max_length=50, blank=True)
    # step_id = models.CharField(max_length=50, blank=True)
    # lot_id = models.CharField(max_length=100, blank=True)
    # wafer_id = models.CharField(max_length=100, blank=True)

    class Meta:
        managed = False          # Django 마이그레이션 대상 아님
        db_table = TABLE_RAW     # 환경변수로 테이블명 변경 가능
        # MySQL 사용 시 app_label 로 DB 라우팅:
        # app_label = "spotfire_db"
