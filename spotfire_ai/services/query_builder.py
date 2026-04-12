"""
services/query_builder.py

역할:
- validate_query_json() 을 통과한 query JSON 을 Django ORM QuerySet 으로 변환한다
- Raw SQL 없이 ORM 만 사용 → SQL Injection 위험 없음
- 결과를 JSON 직렬화 가능한 list of dict 로 반환한다

컬럼 추가 시:
  1. SpotfireRaw / SpotfireReport 모델에 필드 추가
  2. json_validator.py 의 ALLOWED_*_FIELDS 에 컬럼명 추가
  3. 이 파일은 수정 불필요 (query JSON 스키마가 자동으로 반영됨)
"""

from __future__ import annotations

import datetime
from django.db.models import Q, Count, Avg, Sum, Max, Min

from spotfire_ai.models import SpotfireRaw, SpotfireReport, TABLE_RAW, TABLE_REPORT
from spotfire_ai.services.detail_service import get_date_range

# ─────────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────────

# 집계 함수 매핑 (문자열 → Django ORM 함수 클래스)
AGG_FUNC_MAP: dict = {
    "count": Count,
    "avg":   Avg,
    "sum":   Sum,
    "max":   Max,
    "min":   Min,
}

# 조회 최대 행 수 (validate 에서도 체크하지만 이중 방어)
HARD_LIMIT: int = 500


# ─────────────────────────────────────────────────────────────────
# 메인 실행 함수
# ─────────────────────────────────────────────────────────────────

def execute_query(query_json: dict) -> list:
    """
    validate_query_json() 을 통과한 query JSON 을 실행하고
    JSON 직렬화 가능한 list of dict 를 반환한다.

    흐름:
        table 선택 → filter 적용 → group_by + aggregation → order_by → limit → 직렬화

    파라미터:
        query_json : validate_query_json() 통과 보장된 dict

    반환:
        list of dict (datetime → 문자열 자동 변환 포함)
    """
    table_name = query_json.get("table", TABLE_RAW)

    # ── 기본 QuerySet 선택 ────────────────────────────────────
    if table_name == TABLE_RAW:
        qs = SpotfireRaw.objects.all()
    elif table_name == TABLE_REPORT:
        qs = SpotfireReport.objects.all()
    else:
        return []

    # ── 필터 적용 ─────────────────────────────────────────────
    filters = query_json.get("filters", {})
    qs = _apply_filters(qs, filters)

    # ── group_by + aggregation 적용 ────────────────────────────
    group_by     = query_json.get("group_by", [])
    aggregations = query_json.get("aggregations", [])

    if group_by or aggregations:
        qs = _apply_aggregations(qs, group_by, aggregations)

    # ── order_by 적용 ─────────────────────────────────────────
    order_by = query_json.get("order_by", [])
    qs = _apply_order_by(qs, order_by)

    # ── limit 적용 ────────────────────────────────────────────
    limit = min(query_json.get("limit", 100), HARD_LIMIT)
    qs = qs[:limit]

    # ── 실행 + 직렬화 ─────────────────────────────────────────
    return _serialize(list(qs))


# ─────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────

def _apply_filters(qs, filters: dict):
    """
    query JSON 의 filters 딕셔너리를 Django Q 조건으로 변환해 적용한다.

    지원하는 filter 형식:
        단일값 문자열: {"line": "L1"}        → WHERE line = 'L1'
        리스트        : {"line": ["L1","L2"]} → WHERE line IN ('L1','L2')
        날짜 범위     : {"act_time_range": {"flag":"D","yyyy":"2024","flagdate":"2024-01-15"}}
    """
    q = Q()

    for field, value in filters.items():

        # ── 날짜 범위 특수 처리 ───────────────────────────────
        if field == "act_time_range":
            start_dt, end_dt = get_date_range(
                value["flag"], value["yyyy"], value["flagdate"]
            )
            if start_dt and end_dt:
                q &= Q(act_time__gte=start_dt) & Q(act_time__lte=end_dt)
            continue

        # ── 리스트 필터 → IN ──────────────────────────────────
        if isinstance(value, list):
            if value:  # 빈 리스트 skip
                q &= Q(**{f"{field}__in": value})
            continue

        # ── 단일값 필터 → exact ───────────────────────────────
        if isinstance(value, str) and value:
            q &= Q(**{field: value})

    return qs.filter(q)


def _apply_aggregations(qs, group_by: list, aggregations: list):
    """
    group_by + aggregations 를 Django ORM values().annotate() 로 변환한다.

    count 집계는 항상 Count("pk") 를 사용한다.
    (field 값이 "pk" 여도 다른 값이어도 pk 기준 카운트)
    """
    # group_by 가 있으면 values() 로 그룹화
    if group_by:
        qs = qs.values(*group_by)

    # aggregation 이 있으면 annotate()
    if aggregations:
        agg_kwargs: dict = {}
        for agg in aggregations:
            func_name = agg["func"]    # "count" | "avg" | ...
            field     = agg["field"]   # 집계 대상 컬럼
            alias     = agg["alias"]   # 결과 컬럼 이름

            func_cls = AGG_FUNC_MAP.get(func_name)
            if func_cls is None:
                continue

            # count 는 항상 pk 기준 (NULL 없는 안전한 카운트)
            if func_name == "count":
                agg_kwargs[alias] = Count("pk")
            else:
                agg_kwargs[alias] = func_cls(field)

        if agg_kwargs:
            qs = qs.annotate(**agg_kwargs)

    return qs


def _apply_order_by(qs, order_by: list):
    """
    order_by 리스트를 Django ORM order_by() 인수로 변환한다.
    direction = "desc" 이면 필드명 앞에 "-" 를 붙인다.
    """
    if not order_by:
        return qs

    ordering = []
    for item in order_by:
        field     = item.get("field", "")
        direction = item.get("direction", "asc")
        if not field:
            continue
        # desc: "-field", asc: "field"
        ordering.append(f"-{field}" if direction == "desc" else field)

    return qs.order_by(*ordering) if ordering else qs


def _serialize(rows: list) -> list:
    """
    QuerySet 실행 결과(list of dict or model instance)를
    JSON 직렬화 가능한 list of dict 로 변환한다.

    - datetime → "YYYY-MM-DD HH:MM:SS" 문자열
    - float None → None 유지 (JSON null)
    - Model instance → dict 변환 (aggregation 없는 raw 쿼리 대비)
    """
    result = []
    for row in rows:
        if not isinstance(row, dict):
            # aggregation 없는 경우 model instance 가 올 수 있음
            # values() 를 쓰지 않았을 때 대비
            row = row.__dict__
            row.pop("_state", None)

        serialized: dict = {}
        for key, val in row.items():
            if isinstance(val, datetime.datetime):
                serialized[key] = val.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(val, datetime.date):
                serialized[key] = val.isoformat()
            elif isinstance(val, float):
                # 소수점 4자리로 반올림 (가독성)
                serialized[key] = round(val, 4) if val is not None else None
            else:
                serialized[key] = val
        result.append(serialized)

    return result
