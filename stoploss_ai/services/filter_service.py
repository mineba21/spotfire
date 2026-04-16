"""
stoploss_ai/services/filter_service.py

역할:
- request.GET 에서 sidebar 필터 파라미터를 파싱한다
- Report / Raw QuerySet 에 공통으로 적용 가능한 Q 필터를 생성한다
- "ALL" 값이 들어오면 해당 필터를 건너뛴다 (전체 조회)

spotfire_ai.services.filter_service 와 동일한 패턴으로 독립 구현.
FILTER_FIELDS 는 stoploss_ai 전용으로 param_type 포함.
"""

from django.db.models import Q

# ─────────────────────────────────────────────────────────────────
# sidebar 에서 multi-select 로 넘어오는 필터 필드 목록
# ─────────────────────────────────────────────────────────────────
FILTER_FIELDS = [
    "line",
    "sdwt_prod",
    "eqp_model",
    "eqp_id",
    "param_type",
]

# ALL 을 의미하는 특수 값
ALL_VALUE = "ALL"


def parse_filters(get_params) -> dict:
    """
    request.GET 을 받아 필드별 선택 값 리스트를 반환한다.

    반환 예시:
        {
            "line": ["L1", "L2"],
            "sdwt_prod": [],          # ALL 이거나 미선택 → 빈 리스트
            "eqp_model": ["MODEL-X"],
            "eqp_id": [],
            "param_type": ["MCC"],
        }

    빈 리스트는 "전체 선택" 을 의미한다 (필터 미적용).
    """
    result = {}

    for field in FILTER_FIELDS:
        values = get_params.getlist(field)

        if not values or ALL_VALUE in values:
            result[field] = []
        else:
            result[field] = values

    return result


def build_q(filters: dict) -> Q:
    """
    parse_filters() 결과를 받아 Django Q 객체로 변환한다.
    빈 리스트 필드는 조건에서 제외된다 (전체 허용).

    사용 예:
        q = build_q(filters)
        qs = StoplossReport.objects.filter(q)
    """
    q = Q()  # 초기 Q (아무 조건 없음 = 전체)

    for field, values in filters.items():
        if values:
            q &= Q(**{f"{field}__in": values})

    return q
