"""
services/detail_service.py

역할:
- bar 클릭 시 전달되는 (flag, yyyy, flagdate) 로 날짜 범위를 계산한다
- Raw 테이블에서 해당 기간의 raw data 를 조회한다
- Rawdata Show / Top Show 둘 다 이 서비스에서 데이터를 가져간다

날짜 범위 규칙:
  flag=M, flagdate="M01" → 해당 월의 1일 ~ 말일
  flag=W, flagdate="W03" → 해당 연도 3번째 주 월요일 ~ 일요일
  flag=D, flagdate="2024-01-15" → 해당 일 00:00:00 ~ 23:59:59

컬럼 추가 시:
  - RAW_COLUMNS 에 새 컬럼명을 추가하면 응답 JSON 에 포함된다
  - SpotfireRaw 모델에도 해당 필드가 있어야 한다
"""

import calendar
import datetime
from spotfire_ai.models import SpotfireRaw
from .filter_service import build_filter_q

# ─────────────────────────────────────────────────────────────────
# raw detail 응답에 포함할 컬럼 목록
# 컬럼 추가: 여기에 컬럼명을 추가 + SpotfireRaw 모델에도 필드 추가
# ─────────────────────────────────────────────────────────────────
RAW_COLUMNS = [
    "act_time",
    "yyyymmdd",
    "line",
    "sdwt_prod",
    "eqp_id",
    "eqp_model",
    "param_type",
    "item_id",
    "test_id",
    "value",
    # 추가 컬럼 예시:
    # "recipe_id",
    # "lot_id",
    # "wafer_id",
]

# 조회 최대 row 수 (성능 보호)
MAX_RAW_ROWS = 5000


def get_date_range(flag: str, yyyy: str, flagdate: str):
    """
    (flag, yyyy, flagdate) 로부터 (start_dt, end_dt) datetime 를 계산한다.

    flag=M : "M01" → 2024-01-01 00:00:00 ~ 2024-01-31 23:59:59
    flag=W : "W03" → 해당 연도 3주차 월~일
    flag=D : "2024-01-15" → 2024-01-15 00:00:00 ~ 2024-01-15 23:59:59

    예외 시 None, None 반환 → view 에서 400 처리
    """
    try:
        year = int(yyyy)

        if flag == "M":
            # flagdate = "M01" → 월 번호 추출
            month = int(flagdate[1:])  # "M01" → 1
            # 해당 월 마지막 날
            last_day = calendar.monthrange(year, month)[1]
            start_dt = datetime.datetime(year, month, 1, 0, 0, 0)
            end_dt = datetime.datetime(year, month, last_day, 23, 59, 59)

        elif flag == "W":
            # flagdate = "W03" → 주차 번호 추출
            week_num = int(flagdate[1:])  # "W03" → 3

            # 해당 연도 1월 1일 기준 ISO 주차 계산
            # 1월 1일이 속한 주를 1주차로 한다 (요구사항 기준)
            jan1 = datetime.date(year, 1, 1)
            # 1월 1일의 요일 (Monday=0)
            jan1_weekday = jan1.weekday()
            # 1주차 월요일
            first_monday = jan1 - datetime.timedelta(days=jan1_weekday)
            # 해당 주차 월요일
            week_monday = first_monday + datetime.timedelta(weeks=week_num - 1)
            week_sunday = week_monday + datetime.timedelta(days=6)

            start_dt = datetime.datetime.combine(week_monday, datetime.time.min)
            end_dt = datetime.datetime.combine(week_sunday, datetime.time.max)

        elif flag == "D":
            # flagdate = "2024-01-15"
            date_obj = datetime.date.fromisoformat(flagdate)
            start_dt = datetime.datetime.combine(date_obj, datetime.time.min)
            end_dt = datetime.datetime.combine(date_obj, datetime.time.max)

        else:
            return None, None

        return start_dt, end_dt

    except Exception:
        return None, None


def get_raw_detail(flag: str, yyyy: str, flagdate: str, filters: dict) -> list:
    """
    (flag, yyyy, flagdate) + sidebar 필터 기준으로 raw data 를 조회한다.

    반환: dict list (각 dict 는 RAW_COLUMNS 에 정의된 컬럼만 포함)

    Raw 테이블에 컬럼이 추가되면 RAW_COLUMNS 상수에만 추가하면 된다.
    """
    start_dt, end_dt = get_date_range(flag, yyyy, flagdate)

    if start_dt is None:
        return []

    # sidebar 필터 Q 객체
    q = build_filter_q(filters)

    # act_time 기준 날짜 범위 필터
    # 주의: report 테이블이 아닌 raw 테이블 (SpotfireRaw) 을 사용한다
    qs = (
        SpotfireRaw.objects
        .filter(q)
        .filter(act_time__gte=start_dt, act_time__lte=end_dt)
        .values(*RAW_COLUMNS)
        .order_by("act_time")[:MAX_RAW_ROWS]
    )

    rows = list(qs)

    # datetime 직렬화: JSON 으로 바로 변환 가능하도록 문자열 변환
    for row in rows:
        if "act_time" in row and row["act_time"]:
            row["act_time"] = row["act_time"].strftime("%Y-%m-%d %H:%M:%S")

    return rows
