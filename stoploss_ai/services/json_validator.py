"""
stoploss_ai/services/json_validator.py

[변경 이력]
  - line → area 반영
  - ALLOWED_REPORT_FIELDS 에 eng, etc, stepchg, std_time, rd 추가
"""
from stoploss_ai.models import TABLE_EQP_LOSS, TABLE_STOPLOSS_REPORT, LOSS_COLUMNS

ALLOWED_TABLES = frozenset({TABLE_EQP_LOSS, TABLE_STOPLOSS_REPORT})

ALLOWED_EQP_LOSS_FIELDS = frozenset({
    # TpmEqpLoss 실제 컬럼 (tpm_eqp_loss 테이블 기준)
    "yyyymmdd", "eqp_id",
    "start_time", "end_time",
    "state", "down_comment",
    "pk",
    "yyyymmdd_range",
})

ALLOWED_REPORT_FIELDS = frozenset({
    "yyyy", "flag", "flagdate",
    "area", "sdwt_prod", "eqp_id", "eqp_model", "prc_group",
    "plan_time",
    "stoploss", "pm", "qual", "bm",
    "eng", "etc", "stepchg", "std_time", "rd",
    "rank", "pk",
})

ALLOWED_AGG_FUNCS   = frozenset({"count", "avg", "sum", "max", "min"})
ALLOWED_ORDER_DIRS  = frozenset({"asc", "desc"})
MAX_LIMIT           = 10000
ACT_TIME_RANGE_KEYS = frozenset({"flag", "yyyy", "flagdate"})
ALLOWED_FLAGS       = frozenset({"M", "W", "D"})


def validate_stoploss_query_json(qj: dict) -> tuple:
    if not isinstance(qj, dict):
        return False, "dict 여야 합니다"

    table = qj.get("table")
    if table not in ALLOWED_TABLES:
        return False, f"허용되지 않은 table: '{table}'"

    allowed_fields = (
        ALLOWED_EQP_LOSS_FIELDS if table == TABLE_EQP_LOSS
        else ALLOWED_REPORT_FIELDS
    )

    filters = qj.get("filters", {})
    if not isinstance(filters, dict):
        return False, "filters는 dict여야 합니다"

    for field, value in filters.items():
        if field in ("act_time_range", "yyyy_filter", "yyyymmdd_range"):
            continue
        if field not in allowed_fields:
            return False, f"허용되지 않은 filter: '{field}'"
        if not isinstance(value, (list, str)):
            return False, f"filter '{field}' 값은 list 또는 str이어야 합니다"

    aggregations = qj.get("aggregations", [])
    if not isinstance(aggregations, list):
        return False, "aggregations는 list여야 합니다"

    seen_aliases = set()
    for agg in aggregations:
        if not isinstance(agg, dict):
            return False, "aggregation 항목은 dict여야 합니다"
        func  = agg.get("func", "")
        field = agg.get("field", "")
        alias = agg.get("alias", "")
        if func not in ALLOWED_AGG_FUNCS:
            return False, f"허용되지 않은 집계 함수: '{func}'"
        if field not in allowed_fields:
            return False, f"허용되지 않은 집계 컬럼: '{field}'"
        if not alias or not all(c.isalnum() or c == "_" for c in alias):
            return False, f"유효하지 않은 alias: '{alias}'"
        if alias in seen_aliases:
            return False, f"중복 alias: '{alias}'"
        seen_aliases.add(alias)

    group_by = qj.get("group_by", [])
    if not isinstance(group_by, list):
        return False, "group_by는 list여야 합니다"
    for field in group_by:
        if field not in allowed_fields:
            return False, f"허용되지 않은 group_by: '{field}'"

    order_by = qj.get("order_by", [])
    if not isinstance(order_by, list):
        return False, "order_by는 list여야 합니다"
    orderable = set(group_by) | seen_aliases | allowed_fields
    for item in order_by:
        if not isinstance(item, dict):
            return False, "order_by 항목은 dict여야 합니다"
        if item.get("direction", "asc") not in ALLOWED_ORDER_DIRS:
            return False, f"허용되지 않은 정렬 방향: '{item.get('direction')}'"
        if item.get("field", "") not in orderable:
            return False, f"허용되지 않은 order_by 필드: '{item.get('field')}'"

    limit = qj.get("limit", 100)
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        return False, f"limit은 1~{MAX_LIMIT} 사이여야 합니다"

    return True, None
