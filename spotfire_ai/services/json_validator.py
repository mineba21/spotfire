"""
services/json_validator.py

역할:
- LLM 이 생성한 query JSON 의 안전성 / 형식을 검증한다
- SQL Injection 방지: 모든 테이블명 / 컬럼명 / 함수명을 allowlist 로 제한
- 검증 실패 시 (False, 에러메시지) 반환 → ai_service 에서 재시도 또는 에러 처리

[다중 DB 확장 시]
  1. ALLOWED_TABLES 에 새 테이블명 추가
  2. 새 테이블의 ALLOWED_*_FIELDS frozenset 추가
  3. validate_query_json() 의 allowed_fields 분기에 elif 추가
"""

from __future__ import annotations
from spotfire_ai.models import TABLE_RAW, TABLE_REPORT

# ─────────────────────────────────────────────────────────────────
# Allowlist 상수
# ─────────────────────────────────────────────────────────────────

# 허용 테이블
# [다중 DB 확장] 새 테이블 추가: frozenset({..., TABLE_EQP_UTIL, TABLE_MAINTENANCE})
ALLOWED_TABLES: frozenset = frozenset({TABLE_RAW, TABLE_REPORT})

# spotfire_raw 허용 컬럼
# [변경] value 제거 → param_name 추가
# Raw 테이블은 이벤트 로그이므로 cnt 는 pk COUNT 로 산출하고
# 숫자 측정값(value) 대신 param_name 으로 파라미터별 집계를 수행한다.
ALLOWED_RAW_FIELDS: frozenset = frozenset({
    "yyyymmdd", "act_time",
    "line", "sdwt_prod", "eqp_id", "unit_id", "eqp_model",
    "param_type", "param_name",
    "ppid", "ch_step", "lot_id", "slot_no",
    "pk",
    "yyyy_filter",
    "yyyymmdd_range",
})

# spotfire_report 허용 컬럼 (변경 없음)
ALLOWED_REPORT_FIELDS: frozenset = frozenset({
    "yyyy", "flag", "flagdate",
    "line", "sdwt_prod", "eqp_id", "eqp_model", "param_type",
    "cnt", "ratio", "rank",
    "pk",
})

# [다중 DB 확장] 새 테이블 allowlist 예시
# ALLOWED_EQP_UTIL_FIELDS: frozenset = frozenset({
#     "yyyymmdd", "line", "eqp_id",
#     "uptime_min", "downtime_min", "util_rate",
#     "pk",
# })
#
# ALLOWED_MAINTENANCE_FIELDS: frozenset = frozenset({
#     "maint_date", "line", "eqp_id",
#     "maint_type", "downtime_min", "engineer", "memo",
#     "pk",
# })

# 허용 집계 함수
ALLOWED_AGG_FUNCS: frozenset = frozenset({"count", "avg", "sum", "max", "min"})

# 허용 정렬 방향
ALLOWED_ORDER_DIRS: frozenset = frozenset({"asc", "desc"})

# limit 최대값
MAX_LIMIT: int = 10000

# act_time_range 필수 키
ACT_TIME_RANGE_KEYS: frozenset = frozenset({"flag", "yyyy", "flagdate"})

# 허용 flag 값
ALLOWED_FLAGS: frozenset = frozenset({"M", "W", "D"})


# ─────────────────────────────────────────────────────────────────
# 검증 함수
# ─────────────────────────────────────────────────────────────────

def validate_query_json(qj: dict) -> tuple[bool, str | None]:
    """
    LLM 이 생성한 query JSON 을 검증한다.

    반환:
        (True,  None)          — 검증 통과
        (False, "에러 메시지") — 검증 실패
    """
    if not isinstance(qj, dict):
        return False, "query JSON 은 dict 여야 합니다."

    # ── table 검사 ────────────────────────────────────────────
    table = qj.get("table")
    if table not in ALLOWED_TABLES:
        return False, f"허용되지 않은 table: '{table}'. 허용값: {sorted(ALLOWED_TABLES)}"

    # 테이블별 허용 컬럼 선택
    # [다중 DB 확장] elif 로 새 테이블 분기 추가
    if table == TABLE_RAW:
        allowed_fields = ALLOWED_RAW_FIELDS
    elif table == TABLE_REPORT:
        allowed_fields = ALLOWED_REPORT_FIELDS
    # elif table == TABLE_EQP_UTIL:
    #     allowed_fields = ALLOWED_EQP_UTIL_FIELDS
    # elif table == TABLE_MAINTENANCE:
    #     allowed_fields = ALLOWED_MAINTENANCE_FIELDS
    else:
        allowed_fields = frozenset()

    # ── filters 검사 ─────────────────────────────────────────
    filters = qj.get("filters", {})
    if not isinstance(filters, dict):
        return False, "filters 는 dict 여야 합니다."

    for field, value in filters.items():
        if field == "act_time_range":
            ok, msg = _validate_act_time_range(value)
            if not ok:
                return False, msg
            continue
        if field == "yyyy_filter":
            ok, msg = _validate_yyyy_filter(value)
            if not ok:
                return False, msg
            continue
        if field == "yyyymmdd_range":
            ok, msg = _validate_yyyymmdd_range(value)
            if not ok:
                return False, msg
            continue
        if field not in allowed_fields:
            return False, f"허용되지 않은 filter 컬럼: '{field}'"
        if not isinstance(value, (list, str)):
            return False, f"filter '{field}' 의 값은 list 또는 str 여야 합니다."

    # ── aggregations 검사 ────────────────────────────────────
    aggregations = qj.get("aggregations", [])
    if not isinstance(aggregations, list):
        return False, "aggregations 는 list 여야 합니다."

    seen_aliases: set = set()
    for agg in aggregations:
        if not isinstance(agg, dict):
            return False, "aggregations 의 각 항목은 dict 여야 합니다."

        func  = agg.get("func", "")
        field = agg.get("field", "")
        alias = agg.get("alias", "")

        if func not in ALLOWED_AGG_FUNCS:
            return False, f"허용되지 않은 집계 함수: '{func}'. 허용값: {sorted(ALLOWED_AGG_FUNCS)}"

        if field not in allowed_fields:
            return False, f"허용되지 않은 집계 컬럼: '{field}'"

        # Raw 테이블에서 count 외 집계는 pk 또는 숫자형 컬럼만 허용
        # Raw 는 이벤트 로그이므로 실질적으로 count(pk) 만 의미 있음
        if table == TABLE_RAW and func != "count":
            return False, (
                f"spotfire_raw 테이블에서는 'count' 집계만 허용됩니다. "
                f"(요청된 func='{func}', field='{field}')\n"
                f"Raw 테이블은 이벤트 로그이므로 건수(COUNT) 기반으로만 분석하세요."
            )

        if not alias or not _is_safe_identifier(alias):
            return False, f"alias '{alias}' 가 유효하지 않습니다."

        if alias in seen_aliases:
            return False, f"중복된 alias: '{alias}'"
        seen_aliases.add(alias)

    # ── group_by 검사 ────────────────────────────────────────
    group_by = qj.get("group_by", [])
    if not isinstance(group_by, list):
        return False, "group_by 는 list 여야 합니다."

    for field in group_by:
        if field not in allowed_fields:
            return False, f"허용되지 않은 group_by 컬럼: '{field}'"

    # Raw 테이블 group_by 계층 가이드 (검증은 하지 않고 LLM system prompt 에서 유도)
    # 권장 계층: line → line+eqp_id → line+eqp_id+param_type
    #           → line+eqp_id+param_type+param_name

    # ── order_by 검사 ────────────────────────────────────────
    order_by = qj.get("order_by", [])
    if not isinstance(order_by, list):
        return False, "order_by 는 list 여야 합니다."

    orderable = set(group_by) | seen_aliases | allowed_fields

    for item in order_by:
        if not isinstance(item, dict):
            return False, "order_by 의 각 항목은 dict 여야 합니다."
        direction = item.get("direction", "asc")
        if direction not in ALLOWED_ORDER_DIRS:
            return False, f"허용되지 않은 order 방향: '{direction}'"
        field = item.get("field", "")
        if field not in orderable:
            return False, f"order_by 에서 허용되지 않는 필드: '{field}'"

    # ── limit 검사 ───────────────────────────────────────────
    limit = qj.get("limit", 100)
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        return False, f"limit 은 1 ~ {MAX_LIMIT} 사이의 정수여야 합니다. (현재: {limit})"

    return True, None


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────

def _validate_act_time_range(value: dict) -> tuple[bool, str | None]:
    if not isinstance(value, dict):
        return False, "act_time_range 는 dict 여야 합니다."

    missing = ACT_TIME_RANGE_KEYS - set(value.keys())
    if missing:
        return False, f"act_time_range 에 필수 키가 없습니다: {missing}"

    flag_val = value.get("flag")
    if flag_val not in ALLOWED_FLAGS:
        return False, (
            f"act_time_range.flag 허용값은 M(월)/W(주)/D(일) 뿐입니다. "
            f"(받은 값: '{flag_val}') "
            f"'Y'(연) 등은 지원하지 않습니다. M/W/D 중 하나를 사용하세요."
        )

    yyyy = value.get("yyyy", "")
    if not (isinstance(yyyy, str) and yyyy.isdigit() and len(yyyy) == 4):
        return False, f"act_time_range.yyyy 는 4자리 연도 문자열이어야 합니다. (현재: '{yyyy}')"

    return True, None


def _validate_yyyymmdd_range(value) -> tuple[bool, str | None]:
    """
    yyyymmdd_range 형식 검증.
    예: {"start": "20260101", "end": "20260331"}
    """
    if not isinstance(value, dict):
        return False, "yyyymmdd_range 는 dict 여야 합니다. 예) {'start': '20260101', 'end': '20260331'}"
    start = value.get("start", "")
    end   = value.get("end",   "")
    for label, v in [("start", start), ("end", end)]:
        if not (isinstance(v, str) and v.isdigit() and len(v) == 8):
            return False, f"yyyymmdd_range.{label} 는 8자리 숫자 문자열이어야 합니다. (받은 값: '{v}')"
    if start > end:
        return False, f"yyyymmdd_range.start({start}) 가 end({end}) 보다 클 수 없습니다."
    return True, None


def _validate_yyyy_filter(value) -> tuple[bool, str | None]:
    """
    yyyy_filter 의 형식을 검증한다.
    예: ["2025", "2026"]  또는  "2026"
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        return False, "yyyy_filter 는 연도 문자열 리스트여야 합니다. 예) ['2025', '2026']"
    for y in value:
        if not (isinstance(y, str) and y.isdigit() and len(y) == 4):
            return False, f"yyyy_filter 의 각 값은 4자리 연도 문자열이어야 합니다. (받은 값: '{y}')"
    return True, None


def _is_safe_identifier(name: str) -> bool:
    return bool(name) and all(c.isalnum() or c == "_" for c in name)