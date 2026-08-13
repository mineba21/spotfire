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

from django.db.models import Q

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


# ─── 데이터 후처리 설정 ──────────────────────────────────────────
# eqp_id 에 이 단어 중 하나라도 포함되면 raw_detail 결과에서 제외 (대소문자 무시).
# DB 단계 .exclude(eqp_id__icontains=...) 로 처리되어 효율적.
# 빈 list 일 때는 무영향 (기존 동작과 동일).
EQP_ID_EXCLUDE_KEYWORDS = [
    # TODO: 운영 환경에서 실제 제외 키워드 채워넣기
    # 예: "TEST", "DUMMY", "VIRT",
]

# sdwt_prod 값 치환 (key=DB 원본, value=화면 표시값). 정확 일치 기준.
# 사이드바 드롭다운은 DB 원본 값 그대로 표시 (필터링은 정상 작동).
# 빈 dict 일 때는 무영향.
SDWT_PROD_REPLACEMENTS = {
    # TODO: 운영 환경에서 실제 치환 매핑 채워넣기
    # 예: "OLD_VAL_1": "NEW_VAL_1",
}


def _apply_sdwt_replacement(row: dict) -> dict:
    """SDWT_PROD_REPLACEMENTS 가 비어있지 않으면 sdwt_prod 값을 치환한다."""
    if SDWT_PROD_REPLACEMENTS:
        sp = row.get("sdwt_prod")
        if sp in SDWT_PROD_REPLACEMENTS:
            row = dict(row)  # 원본 dict 가 generator 에서 재사용될 수 있으므로 복사
            row["sdwt_prod"] = SDWT_PROD_REPLACEMENTS[sp]
    return row


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


def normalize_fd_pairs(flagdates, yyyy: str) -> list:
    """
    flagdates 입력을 (flagdate, yyyy) 쌍 리스트로 정규화한다 (하위 호환).

      1) "M03"                            → yyyy 인자 사용
      2) ["M03", "M10"]                   → 모두 yyyy 인자 사용 (구버전)
      3) [("M03","2026"), ("M10","2025")] → 쌍별 연도 사용 (신규, 권장)
    """
    if isinstance(flagdates, str):
        flagdates = [flagdates]

    fd_pairs = []
    for item in flagdates or []:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            fd, fy = str(item[0]).strip(), str(item[1]).strip()
        else:
            fd, fy = str(item).strip(), yyyy
        if fd:
            fd_pairs.append((fd, fy))
    return fd_pairs


def _detect_ymd_hyphen() -> bool:
    """DB yyyymmdd 저장 형식이 "2026-04-03"(하이픈) 인지 "20260403" 인지 감지."""
    sample = SpotfireRaw.objects.values_list("yyyymmdd", flat=True).first()
    return "-" in str(sample) if sample else False


def _to_db_ymd(ymd8: str, has_hyphen: bool) -> str:
    if has_hyphen and len(ymd8) == 8 and ymd8.isdigit():
        return f"{ymd8[:4]}-{ymd8[4:6]}-{ymd8[6:8]}"
    return ymd8


def _build_date_q(flag: str, fd_pairs: list):
    """
    각 (flagdate, yyyy) 범위를 OR 로 결합한 Q 를 반환한다.

    min~max 로 감싸면 선택하지 않은 중간 기간까지 조회되므로 반드시 OR 로 묶는다.
    (예: M03 + M10 선택 → 3월 / 10월 두 구간만)
    유효 범위가 하나도 없으면 None.
    """
    has_hyphen = _detect_ymd_hyphen()

    date_q    = Q()
    range_log = []
    for fd, fy in fd_pairs:
        s, e = get_date_range(flag, fy, fd)
        if not (s and e):
            logger.warning("get_date_range None | flag=%s yyyy=%s fd=%s", flag, fy, fd)
            continue
        date_q |= Q(yyyymmdd__gte=_to_db_ymd(s, has_hyphen),
                    yyyymmdd__lte=_to_db_ymd(e, has_hyphen))
        range_log.append(f"{fy}/{fd}:{s}~{e}")

    if not range_log:
        return None

    logger.info("[Detail] flag=%s | ranges=[%s] | 하이픈=%s",
                flag, ", ".join(range_log), has_hyphen)
    return date_q


def _normalize_act_time(rows):
    """
    act_time 표시 형식 정규화.

    DB 는 DATETIME 이지만 모델은 CharField 라 datetime 객체가 그대로 넘어오고,
    JsonResponse 직렬화 단계에서 ISO("T") 형식이 된다. 문자열 replace 로는
    잡히지 않으므로 여기서 naive datetime → "YYYY-MM-DD HH:MM:SS" 로 변환한다.
    """
    for row in rows:
        at = row.get("act_time")
        if hasattr(at, "tzinfo") and at.tzinfo is not None:
            at = at.replace(tzinfo=None)
        if hasattr(at, "strftime"):
            row["act_time"] = at.strftime("%Y-%m-%d %H:%M:%S")
        elif at and "T" in str(at):
            row["act_time"] = str(at).replace("T", " ")
    return rows


def get_raw_detail(flag: str, yyyy: str, flagdates, filters: dict) -> list:
    """
    (flag, flagdates) + sidebar 필터 기준으로 raw data 를 조회한다.

    - flagdates: normalize_fd_pairs 가 받는 모든 형식 지원 (쌍 권장)
    - 각 flagdate 범위는 OR 로 결합한다 (min~max 로 감싸지 않음)
    반환: dict list (각 dict 는 RAW_COLUMNS 에 정의된 컬럼만 포함)
    Raw 테이블은 이벤트 로그이므로 건수(행 수) 자체가 발생 횟수를 의미한다.
    """
    fd_pairs = normalize_fd_pairs(flagdates, yyyy)
    if not fd_pairs:
        return []

    date_q = _build_date_q(flag, fd_pairs)
    if date_q is None:
        return []

    q  = build_filter_q(filters)
    qs = SpotfireRaw.objects.filter(q).filter(date_q)

    # eqp_id 제외 키워드 (DB 단계 — 효율적)
    for kw in EQP_ID_EXCLUDE_KEYWORDS:
        if kw:
            qs = qs.exclude(eqp_id__icontains=kw)

    qs   = qs.values(*RAW_COLUMNS).order_by("yyyymmdd", "act_time")
    rows = list(qs)

    # sdwt_prod 치환 (Python 단계 — 사이드바는 원본 그대로)
    if SDWT_PROD_REPLACEMENTS:
        for row in rows:
            sp = row.get("sdwt_prod")
            if sp in SDWT_PROD_REPLACEMENTS:
                row["sdwt_prod"] = SDWT_PROD_REPLACEMENTS[sp]

    _normalize_act_time(rows)

    logger.info("[Detail] 조회 결과 %d건", len(rows))

    return rows


def iter_raw_detail_export(flag: str, yyyy: str, flagdates, filters: dict):
    """
    Excel export 용 raw 행 iterator.

    get_raw_detail 와 같은 scope (sidebar 필터 + 기간, 쌍별 연도 + OR 결합) 이지만
    MAX_RAW_ROWS limit 없이 queryset.iterator() 를 반환한다. openpyxl write_only
    모드와 조합해 메모리 효율적 스트리밍 가능.
    """
    fd_pairs = normalize_fd_pairs(flagdates, yyyy)
    if not fd_pairs:
        return iter(())

    date_q = _build_date_q(flag, fd_pairs)
    if date_q is None:
        return iter(())

    q  = build_filter_q(filters)
    qs = SpotfireRaw.objects.filter(q).filter(date_q)

    for kw in EQP_ID_EXCLUDE_KEYWORDS:
        if kw:
            qs = qs.exclude(eqp_id__icontains=kw)

    qs = (
        qs.values(*RAW_COLUMNS)
          .order_by("yyyymmdd", "act_time")
    )

    # SDWT_PROD_REPLACEMENTS 가 비어있으면 raw iterator 그대로,
    # 비어있지 않으면 row 마다 치환한 dict 를 yield 하는 wrapper 반환.
    base = qs.iterator(chunk_size=1000)
    if not SDWT_PROD_REPLACEMENTS:
        return base

    def _replaced():
        for row in base:
            yield _apply_sdwt_replacement(row)
    return _replaced()