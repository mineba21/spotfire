"""
services/json_validator.py

역할:
- LLM 이 생성한 query JSON 의 안전성 / 형식을 검증한다
- SQL Injection 방지: 모든 테이블명 / 컬럼명 / 함수명을 allowlist 로 제한
- 검증 실패 시 (False, 에러메시지) 반환 → ai_service 에서 재시도 또는 에러 처리

컬럼 추가 시:
  ALLOWED_RAW_FIELDS / ALLOWED_REPORT_FIELDS 에 새 컬럼명을 추가하면 된다.
  SpotfireRaw / SpotfireReport 모델과 동기화가 필요하다.
"""

from __future__ import annotations
from spotfire_ai.models import TABLE_RAW, TABLE_REPORT

# ─────────────────────────────────────────────────────────────────
# Allowlist 상수
# ─────────────────────────────────────────────────────────────────

# 허용 테이블 (models.py 의 TABLE_* 상수를 재사용)
ALLOWED_TABLES: frozenset = frozenset({TABLE_RAW, TABLE_REPORT})

# spotfire_raw 허용 컬럼
# 컬럼 추가 시: 여기에 추가 + SpotfireRaw 모델에도 필드 추가
ALLOWED_RAW_FIELDS: frozenset = frozenset({
    "act_time", "yyyymmdd",
    "line", "sdwt_prod", "eqp_id", "eqp_model", "param_type",
    "item_id", "test_id", "value",
    "pk",  # count 집계용 (primary key)
})

# spotfire_report 허용 컬럼
ALLOWED_REPORT_FIELDS: frozenset = frozenset({
    "yyyy", "flag", "flagdate",
    "line", "sdwt_prod", "eqp_id", "eqp_model", "param_type",
    "cnt", "ratio", "rank",
    "pk",
})

# 허용 집계 함수
ALLOWED_AGG_FUNCS: frozenset = frozenset({"count", "avg", "sum", "max", "min"})

# 허용 정렬 방향
ALLOWED_ORDER_DIRS: frozenset = frozenset({"asc", "desc"})

# limit 최대값 (과도한 조회 방지)
MAX_LIMIT: int = 500

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

    검증 항목:
        1. qj 가 dict 인지
        2. table 이 ALLOWED_TABLES 에 있는지
        3. filters 의 각 field 가 허용 컬럼인지
        4. aggregations 의 func / field 가 허용 값인지
        5. group_by 의 각 field 가 허용 컬럼인지
        6. order_by 의 direction 이 허용 값인지
        7. limit 이 1 ~ MAX_LIMIT 범위인지
    """
    # ── 1. 타입 검사 ──────────────────────────────────────────
    if not isinstance(qj, dict):
        return False, "query JSON 은 dict 여야 합니다."

    # ── 2. table 검사 ─────────────────────────────────────────
    table = qj.get("table")
    if table not in ALLOWED_TABLES:
        return False, f"허용되지 않은 table: '{table}'. 허용값: {sorted(ALLOWED_TABLES)}"

    # 테이블에 맞는 허용 컬럼 선택
    allowed_fields = (
        ALLOWED_RAW_FIELDS if table == TABLE_RAW else ALLOWED_REPORT_FIELDS
    )

    # ── 3. filters 검사 ───────────────────────────────────────
    filters = qj.get("filters", {})
    if not isinstance(filters, dict):
        return False, "filters 는 dict 여야 합니다."

    for field, value in filters.items():
        if field == "act_time_range":
            ok, msg = _validate_act_time_range(value)
            if not ok:
                return False, msg
            continue
        if field not in allowed_fields:
            return False, f"허용되지 않은 filter 컬럼: '{field}'"
        if not isinstance(value, (list, str)):
            return False, f"filter '{field}' 의 값은 list 또는 str 여야 합니다."

    # ── 4. aggregations 검사 ──────────────────────────────────
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

        if not alias or not _is_safe_identifier(alias):
            return False, f"alias '{alias}' 가 유효하지 않습니다. (영문자/숫자/밑줄만 허용)"

        if alias in seen_aliases:
            return False, f"중복된 alias: '{alias}'"
        seen_aliases.add(alias)

    # ── 5. group_by 검사 ──────────────────────────────────────
    group_by = qj.get("group_by", [])
    if not isinstance(group_by, list):
        return False, "group_by 는 list 여야 합니다."

    for field in group_by:
        if field not in allowed_fields:
            return False, f"허용되지 않은 group_by 컬럼: '{field}'"

    # ── 6. order_by 검사 ──────────────────────────────────────
    order_by = qj.get("order_by", [])
    if not isinstance(order_by, list):
        return False, "order_by 는 list 여야 합니다."

    # order_by 에서 사용 가능한 필드: group_by 컬럼 + aggregation alias
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

    # ── 7. limit 검사 ─────────────────────────────────────────
    limit = qj.get("limit", 100)
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        return False, f"limit 은 1 ~ {MAX_LIMIT} 사이의 정수여야 합니다. (현재: {limit})"

    return True, None


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────

def _validate_act_time_range(value: dict) -> tuple[bool, str | None]:
    """
    filters.act_time_range 의 형식을 검증한다.
    예: {"flag": "M", "yyyy": "2024", "flagdate": "M01"}
    """
    if not isinstance(value, dict):
        return False, "act_time_range 는 dict 여야 합니다."

    missing = ACT_TIME_RANGE_KEYS - set(value.keys())
    if missing:
        return False, f"act_time_range 에 필수 키가 없습니다: {missing}"

    if value.get("flag") not in ALLOWED_FLAGS:
        return False, f"act_time_range.flag 는 M/W/D 중 하나여야 합니다."

    yyyy = value.get("yyyy", "")
    if not (isinstance(yyyy, str) and yyyy.isdigit() and len(yyyy) == 4):
        return False, f"act_time_range.yyyy 는 4자리 연도 문자열이어야 합니다. (현재: '{yyyy}')"

    return True, None


def _is_safe_identifier(name: str) -> bool:
    """
    alias / 컬럼명이 SQL safe identifier 인지 검사한다.
    영문자, 숫자, 밑줄(_)만 허용.
    """
    return bool(name) and all(c.isalnum() or c == "_" for c in name)
