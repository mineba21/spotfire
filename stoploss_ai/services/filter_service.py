"""
stoploss_ai/services/filter_service.py

역할:
- request.GET 에서 sidebar 필터 파라미터를 파싱한다
- Report / Raw QuerySet 에 공통으로 적용 가능한 Q 필터를 생성한다
- "ALL" 값이 들어오면 해당 필터를 건너뛴다 (전체 조회)

[변경 이력]
  - line → area 컬럼명 변경 반영
"""

from django.db.models import Q

# ─────────────────────────────────────────────────────────────────
# sidebar 에서 multi-select 로 넘어오는 필터 필드 목록
# ─────────────────────────────────────────────────────────────────
FILTER_FIELDS = [
    "area",
    "sdwt_prod",
    "eqp_model",
    "eqp_id",
    "prc_group",
]

ALL_VALUE = "ALL"


def parse_filters(get_params) -> dict:
    """
    request.GET 을 받아 필드별 선택 값 리스트를 반환한다.

    반환 예시:
        {
            "area":      ["A1", "A2"],
            "sdwt_prod": [],
            "eqp_model": ["MODEL-X"],
            "eqp_id":    [],
            "prc_group": [],
        }
    """
    result = {}
    for field in FILTER_FIELDS:
        values = get_params.getlist(field)
        if not values or ALL_VALUE in values:
            result[field] = []
        else:
            result[field] = values
    return result


def build_q(filters: dict) -> "Q":
    """
    parse_filters() 결과를 Django Q 객체로 변환한다.
    빈 리스트 필드는 조건에서 제외된다 (전체 허용).
    """
    q = Q()
    for field, values in filters.items():
        if values:
            q &= Q(**{f"{field}__in": values})
    return q
