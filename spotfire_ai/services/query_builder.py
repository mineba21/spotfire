"""
services/query_builder.py

역할:
- validate_query_json() 을 통과한 query JSON 을 Django ORM QuerySet 으로 변환한다
- Raw SQL 없이 ORM 만 사용 → SQL Injection 위험 없음
- 결과를 JSON 직렬화 가능한 list of dict 로 반환한다

[yyyy_filter 지원]
  연간 비교 질문에서 act_time_range(flag=M/W/D) 대신 사용한다.
  예) {"yyyy_filter": ["2025", "2026"]}
  → yyyymmdd LIKE '2025%' OR yyyymmdd LIKE '2026%'
  → group_by 에 "yyyymmdd" 를 포함하면 연도별 집계 가능
"""

from __future__ import annotations

import datetime
from django.db.models import Q, Count, Avg, Sum, Max, Min

from spotfire_ai.models import SpotfireRaw, SpotfireReport, TABLE_RAW, TABLE_REPORT
from spotfire_ai.services.detail_service import get_date_range

# ─────────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────────

AGG_FUNC_MAP: dict = {
    "count": Count,
    "avg":   Avg,
    "sum":   Sum,
    "max":   Max,
    "min":   Min,
}

HARD_LIMIT: int = 10000


# ─────────────────────────────────────────────────────────────────
# 메인 실행 함수
# ─────────────────────────────────────────────────────────────────

def execute_query(query_json: dict) -> list:
    """
    validate_query_json() 을 통과한 query JSON 을 실행하고
    JSON 직렬화 가능한 list of dict 를 반환한다.
    """
    table_name = query_json.get("table", TABLE_RAW)

    if table_name == TABLE_RAW:
        qs = SpotfireRaw.objects.all()
    elif table_name == TABLE_REPORT:
        qs = SpotfireReport.objects.all()
    else:
        return []

    filters      = query_json.get("filters", {})
    group_by     = query_json.get("group_by", [])
    aggregations = query_json.get("aggregations", [])
    order_by     = query_json.get("order_by", [])
    limit        = min(query_json.get("limit", 100), HARD_LIMIT)

    qs = _apply_filters(qs, filters)

    if group_by or aggregations:
        qs = _apply_aggregations(qs, group_by, aggregations)

    qs = _apply_order_by(qs, order_by)
    qs = qs[:limit]

    return _serialize(list(qs))


# ─────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────

def _detect_db_ymd_format() -> bool:
    """
    DB yyyymmdd 컬럼의 실제 저장 형식을 감지한다.
    샘플 1건을 조회해 하이픈 포함 여부 확인.
    True  → "2026-01-01" (하이픈 형식)
    False → "20260101"   (숫자 형식)
    """
    sample = SpotfireRaw.objects.values_list("yyyymmdd", flat=True).first()
    return "-" in str(sample) if sample else False


def _to_db_ymd(ymd8: str) -> str:
    """
    8자리 숫자 "20260101" → DB 저장 형식으로 변환.
    DB 가 하이픈 형식("2026-01-01")이면 변환, 숫자 형식이면 그대로 반환.
    """
    if _YYYYMMDD_HAS_HYPHEN and len(ymd8) == 8 and ymd8.isdigit():
        return f"{ymd8[:4]}-{ymd8[4:6]}-{ymd8[6:8]}"
    return ymd8


def _to_db_yyyy_prefix(yyyy: str) -> str:
    """
    연도 prefix 를 DB 형식에 맞게 반환.
    하이픈 형식이면 "2026-", 숫자 형식이면 "2026".
    """
    return f"{yyyy}-" if _YYYYMMDD_HAS_HYPHEN else yyyy


# 모듈 로드 시 DB 형식 1회 감지 (이후 캐시)
try:
    _YYYYMMDD_HAS_HYPHEN: bool = _detect_db_ymd_format()
except Exception:
    _YYYYMMDD_HAS_HYPHEN: bool = False


def _apply_filters(qs, filters: dict):
    """
    query JSON 의 filters 딕셔너리를 Django Q 조건으로 변환해 적용한다.

    지원하는 filter 형식:
        act_time_range  : {"flag": "M", "yyyy": "2026", "flagdate": "M02"}
                          → yyyymmdd BETWEEN start_ymd AND end_ymd
        yyyy_filter     : ["2025", "2026"]
                          → yyyymmdd LIKE '2026%' OR yyyymmdd LIKE '2026-%'
        yyyymmdd_range  : {"start": "20260101", "end": "20260331"}
                          → yyyymmdd BETWEEN start AND end (DB 형식 자동 변환)
        리스트           : {"line": ["L1", "L2"]} → WHERE line IN ('L1','L2')
        단일값           : {"line": "L1"}          → WHERE line = 'L1'
    """
    q = Q()

    for field, value in filters.items():

        # ── M/W/D 기간 필터 ──────────────────────────────────
        if field == "act_time_range":
            start_ymd, end_ymd = get_date_range(
                value["flag"], value["yyyy"], value["flagdate"]
            )
            if start_ymd and end_ymd:
                q &= Q(yyyymmdd__gte=_to_db_ymd(start_ymd)) & Q(yyyymmdd__lte=_to_db_ymd(end_ymd))
            continue

        # ── 연도 필터 ─────────────────────────────────────────
        if field == "yyyy_filter":
            years = [value] if isinstance(value, str) else value
            if years:
                year_q = Q()
                for y in years:
                    year_q |= Q(yyyymmdd__startswith=_to_db_yyyy_prefix(str(y)))
                q &= year_q
            continue

        # ── 날짜 범위 필터 ────────────────────────────────────
        # yyyymmdd_range: {"start": "20260101", "end": "20260331"}
        # "1~3월" 같은 월 범위 조회에 사용. DB 형식 자동 변환.
        if field == "yyyymmdd_range":
            start = value.get("start", "")
            end   = value.get("end",   "")
            if start and end:
                q &= Q(yyyymmdd__gte=_to_db_ymd(start)) & Q(yyyymmdd__lte=_to_db_ymd(end))
            continue

        # ── 리스트 필터 → IN ──────────────────────────────────
        if isinstance(value, list):
            if value:
                q &= Q(**{f"{field}__in": value})
            continue

        # ── 단일값 필터 → exact ───────────────────────────────
        if isinstance(value, str) and value:
            q &= Q(**{field: value})

    return qs.filter(q)


def _apply_aggregations(qs, group_by: list, aggregations: list):
    if group_by:
        qs = qs.values(*group_by)

    if aggregations:
        agg_kwargs: dict = {}
        for agg in aggregations:
            func_name = agg["func"]
            field     = agg["field"]
            alias     = agg["alias"]
            func_cls  = AGG_FUNC_MAP.get(func_name)
            if func_cls is None:
                continue
            if func_name == "count":
                agg_kwargs[alias] = Count("pk")
            else:
                agg_kwargs[alias] = func_cls(field)
        if agg_kwargs:
            qs = qs.annotate(**agg_kwargs)

    return qs


def _apply_order_by(qs, order_by: list):
    if not order_by:
        return qs
    ordering = []
    for item in order_by:
        field     = item.get("field", "")
        direction = item.get("direction", "asc")
        if not field:
            continue
        ordering.append(f"-{field}" if direction == "desc" else field)
    return qs.order_by(*ordering) if ordering else qs


def _serialize(rows: list) -> list:
    result = []
    for row in rows:
        if not isinstance(row, dict):
            row = row.__dict__
            row.pop("_state", None)

        serialized: dict = {}
        for key, val in row.items():
            if isinstance(val, datetime.datetime):
                serialized[key] = val.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(val, datetime.date):
                serialized[key] = val.isoformat()
            elif isinstance(val, float):
                serialized[key] = round(val, 4) if val is not None else None
            else:
                serialized[key] = val
        result.append(serialized)

    return result