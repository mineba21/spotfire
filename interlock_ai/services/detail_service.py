"""
services/detail_service.py

역할:
- bar 클릭 시 전달되는 (flag, yyyy, flagdate) 로 날짜 범위를 계산한다
- Raw 테이블에서 해당 기간의 raw data 를 조회한다
- Rawdata Show / Top Show 둘 다 이 서비스에서 데이터를 가져간다

[변경 이력]
  - RAW_COLUMNS 에서 value 제거, param_name 추가
    Raw 테이블은 인터락 발생 이벤트 로그이므로 숫자 측정값 대신
    param_name(파라미터명)으로 발생 건수를 집계한다.
"""

import calendar
import logging
import datetime
logger = logging.getLogger(__name__)

from interlock_ai.models import SpotfireRaw
from .filter_service import build_filter_q

# ─────────────────────────────────────────────────────────────────
# raw detail 응답에 포함할 컬럼 목록
# [변경] value 제거 → param_name 추가
# 컬럼 추가: 여기에 컬럼명을 추가 + SpotfireRaw 모델에도 필드 추가
# ─────────────────────────────────────────────────────────────────
RAW_COLUMNS = [
    "yyyymmdd",
    "act_time",
    "line",
    "sdwt_prod",
    "eqp_id",
    "unit_id",
    "eqp_model",
    "param_type",
    "param_name",
    "ppid",
    "ch_step",
    "lot_id",
    "slot_no",
]

# 조회 최대 row 수 (성능 보호)
MAX_RAW_ROWS = 5000


def get_date_range(flag: str, yyyy: str, flagdate: str):
    """
    (flag, yyyy, flagdate) 로부터 yyyymmdd 범위 문자열 (start_ymd, end_ymd) 을 반환한다.
    Raw 테이블에는 act_time 이 없고 yyyymmdd(8자리 문자열 "20260401") 로 필터링한다.

    [업무 규칙]
    flag=M : "M02" → 2월 (숫자 그대로 월 번호)
             start_ymd="20260201", end_ymd="20260228"

    flag=W : 1월 1일 기준 경과일 // 7 + 1 방식
             W01: 01-01 ~ 01-07, W02: 01-08 ~ 01-14, ...
             start_ymd="20260101", end_ymd="20260107"

    flag=D : flagdate 가 "04/01" 형식 → yyyy + MM + DD 조합
             start_ymd = end_ymd = "20260401"

    반환: (start_ymd: str, end_ymd: str)  예) ("20260201", "20260228")
    예외 시 (None, None) 반환
    """
    try:
        year = int(yyyy)

        if flag == "M":
            # M02 → 2월, 1:1 매핑
            month    = int(flagdate[1:])
            if month < 1 or month > 12:
                return None, None
            last_day = calendar.monthrange(year, month)[1]
            start_ymd = f"{year}{month:02d}01"
            end_ymd   = f"{year}{month:02d}{last_day:02d}"

        elif flag == "W":
            # 1월 1일부터 경과일 // 7 + 1 = 주차
            # → week_num 번째 주: start = jan1 + (week_num-1)*7 일
            week_num      = int(flagdate[1:])
            jan1          = datetime.date(year, 1, 1)
            week_start    = jan1 + datetime.timedelta(days=(week_num - 1) * 7)
            week_end      = jan1 + datetime.timedelta(days=week_num * 7 - 1)
            start_ymd     = week_start.strftime("%Y%m%d")
            end_ymd       = week_end.strftime("%Y%m%d")

        elif flag == "D":
            # flagdate 형식: "04/01" (MM/DD) 또는 "2026-04-01" 또는 "20260401"
            date_obj = _parse_flagdate_d(flagdate, year)
            if date_obj is None:
                return None, None
            ymd       = date_obj.strftime("%Y%m%d")
            start_ymd = ymd
            end_ymd   = ymd

        else:
            return None, None

        return start_ymd, end_ymd

    except Exception:
        return None, None


def _parse_flagdate_d(flagdate: str, year: int) -> "datetime.date | None":
    """
    D flag 의 다양한 flagdate 형식을 date 객체로 변환한다.
    지원: "04/01" (MM/DD), "2026-04-01" (ISO), "20260401" (yyyyMMdd)
    """
    s = flagdate.strip()

    # MM/DD: "04/01"
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            return datetime.date(year, int(parts[0]), int(parts[1]))

    # ISO: "2026-04-01"
    if "-" in s and len(s) == 10:
        try:
            return datetime.date.fromisoformat(s)
        except ValueError:
            pass

    # yyyyMMdd: "20260401"
    if s.isdigit() and len(s) == 8:
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))

    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def get_raw_detail(flag: str, yyyy: str, flagdates, filters: dict) -> list:
    """
    (flag, yyyy, flagdates) + sidebar 필터 기준으로 raw data 를 조회한다.

    - flagdates: 단일 str 또는 list[str] (멀티 bar 선택 지원)
    반환: dict list (각 dict 는 RAW_COLUMNS 에 정의된 컬럼만 포함)
    Raw 테이블은 이벤트 로그이므로 건수(행 수) 자체가 발생 횟수를 의미한다.
    """
    # 단일 str 하위 호환
    if isinstance(flagdates, str):
        flagdates = [flagdates]
    flagdates = [fd for fd in flagdates if fd]
    if not flagdates:
        return []

    # 여러 flagdate 의 date range 를 합친다
    starts, ends = [], []
    for fd in flagdates:
        s, e = get_date_range(flag, yyyy, fd)
        if s and e:
            starts.append(s)
            ends.append(e)

    if not starts:
        logger.warning("get_date_range 반환 None | flag=%s yyyy=%s flagdates=%s", flag, yyyy, flagdates)
        return []

    start_ymd, end_ymd = min(starts), max(ends)

    q = build_filter_q(filters)

    # ── yyyymmdd 포맷 자동 감지 ──────────────────────────────
    # DB 저장 형식이 "20260403"(숫자) 또는 "2026-04-03"(하이픈) 중 하나일 수 있음.
    # 샘플 1건으로 실제 형식을 감지한 뒤 start/end 를 맞춰서 필터링한다.
    sample_qs  = SpotfireRaw.objects.values_list("yyyymmdd", flat=True).first()
    sample_fmt = str(sample_qs) if sample_qs else ""
    has_hyphen = "-" in sample_fmt

    logger.info(
        "[Detail] flag=%s | start_ymd=%r | end_ymd=%r | DB yyyymmdd 샘플=%r (하이픈=%s)",
        flag, start_ymd, end_ymd, sample_fmt, has_hyphen,
    )

    if has_hyphen:
        # DB 가 "2026-04-03" 형식 → start/end 를 하이픈 형식으로 변환
        def to_hyphen(ymd8):  # "20260403" → "2026-04-03"
            if len(ymd8) == 8 and ymd8.isdigit():
                return f"{ymd8[:4]}-{ymd8[4:6]}-{ymd8[6:8]}"
            return ymd8  # 이미 하이픈 형식이면 그대로
        start_filter = to_hyphen(start_ymd)
        end_filter   = to_hyphen(end_ymd)
    else:
        # DB 가 "20260403" 형식 → 그대로 사용
        start_filter = start_ymd
        end_filter   = end_ymd

    logger.info("[Detail] 실제 필터값 | yyyymmdd__gte=%r | yyyymmdd__lte=%r", start_filter, end_filter)

    qs = (
        SpotfireRaw.objects
        .filter(q)
        .filter(yyyymmdd__gte=start_filter, yyyymmdd__lte=end_filter)
        .values(*RAW_COLUMNS)
        .order_by("yyyymmdd")[:MAX_RAW_ROWS]
    )

    rows = list(qs)

    logger.info("[Detail] 조회 결과 %d건", len(rows))

    return rows